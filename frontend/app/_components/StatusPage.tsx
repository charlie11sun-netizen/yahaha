import Link from "next/link";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

type StatusAction = {
  href?: string;
  label: string;
  onClick?: () => void;
  variant?: "default" | "outline";
};

type StatusPageProps = {
  actions?: StatusAction[];
  children?: ReactNode;
  code?: string;
  isError?: boolean;
  title?: string;
};

export function StatusPage({ actions = [], children, code, isError = false, title }: StatusPageProps) {
  return (
    <main className="flex min-h-[calc(100vh-61px)] items-center justify-center px-5 py-12">
      <Card className="w-full max-w-lg rounded-lg border-slate-200/80 bg-white/90 text-center shadow-xl shadow-slate-900/5">
        <CardContent className="flex flex-col items-center gap-5 px-6 py-10 sm:px-10">
          {code ? (
            <span className={isError ? "text-sm font-bold uppercase tracking-[0.18em] text-rose-600" : "text-sm font-bold uppercase tracking-[0.18em] text-indigo-600"}>
              {code}
            </span>
          ) : null}
          {title ? <h1 className="font-display text-3xl font-semibold tracking-normal text-slate-950">{title}</h1> : null}
          {children ? <div className="text-base leading-7 text-slate-600">{children}</div> : null}
          {actions.length ? (
            <div className="flex flex-wrap items-center justify-center gap-3 pt-2">
              {actions.map((action) =>
                action.href ? (
                  <Button asChild key={action.label} variant={action.variant ?? "default"}>
                    <Link href={action.href}>{action.label}</Link>
                  </Button>
                ) : (
                  <Button key={action.label} onClick={action.onClick} type="button" variant={action.variant ?? "default"}>
                    {action.label}
                  </Button>
                ),
              )}
            </div>
          ) : null}
        </CardContent>
      </Card>
    </main>
  );
}
