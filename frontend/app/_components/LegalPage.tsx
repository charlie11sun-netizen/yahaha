import type { ReactNode } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type LegalPageProps = {
  children: ReactNode;
  title: string;
  updated?: string;
  lead?: string;
  className?: string;
};

export function LegalPage({ children, className, lead, title, updated }: LegalPageProps) {
  return (
    <main className="flex min-h-[calc(100vh-61px)] items-start justify-center px-5 py-12 sm:px-8 lg:px-10">
      <Card className={cn("w-full max-w-3xl gap-8 rounded-lg border-slate-200/80 bg-white/90 py-0 shadow-xl shadow-slate-900/5", className)}>
        <CardHeader className="gap-3 px-6 pt-8 sm:px-10 sm:pt-10">
          <CardTitle className="font-display text-3xl font-semibold tracking-normal text-slate-950 sm:text-4xl">
            {title}
          </CardTitle>
          {updated ? <p className="text-sm font-semibold text-indigo-600">Last updated {updated}</p> : null}
          {lead ? <p className="text-base leading-7 text-slate-600">{lead}</p> : null}
        </CardHeader>
        <CardContent className="px-6 pb-8 sm:px-10 sm:pb-10">
          <div className="space-y-7 text-base leading-7 text-slate-600 [&_h2]:font-display [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:tracking-normal [&_h2]:text-slate-950 [&_li]:pl-1 [&_ol]:ml-5 [&_ol]:list-decimal [&_ol]:space-y-2 [&_p]:text-slate-600 [&_ul]:ml-5 [&_ul]:list-disc [&_ul]:space-y-2">
            {children}
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
