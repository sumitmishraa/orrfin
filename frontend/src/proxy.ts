/**
 * Optimistic login check before a page loads (Next 16 "proxy", formerly middleware).
 * No session cookie → straight to /login, so signed-out visitors never see an empty shell.
 * This is a convenience only: the API checks the session itself on every call (BUILD_PLAN §9).
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE = "orrfin_session";

export function proxy(request: NextRequest) {
  if (!request.cookies.has(SESSION_COOKIE)) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Every page except the login page, the API proxy and Next's own files.
  matcher: ["/((?!login|api|_next|favicon.ico).*)"],
};
