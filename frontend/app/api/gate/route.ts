import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { GATE_COOKIE, GATE_TOKEN_COOKIE, gateEnabled, gateToken, safeEqual, sitePassword } from "@/lib/gate";

const COOKIE_MAX_AGE = 60 * 60 * 24 * 30; // 30 days

// POST { password } — verify against SITE_PASSWORD and, on success, drop the
// httpOnly gate cookie so middleware lets this browser through.
export async function POST(req: NextRequest) {
  if (!gateEnabled()) return NextResponse.json({ ok: true });

  let password = "";
  try {
    const body = await req.json();
    if (typeof body?.password === "string") password = body.password;
  } catch {
    // malformed body — treat as an empty (wrong) password
  }

  if (!safeEqual(password, sitePassword())) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }

  const token = await gateToken(password);
  const cookieBase = {
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: COOKIE_MAX_AGE,
  };

  const res = NextResponse.json({ ok: true });
  // httpOnly cookie drives the page gate (middleware) — JS can't forge it.
  res.cookies.set(GATE_COOKIE, token, { ...cookieBase, httpOnly: true });
  // Readable twin so the API client can attach X-Gate-Token to backend calls.
  res.cookies.set(GATE_TOKEN_COOKIE, token, { ...cookieBase, httpOnly: false });
  return res;
}

// DELETE — lock the site again for this browser (clears the gate cookie).
export async function DELETE() {
  const res = NextResponse.json({ ok: true });
  res.cookies.delete(GATE_COOKIE);
  res.cookies.delete(GATE_TOKEN_COOKIE);
  return res;
}
