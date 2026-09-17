import { NextResponse, type NextRequest } from "next/server";

// Preserve the public host through the existing API rewrite. Browser-supplied
// forwarding headers are replaced, never trusted. The secret stays server-side.
export function proxy(request: NextRequest) {
  const requestHeaders = new Headers(request.headers);
  const host = request.headers.get("host") || request.nextUrl.host;
  let hostname: string;
  try {
    hostname = new URL(`http://${host}`).hostname
      .toLowerCase()
      .replace(/\.$/, "");
  } catch {
    return NextResponse.json(
      { detail: "Invalid request hostname" },
      { status: 400 },
    );
  }
  requestHeaders.set("X-Setu-Host", hostname);
  requestHeaders.set(
    "X-Setu-Proxy-Key",
    process.env.BRAND_PROXY_KEY ||
      (process.env.APP_ENV !== "production" ? "setu-development-proxy" : ""),
  );
  return NextResponse.next({ request: { headers: requestHeaders } });
}
export const config = { matcher: "/api/v1/:path*" };
