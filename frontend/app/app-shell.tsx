"use client";

import type { ReactNode } from "react";

import Nav from "@/components/Nav";

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-root-layout">
      <Nav />
      <main className="app-root-main">{children}</main>
    </div>
  );
}
