"use client";

import { ArrowRight, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatRelative, getBrief } from "../_lib/create-state";
import type { Task } from "@/lib/types";

export function TasksDrawer({
  currentTaskId,
  loading,
  now,
  onClose,
  onResume,
  tasks,
}: {
  currentTaskId: string | null;
  loading: boolean;
  now: number;
  onClose: () => void;
  onResume: (id: string) => void;
  tasks: Task[];
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/45 p-3 backdrop-blur-sm" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-xl flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 p-5">
          <div>
            <h2 className="font-display text-2xl font-semibold tracking-normal text-slate-950">My Tasks</h2>
            <p className="mt-1 text-sm text-slate-500">Resume recent generation tasks.</p>
          </div>
          <Button aria-label="Close tasks" onClick={onClose} size="icon" type="button" variant="ghost">
            <X size={18} />
          </Button>
        </header>

        <section className="flex-1 overflow-auto p-5">
          {loading ? <p className="rounded-lg border border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">Loading tasks...</p> : null}
          {!loading && tasks.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500">
              No generation tasks yet.
            </p>
          ) : null}
          <div className="grid gap-3">
            {tasks.map((task) => (
              <button
                className={cn(
                  "grid grid-cols-[auto_1fr_auto] items-center gap-3 rounded-lg border p-4 text-left transition",
                  task.id === currentTaskId
                    ? "border-indigo-200 bg-indigo-50"
                    : "border-slate-200 bg-white hover:border-indigo-200 hover:bg-indigo-50/40",
                )}
                key={task.id}
                onClick={() => onResume(task.id)}
                type="button"
              >
                <span className={cn("size-3 rounded-full", task.status === "succeeded" ? "bg-emerald-500" : task.status === "failed" ? "bg-rose-500" : task.status === "cancelled" ? "bg-amber-500" : "bg-indigo-500")} />
                <div className="min-w-0">
                  <strong className="line-clamp-1 text-sm font-semibold text-slate-950">{getBrief(task, []).title}</strong>
                  <p className="mt-1 text-xs text-slate-500">
                    {task.status} - {formatRelative(task.updated_at || task.created_at, now) || "recently"}
                  </p>
                </div>
                <ArrowRight size={16} className="text-slate-400" />
              </button>
            ))}
          </div>
        </section>
      </aside>
    </div>
  );
}
