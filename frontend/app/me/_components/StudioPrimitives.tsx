import { ChevronRight } from "lucide-react";
import type { ElementType, ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function StatCard({ icon: Icon, label, value }: { icon: ElementType; label: string; value: string }) {
  return (
    <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
      <CardContent className="flex items-center gap-4 p-5">
        <span className="flex size-11 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
          <Icon size={24} />
        </span>
        <div>
          <p className="text-sm font-medium text-slate-500">{label}</p>
          <strong className="font-display text-2xl font-semibold tracking-normal text-slate-950">{value}</strong>
        </div>
      </CardContent>
    </Card>
  );
}

export function Avatar({ size, user }: { size: "large" | "medium"; user: { init: string; name: string } }) {
  return (
    <div
      aria-label={user.name}
      className={cn(
        "flex items-center justify-center rounded-lg bg-indigo-600 font-display font-semibold text-white shadow-lg shadow-indigo-500/25",
        size === "large" ? "size-24 text-3xl" : "size-14 text-xl",
      )}
    >
      {user.init}
    </div>
  );
}

export function Panel({
  actionLabel,
  children,
  onAction,
  title,
}: {
  actionLabel?: string;
  children: ReactNode;
  onAction?: () => void;
  title: string;
}) {
  return (
    <Card className="rounded-lg border-slate-200/80 bg-white/90 shadow-sm">
      <CardHeader className="flex-row items-center justify-between gap-4">
        <CardTitle className="font-display text-xl font-semibold tracking-normal text-slate-950">{title}</CardTitle>
        {actionLabel && onAction ? (
          <Button className="rounded-lg" onClick={onAction} type="button" variant="outline">
            {actionLabel}
            <ChevronRight size={18} />
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-5">{children}</CardContent>
    </Card>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-8 text-center text-sm text-slate-500">{children}</div>;
}
