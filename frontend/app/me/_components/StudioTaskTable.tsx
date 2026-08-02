import { ChevronRight, Sparkles, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Task } from "@/lib/types";
import { shortId, taskActionLabel, taskStatusLabel, taskStep } from "../_lib/studio-format";
import { EmptyState } from "./StudioPrimitives";

export function TaskTable({
  deletingId,
  emptyLabel,
  onDelete,
  onOpen,
  tasks,
}: {
  deletingId: string | null;
  emptyLabel: string;
  onDelete: (task: Task) => void;
  onOpen: (task: Task) => void;
  tasks: Task[];
}) {
  if (tasks.length === 0) return <EmptyState>{emptyLabel}</EmptyState>;

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <div className="hidden grid-cols-[minmax(0,1.4fr)_120px_120px_120px_160px] gap-3 bg-slate-50 px-4 py-3 text-xs font-bold uppercase tracking-[0.14em] text-slate-500 lg:grid">
        <span>Task / Prompt</span>
        <span>Task ID</span>
        <span>Status</span>
        <span>Step</span>
        <span>Action</span>
      </div>
      {tasks.map((task) => (
        <div className="grid gap-3 border-t border-slate-200 bg-white px-4 py-4 lg:grid-cols-[minmax(0,1.4fr)_120px_120px_120px_160px] lg:items-center" key={task.id}>
          <div className="flex min-w-0 gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
              <Sparkles size={16} />
            </span>
            <div className="min-w-0">
              <strong className="line-clamp-1 text-sm font-semibold text-slate-950">{task.game_title || task.idea || "Untitled game"}</strong>
              <p className="line-clamp-2 text-sm leading-6 text-slate-500">{task.idea}</p>
            </div>
          </div>
          <span className="font-mono text-xs text-slate-500">{shortId(task.id)}</span>
          <Badge className={taskBadgeClass(task.status)} variant="outline">
            {taskStatusLabel(task.status)}
          </Badge>
          <span className="text-sm text-slate-600">{taskStep(task)}</span>
          <div className="flex items-center gap-2">
            <Button className="rounded-lg" onClick={() => onOpen(task)} type="button" variant="outline">
              {taskActionLabel(task)}
              <ChevronRight size={17} />
            </Button>
            <Button
              aria-label="Delete task"
              className="rounded-lg text-rose-700 hover:text-rose-700"
              disabled={deletingId === task.id}
              onClick={() => onDelete(task)}
              size="icon"
              type="button"
              variant="outline"
            >
              <Trash2 size={15} />
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}

function taskBadgeClass(status: Task["status"]) {
  if (status === "succeeded") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "failed") return "border-rose-200 bg-rose-50 text-rose-700";
  if (status === "cancelled") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-indigo-200 bg-indigo-50 text-indigo-700";
}
