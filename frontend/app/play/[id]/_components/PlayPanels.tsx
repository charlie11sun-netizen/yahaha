import { CircleAlert, CircleCheck, LoaderCircle, ShieldCheck } from "lucide-react";

import { runtimeLabel, type RuntimeKey, type RuntimeStatus } from "../_lib/play-runtime";

export function RuntimeList({
  compact = false,
  runtime,
}: {
  compact?: boolean;
  runtime: Record<RuntimeKey, RuntimeStatus>;
}) {
  const rows: { key: RuntimeKey; label: string }[] = [
    { key: "manifest", label: "Manifest" },
    { key: "sandbox", label: "Sandbox" },
    { key: "bundle", label: "Bundle" },
  ];

  return (
    <div className={`pf-play-runtime${compact ? " is-compact" : ""}`}>
      {rows.map((row) => (
        <div className={`pf-play-runtime-row is-${runtime[row.key]}`} key={row.key}>
          {runtime[row.key] === "ready" ? <CircleCheck size={17} /> : runtime[row.key] === "failed" ? <CircleAlert size={17} /> : runtime[row.key] === "running" ? <LoaderCircle className="pf-spin" size={17} /> : <ShieldCheck size={17} />}
          <span>{row.label}</span>
          <strong>{runtimeLabel(runtime[row.key])}</strong>
        </div>
      ))}
    </div>
  );
}

export function ActivityFeed({ lines }: { lines: string[] }) {
  if (!lines.length) return null;
  return (
    <div className="pf-play-activity">
      {lines.map((line, index) => (
        <p key={`${index}-${line}`}>{line}</p>
      ))}
    </div>
  );
}
