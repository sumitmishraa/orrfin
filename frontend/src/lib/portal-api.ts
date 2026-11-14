/**
 * Calls from the supplier portal to the API (BUILD_PLAN §9 v3.0).
 *
 * Separate from `lib/api.ts` on purpose: that helper sends a signed-out employee to the employee
 * login page, and a supplier must never be sent there. Here a 401 is reported to the page, which
 * shows the portal's own sign-in form.
 */
import { API_URL, APP_HEADERS } from "@/lib/api";

export class PortalAuthError extends Error {}

async function read<T>(response: Response): Promise<T> {
  if (response.status === 401 && !response.url.endsWith("/portal/login")) {
    throw new PortalAuthError("Please sign in to the supplier portal.");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    throw new Error(typeof detail === "string" ? detail : Array.isArray(detail) && detail[0]?.msg ? detail[0].msg : `Request failed (${response.status})`);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export async function portalApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  return read<T>(await fetch(`${API_URL}${path}`, {
    ...init, credentials: "same-origin", headers: { "Content-Type": "application/json", ...APP_HEADERS },
  }));
}

/** Upload one file with a few form fields. The browser sets the multipart content type itself. */
export async function portalUpload<T>(path: string, file: File, fields: Record<string, string>): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  for (const [key, value] of Object.entries(fields)) if (value) form.append(key, value);
  return read<T>(await fetch(`${API_URL}${path}`, { method: "POST", body: form, credentials: "same-origin", headers: APP_HEADERS }));
}
