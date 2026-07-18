import { AlertCircle, Check, Circle, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { AuthorTeamProgress, AuthorTeamRoleStatus } from "../_lib/author-team";

export function AuthorTeamProgressList({ compact = false, progress }: { compact?: boolean; progress: AuthorTeamProgress }) {
  return (
    <ol
      aria-label="Implementation team progress"
      className={cn("grid gap-2", compact ? "sm:grid-cols-5" : "sm:grid-cols-2 lg:grid-cols-5")}
    >
      {progress.roles.map((role) => (
        <li
          className={cn(
            "flex min-w-0 items-center gap-2 rounded-lg border px-2.5 py-2",
            role.status === "running"
              ? "border-indigo-200 bg-indigo-50 text-indigo-800"
              : role.status === "completed"
                ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                : role.status === "partial"
                  ? "border-amber-200 bg-amber-50 text-amber-800"
                : role.status === "failed"
                  ? "border-rose-200 bg-rose-50 text-rose-800"
                  : role.status === "skipped"
                    ? "border-amber-200 bg-amber-50 text-amber-800"
                    : "border-slate-200 bg-white text-slate-500",
          )}
          key={role.name}
          title={role.detail}
        >
          <RoleMarker status={role.status} />
          <span className="min-w-0 text-[11px] font-semibold leading-4">{role.label}</span>
        </li>
      ))}
    </ol>
  );
}

function RoleMarker({ status }: { status: AuthorTeamRoleStatus }) {
  const className = "size-3.5 shrink-0";
  if (status === "running") return <Loader2 className={cn(className, "animate-spin")} />;
  if (status === "completed") return <Check className={className} />;
  if (status === "partial") return <AlertCircle className={className} />;
  if (status === "failed") return <AlertCircle className={className} />;
  return <Circle className={className} />;
}
