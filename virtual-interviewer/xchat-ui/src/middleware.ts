import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (
    pathname === "/" ||
    pathname.startsWith("/virtual-interviewer")
  ) {
    return NextResponse.next();
  }

  const redirectUrl = request.nextUrl.clone();
  redirectUrl.pathname = "/virtual-interviewer";
  redirectUrl.search = "";

  return NextResponse.redirect(redirectUrl);
}

export const config = {
  matcher: [
    "/((?!api|_next|_static|_vercel|landing|favicon.ico|robots.txt|public/).*)",
  ],
};
