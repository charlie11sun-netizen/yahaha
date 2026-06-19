"use client";

import Link from "next/link";
import { useEffect } from "react";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // 预留前端错误上报接入点（Sentry 等）
    console.error(error);
  }, [error]);

  return (
    <div
      style={{
        minHeight: "calc(100vh - 64px)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        padding: "40px 24px",
        background: "#fbfcff",
      }}
    >
      <div style={{ fontFamily: "'IBM Plex Mono'", fontSize: 13, fontWeight: 600, letterSpacing: ".2em", color: "#e2483d", marginBottom: 14 }}>
        SOMETHING WENT WRONG
      </div>
      <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 34, fontWeight: 700, letterSpacing: "-.02em", color: "#181613", marginBottom: 12 }}>
        Unexpected error
      </h1>
      <p style={{ fontSize: 15, color: "#7a756c", maxWidth: 440, lineHeight: 1.6, marginBottom: 26 }}>
        {error?.message || "An unexpected error occurred while rendering this page."}
      </p>
      <div style={{ display: "flex", gap: 11 }}>
        <button
          onClick={() => reset()}
          type="button"
          style={{ border: "none", cursor: "pointer", background: "#ff6b35", color: "#fff", fontWeight: 700, fontSize: 14.5, padding: "12px 22px", borderRadius: 11, boxShadow: "0 8px 20px rgba(255,107,53,.3)" }}
        >
          Try again
        </button>
        <Link
          href="/"
          style={{ textDecoration: "none", border: "1px solid #e8e3d8", background: "#fff", color: "#5c574e", fontWeight: 600, fontSize: 14.5, padding: "12px 22px", borderRadius: 11 }}
        >
          Back to home
        </Link>
      </div>
    </div>
  );
}
