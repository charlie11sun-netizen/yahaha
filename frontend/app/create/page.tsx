"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import type { Step, UploadedAsset } from "@/lib/types";

const ORANGE = "#ff6b35";
const mono = "'IBM Plex Mono'";

const EXAMPLES = [
  "A cozy game where you catch falling stars in a basket, soft warm colors, 30-second rounds",
  "A fast neon endless runner — dodge traffic by switching lanes, gets harder over time",
  "A memory game: repeat the glowing color sequence, one more each round",
];
const AGENT_LIST = [
  { n: "1", agent: "Safety Intake", role: "Screen prompt & assets, block injection" },
  { n: "2", agent: "Intent Spec", role: "Idea → structured GameSpec" },
  { n: "3", agent: "Asset Processing", role: "Uploads → AssetManifest" },
  { n: "4", agent: "Game Design", role: "GameSpec → runnable design" },
  { n: "5", agent: "Code Generation", role: "Render index.html / style.css / game.js" },
  { n: "6", agent: "Build Validation", role: "Safety scan + structure check (→ repair/replan)" },
  { n: "7", agent: "Publish Artifact", role: "Upload to OSS + write meta" },
];

// 数字平滑递增动画（easeOutCubic），让 token 计数"跳动"地累加而非瞬跳
function useCountUp(target: number, durationMs = 700): number {
  const [display, setDisplay] = useState(target);
  const displayRef = useRef(target);
  displayRef.current = display;
  useEffect(() => {
    const from = displayRef.current;
    if (from === target) return;
    let raf = 0;
    let start = 0;
    const tick = (t: number) => {
      if (!start) start = t;
      const p = Math.min(1, (t - start) / durationMs);
      const eased = 1 - Math.pow(1 - p, 3);
      setDisplay(Math.round(from + (target - from) * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);
  return display;
}

export default function CreatePage() {
  const router = useRouter();
  const qc = useQueryClient();
  const flash = useToast();
  const { user, loading } = useAuth();

  const [idea, setIdea] = useState("");
  const [files, setFiles] = useState<UploadedAsset[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login?intent=create");
  }, [loading, user, router]);

  const taskQ = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.task(taskId as string),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "pending" || s === "running" ? 500 : false;
    },
  });
  const task = taskQ.data;
  const status = taskId ? task?.status ?? "running" : "idle";
  const running = status === "running" || status === "pending";
  const succeeded = status === "succeeded";
  const animatedTokens = useCountUp(task?.tokens ?? 0);

  if (loading || !user) return null;

  const onPick = async (fl: FileList | null) => {
    if (!fl || !fl.length) return;
    try {
      const r = await api.upload(fl);
      setFiles((prev) => [...prev, ...r.assets].slice(0, 6));
    } catch {
      flash("Upload failed");
    }
  };

  const generate = async () => {
    if (!idea.trim() || running || busy) return;
    setBusy(true);
    try {
      const r = await api.createTask(idea.trim(), files.map((f) => f.id));
      setTaskId(r.task_id);
    } catch {
      flash("Could not start generation");
    } finally {
      setBusy(false);
    }
  };

  const publish = async () => {
    if (!task?.game) return;
    await api.publish(task.game.id);
    flash(`“${task.game.title}” published to the arcade`);
    qc.invalidateQueries({ queryKey: ["games"] });
    qc.invalidateQueries({ queryKey: ["stats"] });
    router.push("/");
  };

  const genDisabled = !idea.trim() || running;

  return (
    <div style={{ maxWidth: 1140, width: "100%", margin: "0 auto", padding: "30px 28px 80px" }}>
      <div style={{ marginBottom: 26 }}>
        <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 32, fontWeight: 700, letterSpacing: "-.02em", marginBottom: 6 }}>Create a game</h1>
        <p style={{ fontSize: 15, color: "#7a756c" }}>Describe your idea, attach reference art, and watch the multi-agent pipeline build it.</p>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 26, alignItems: "start" }}>
        {/* composer */}
        <div style={{ background: "#fff", border: "1px solid #e8e3d8", borderRadius: 18, padding: 20, boxShadow: "0 2px 8px rgba(40,30,20,.05)" }}>
          <label style={{ display: "block", fontSize: 12.5, fontWeight: 700, color: "#5c574e", letterSpacing: ".02em", marginBottom: 9 }}>YOUR CREATIVE BRIEF</label>
          <textarea value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="e.g. A cozy game where you catch falling stars in a basket. Warm colors, gentle music, 30-second rounds, avoid the red stars…" style={{ width: "100%", minHeight: 130, resize: "vertical", border: "1px solid #e8e3d8", borderRadius: 13, padding: 14, fontSize: 14.5, lineHeight: 1.55, outline: "none", background: "#fdfcf9", color: "#181613" }} />
          <div style={{ display: "flex", gap: 7, flexWrap: "wrap", marginTop: 11 }}>
            {EXAMPLES.map((ex) => (
              <button key={ex} onClick={() => setIdea(ex)} style={{ border: "1px dashed #d8d2c4", background: "#faf8f3", cursor: "pointer", color: "#6b6459", fontSize: 12, padding: "6px 11px", borderRadius: 999, textAlign: "left", maxWidth: "100%", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>✦ {ex}</button>
            ))}
          </div>
          <label
            onDrop={(e) => { e.preventDefault(); onPick(e.dataTransfer.files); }}
            onDragOver={(e) => e.preventDefault()}
            style={{ marginTop: 16, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 7, border: "1.5px dashed #d8d2c4", borderRadius: 13, padding: 22, cursor: "pointer", background: "#fdfcf9", textAlign: "center" }}
          >
            <div style={{ width: 38, height: 38, borderRadius: 10, background: "#fff1ea", display: "flex", alignItems: "center", justifyContent: "center", color: ORANGE, fontSize: 18 }}>↑</div>
            <div style={{ fontSize: 13.5, color: "#5c574e", fontWeight: 600 }}>Drop images, video or files — or click to browse</div>
            <div style={{ fontSize: 12, color: "#a8a294" }}>Reference art, sprites, audio · used by the agents</div>
            <input type="file" multiple onChange={(e) => { onPick(e.target.files); e.target.value = ""; }} style={{ display: "none" }} />
          </label>
          {files.length > 0 && (
            <div style={{ display: "flex", gap: 9, flexWrap: "wrap", marginTop: 13 }}>
              {files.map((f, i) => (
                <div key={f.id} style={{ display: "flex", alignItems: "center", gap: 8, background: "#faf8f3", border: "1px solid #e8e3d8", borderRadius: 10, padding: "7px 9px", maxWidth: 200 }}>
                  {f.kind === "image" ? (
                    <div style={{ width: 30, height: 30, borderRadius: 6, flex: "none", backgroundImage: `url(${f.url})`, backgroundSize: "cover", backgroundPosition: "center" }} />
                  ) : (
                    <div style={{ width: 30, height: 30, borderRadius: 6, background: "#ece7dc", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, color: "#8a8479" }}>▤</div>
                  )}
                  <span style={{ fontSize: 12, color: "#5c574e", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 110 }}>{f.name}</span>
                  <button onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))} style={{ border: "none", background: "none", cursor: "pointer", color: "#b3aca0", fontSize: 14, padding: 0 }}>✕</button>
                </div>
              ))}
            </div>
          )}
          <button onClick={generate} disabled={genDisabled} style={{ width: "100%", marginTop: 16, border: "none", borderRadius: 12, padding: 14, fontWeight: 700, fontSize: 15.5, cursor: genDisabled ? "not-allowed" : "pointer", background: genDisabled ? "#e8e3d8" : ORANGE, color: genDisabled ? "#a8a294" : "#fff", boxShadow: genDisabled ? "none" : "0 8px 20px rgba(255,107,53,.3)" }}>
            {running ? "Generating…" : "Generate game"}
          </button>
          <div style={{ display: "flex", alignItems: "center", gap: 7, marginTop: 12, fontSize: 12, color: "#a8a294", fontFamily: mono }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#1f9d6b" }} /> 5-agent orchestrator · gVisor sandbox · OSS upload
          </div>
        </div>

        {/* output */}
        <div style={{ background: "#fff", border: "1px solid #e8e3d8", borderRadius: 18, overflow: "hidden", boxShadow: "0 2px 8px rgba(40,30,20,.05)", minHeight: 420, display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "15px 18px", borderBottom: "1px solid #f0ece2" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <span style={{ fontFamily: "'Space Grotesk'", fontWeight: 700, fontSize: 15 }}>Generation task</span>
              <StatusPill status={status} />
            </div>
            {status !== "idle" && (
              <span style={{ fontFamily: mono, fontSize: 12.5, color: running ? "#d4501f" : "#7a756c", transition: "color .3s" }}>
                <b style={{ fontWeight: 700 }}>{animatedTokens.toLocaleString()}</b> tokens
              </span>
            )}
          </div>

          {!taskId ? (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", padding: "26px 22px" }}>
              <div style={{ fontSize: 13, color: "#a8a294", fontFamily: mono, letterSpacing: ".04em", marginBottom: 18 }}>PIPELINE · IDLE</div>
              {AGENT_LIST.map((a) => (
                <div key={a.n} style={{ display: "flex", alignItems: "center", gap: 13, padding: "11px 0", borderBottom: "1px solid #f4f1e9" }}>
                  <div style={{ width: 30, height: 30, borderRadius: 9, background: "#faf8f3", border: "1px solid #e8e3d8", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: mono, fontSize: 13, color: "#bdb6a8" }}>{a.n}</div>
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 14, color: "#3a362f" }}>{a.agent}</div>
                    <div style={{ fontSize: 12.5, color: "#a8a294" }}>{a.role}</div>
                  </div>
                </div>
              ))}
              <p style={{ marginTop: 18, fontSize: 13, color: "#a8a294", lineHeight: 1.5 }}>Write a brief and hit generate — each agent&apos;s logs stream here so you can see exactly what&apos;s happening.</p>
            </div>
          ) : (
            <div style={{ flex: 1, padding: "20px 20px 8px", overflow: "auto" }}>
              {(task?.steps ?? []).map((st, i, arr) => (
                <PipelineStep key={st.seq} step={st} last={i === arr.length - 1} />
              ))}
            </div>
          )}

          {succeeded && task?.game && (
            <div style={{ borderTop: "1px solid #f0ece2", padding: 18, background: "#fbfaf6" }}>
              <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                <div style={{ position: "relative", width: 84, height: 62, borderRadius: 11, overflow: "hidden", flex: "none", background: task.game.cover }}>
                  <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <div style={{ width: 0, height: 0, borderLeft: "14px solid rgba(255,255,255,.9)", borderTop: "9px solid transparent", borderBottom: "9px solid transparent", marginLeft: 3 }} />
                  </div>
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: "'Space Grotesk'", fontWeight: 700, fontSize: 17 }}>{task.game.title}</div>
                  <div style={{ fontFamily: mono, fontSize: 11, color: "#7a756c", wordBreak: "break-all", marginTop: 3 }}>{task.game.oss_path}</div>
                </div>
              </div>
              <div style={{ display: "flex", gap: 10, marginTop: 15 }}>
                <button onClick={() => window.open(`/play/${task.game!.id}`, "_blank", "noopener")} style={{ flex: 1, border: "1px solid #e8e3d8", background: "#fff", cursor: "pointer", fontWeight: 600, fontSize: 14, padding: 11, borderRadius: 11, color: "#181613" }}>Preview ↗</button>
                <button onClick={() => setTaskId(null)} style={{ border: "1px solid #e8e3d8", background: "#fff", cursor: "pointer", fontWeight: 600, fontSize: 14, padding: "11px 14px", borderRadius: 11, color: "#181613" }}>Regenerate</button>
                <button onClick={publish} style={{ flex: 1, border: "none", cursor: "pointer", background: ORANGE, color: "#fff", fontWeight: 700, fontSize: 14, padding: 11, borderRadius: 11, boxShadow: "0 6px 16px rgba(255,107,53,.3)" }}>Publish</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, { bg: string; color: string; label: string }> = {
    running: { bg: "#fff1ea", color: "#d4501f", label: "running" },
    pending: { bg: "#fff1ea", color: "#d4501f", label: "running" },
    succeeded: { bg: "#e7f6ee", color: "#1f9d6b", label: "succeeded" },
    failed: { bg: "#fdecea", color: "#e2483d", label: "failed" },
    idle: { bg: "#f4f1e9", color: "#8a8479", label: "idle" },
  };
  const s = map[status] ?? map.idle;
  return <span style={{ fontFamily: mono, fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 999, letterSpacing: ".03em", background: s.bg, color: s.color }}>{s.label}</span>;
}

function PipelineStep({ step, last }: { step: Step; last: boolean }) {
  const done = step.status === "done";
  const running = step.status === "running";
  const failed = step.status === "failed";
  const dotBase: React.CSSProperties = {
    width: 26, height: 26, borderRadius: "50%", flex: "none", display: "flex",
    alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 700, fontFamily: mono,
  };
  const dot: React.CSSProperties = done
    ? { ...dotBase, background: "#1f9d6b", color: "#fff" }
    : failed
      ? { ...dotBase, background: "#e2483d", color: "#fff" }
      : running
        ? { ...dotBase, background: "#fff", border: `2px solid ${ORANGE}` }
        : { ...dotBase, background: "#f4f1e9", border: "1px solid #e8e3d8", color: "#bdb6a8" };
  return (
    <div style={{ display: "flex", gap: 14, animation: "pfrise .3s ease" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={dot}>
          {done ? "✓" : failed ? "!" : running ? (
            <span style={{ width: 11, height: 11, borderRadius: "50%", border: "2px solid #f6dccd", borderTopColor: ORANGE, animation: "pfspin .7s linear infinite" }} />
          ) : step.seq}
        </div>
        {!last && <div style={{ width: 2, flex: 1, minHeight: 16, margin: "5px 0", background: done ? "#cfe9da" : "#ece7dc" }} />}
      </div>
      <div style={{ flex: 1, paddingBottom: 18, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 9, minHeight: 26 }}>
          <span style={{ fontFamily: "'Space Grotesk'", fontWeight: 600, fontSize: 14.5, letterSpacing: "-.01em", color: running ? "#181613" : done ? "#3a362f" : "#a8a294" }}>{step.name}</span>
          {running && <span style={{ fontFamily: mono, fontSize: 10, fontWeight: 600, color: "#d4501f", background: "#fff1ea", padding: "3px 9px", borderRadius: 999, animation: "pfpulse 1.4s infinite" }}>running</span>}
          {done && <span style={{ fontFamily: mono, fontSize: 10.5, color: "#bdb6a8" }}>{step.agent}</span>}
        </div>
        {step.logs.length > 0 && (
          <div style={{ marginTop: 9, background: "#fbf9f4", border: "1px solid #efe9dc", borderLeft: `2.5px solid ${failed ? "#e2483d" : done ? "#1f9d6b" : ORANGE}`, borderRadius: 9, padding: "10px 13px" }}>
            {step.logs.map((ln, i) => (
              <div key={i} style={{ fontFamily: mono, fontSize: 11.5, lineHeight: 1.8, color: "#6b6459", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                <span style={{ color: "#cdbfa3" }}>›</span> {ln}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
