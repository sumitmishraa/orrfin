/**
 * Calls the Orrfin API. Requests go to /api/* on this same origin (next.config.ts forwards
 * them), so the HttpOnly session cookie is sent automatically and never touched by scripts.
 * The server enforces every rule; this helper only turns its answers into errors the page can show.
 */
export const API_URL = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type FastApiDetail = string | { msg: string; loc?: (string | number)[] }[];

function readableDetail(detail: FastApiDetail | undefined, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    // Pydantic validation errors: show the field and the reason, e.g. "lines.0.qty: must be greater than 0".
    return detail
      .map((d) => `${(d.loc ?? []).filter((p) => p !== "body").join(".")}: ${d.msg}`)
      .join("; ");
  }
  return `Request failed (${status})`;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  if (response.status === 401 && !path.startsWith("/auth/")) {
    // Session expired or missing: back to the login page. A full page load on purpose, so no
    // cached screen of the signed-out user survives.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.href = "/login";
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, readableDetail(body.detail, response.status));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
}
