import type { Metadata } from "next";

import "./globals.css";
import Nav from "@/components/Nav";
import Providers from "./providers";

export const metadata: Metadata = {
  title: "PlayForge AI - AI Native Game Platform",
  description: "Prompt a game. Play it in seconds.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <Providers>
          <div style={{ minHeight: "100vh", display: "flex", flexDirection: "column", background: "#fbfcff" }}>
            <Nav />
            <main style={{ flex: 1, display: "flex", flexDirection: "column" }}>{children}</main>
          </div>
        </Providers>
      </body>
    </html>
  );
}
