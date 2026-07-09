import { Loader2 } from "lucide-react";

export default function Loading() {
  return (
    <main className="flex min-h-[calc(100vh-61px)] items-center justify-center px-5 py-12">
      <div className="flex items-center gap-3 rounded-lg border border-slate-200/80 bg-white/90 px-5 py-4 text-sm font-semibold text-slate-600 shadow-lg shadow-slate-900/5">
        <Loader2 className="size-5 animate-spin text-indigo-600" />
        Loading...
      </div>
    </main>
  );
}
