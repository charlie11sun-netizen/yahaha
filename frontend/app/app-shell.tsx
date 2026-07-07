"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import Nav from "@/components/Nav";

function usesLegacyPfStyles(pathname: string | null) {
  if (!pathname) return true;
  return pathname !== "/" && pathname !== "/gate";
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const className = usesLegacyPfStyles(pathname)
    ? "app-root-layout pf-legacy-scope"
    : "app-root-layout";

  return (
    <div className={className}>
      <Nav />
      <main className="app-root-main">{children}</main>
    </div>
  );
}
