import Link from "next/link";

export default function NotFound() {
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
      <div style={{ fontFamily: "'IBM Plex Mono'", fontSize: 13, fontWeight: 600, letterSpacing: ".2em", color: "#ff6b35", marginBottom: 14 }}>
        ERROR 404
      </div>
      <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 40, fontWeight: 700, letterSpacing: "-.02em", color: "#181613", marginBottom: 12 }}>
        Page not found
      </h1>
      <p style={{ fontSize: 15.5, color: "#7a756c", maxWidth: 420, lineHeight: 1.6, marginBottom: 26 }}>
        The page you&apos;re looking for doesn&apos;t exist or may have been moved. Let&apos;s get you back to the arcade.
      </p>
      <Link
        href="/"
        style={{ textDecoration: "none", background: "#ff6b35", color: "#fff", fontWeight: 700, fontSize: 15, padding: "13px 24px", borderRadius: 12, boxShadow: "0 10px 26px rgba(255,107,53,.3)" }}
      >
        Back to arcade
      </Link>
    </div>
  );
}
