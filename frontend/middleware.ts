import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { GATE_COOKIE, GATE_TOKEN_COOKIE, gateEnabled, gateToken, safeEqual, sitePassword } from "@/lib/gate";

// Front-door password gate for the whole site. When SITE_PASSWORD is set, every
// page (the per-user login included) sits behind this; an unlocked visitor is
// bounced to /gate and returned to where they were headed after unlocking.
export async function middleware(req: NextRequest) {
  if (!gateEnabled()) return NextResponse.next();

  const expected = await gateToken(sitePassword());
  const token = req.cookies.get(GATE_COOKIE)?.value;
  if (token && safeEqual(token, expected)) {
    const res = NextResponse.next();
    // Backfill the readable API token for sessions unlocked before it existed,
    // so the backend gate accepts their cross-origin calls without re-unlocking.
    if (req.cookies.get(GATE_TOKEN_COOKIE)?.value !== expected) {
      res.cookies.set(GATE_TOKEN_COOKIE, expected, {
        sameSite: "lax",
        secure: process.env.NODE_ENV === "production",
        path: "/",
        maxAge: 60 * 60 * 24 * 30,
      });
    }
    return res;
  }

  const url = req.nextUrl.clone();
  const target = req.nextUrl.pathname + req.nextUrl.search;
  url.pathname = "/gate";
  url.search = "";
  url.searchParams.set("next", target);
  return NextResponse.redirect(url);
}

export const config = {
  // Gate everything except the gate page/endpoint, Next internals, and public
  // assets (favicon + /public/playforge/*). HMR lives under /_next, so excluding
  // it keeps dev reloads working.
  matcher: ["/((?!_next|favicon.ico|gate|api/gate|playforge/).*)"],
};
