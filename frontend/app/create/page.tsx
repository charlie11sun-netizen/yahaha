"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import type { AgentLogItem, StepSummary, Task, UploadedAsset } from "@/lib/types";

/* ---------------- palette (indigo / emerald per design doc) ---------------- */
const INDIGO = "#6366f1";
const INDIGO_D = "#4f46e5";
const INDIGO_BG = "#eef2ff";
const EMERALD = "#10b981";
const EMERALD_BG = "#ecfdf5";
const RED = "#ef4444";
const RED_BG = "#fef2f2";
const INK = "#0f172a";
const SLATE = "#475569";
const SLATE_L = "#94a3b8";
const BORDER = "#e7e9f1";
const CARD = "#ffffff";
const PAGE = "#f6f7fb";
const MONO = "'IBM Plex Mono', ui-monospace, monospace";

const card: React.CSSProperties = { background: CARD, border: `1px solid ${BORDER}`, borderRadius: 18, padding: 20 };

/* ---------------- icons (inline svg) ---------------- */
const sv = (s: number) => ({ width: s, height: s, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const });
const IcCheck = ({ s = 15 }: { s?: number }) => (<svg {...sv(s)} strokeWidth={2.6}><polyline points="20 6 9 17 4 12" /></svg>);
const IcClock = ({ s = 15 }: { s?: number }) => (<svg {...sv(s)}><circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15 14" /></svg>);
const IcLink = ({ s = 15 }: { s?: number }) => (<svg {...sv(s)}><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1" /><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1" /></svg>);
const IcEye = ({ s = 15 }: { s?: number }) => (<svg {...sv(s)}><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" /></svg>);
const IcPencil = ({ s = 14 }: { s?: number }) => (<svg {...sv(s)}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>);
const IcBot = ({ s = 16 }: { s?: number }) => (<svg {...sv(s)}><rect x="4" y="8" width="16" height="11" rx="3" /><path d="M12 8V4" /><circle cx="9" cy="13" r="1" /><circle cx="15" cy="13" r="1" /></svg>);
const IcFolder = ({ s = 16 }: { s?: number }) => (<svg {...sv(s)}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></svg>);
const IcDoc = ({ s = 15 }: { s?: number }) => (<svg {...sv(s)}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><polyline points="14 3 14 8 19 8" /><line x1="9" y1="13" x2="15" y2="13" /><line x1="9" y1="17" x2="13" y2="17" /></svg>);
const IcPlay = ({ s = 15 }: { s?: number }) => (<svg {...sv(s)} fill="currentColor" stroke="none"><polygon points="6 4 20 12 6 20" /></svg>);
const IcX = ({ s = 18 }: { s?: number }) => (<svg {...sv(s)}><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>);
const IcAlert = ({ s = 15 }: { s?: number }) => (<svg {...sv(s)}><path d="M12 9v4" /><path d="M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg>);
const Spinner = ({ s = 14, c = INDIGO }: { s?: number; c?: string }) => (
  <span style={{ width: s, height: s, borderRadius: "50%", border: `2px solid ${c}33`, borderTopColor: c, display: "inline-block", animation: "pfspin .7s linear infinite" }} />
);

/* ---------------- count-up ---------------- */
function useCountUp(target: number, durationMs = 700): number {
  const [display, setDisplay] = useState(target);
  const ref = useRef(target);
  ref.current = display;
  useEffect(() => {
    const from = ref.current;
    if (from === target) return;
    let raf = 0;
    let start = 0;
    const tick = (t: number) => {
      if (!start) start = t;
      const p = Math.min(1, (t - start) / durationMs);
      setDisplay(Math.round(from + (target - from) * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);
  return display;
}

const STAGES = [
  { key: "safety_intake", title: "检查创意和素材", desc: "确认上传内容格式正确，并过滤不安全的生成请求。" },
  { key: "intent_spec", title: "理解你的游戏创意", desc: "提取游戏类型、核心玩法、胜负条件和操作方式。" },
  { key: "asset_processing", title: "整理素材", desc: "处理你上传的图片，并补齐游戏需要的默认素材。" },
  { key: "game_design", title: "设计玩法规则", desc: "设计机制、数值、范围、波次和胜负条件。" },
  { key: "code_generation", title: "生成游戏代码", desc: "把玩法设计转换成浏览器可运行的 Canvas 游戏。" },
  { key: "build_validation", title: "测试游戏是否可运行", desc: "检查文件是否完整、安全，并确认可在浏览器中运行。" },
  { key: "publish_artifact", title: "准备预览版本", desc: "上传游戏文件，并生成可游玩的预览链接。" },
];
const EXAMPLES = ["像素风太空躲避游戏", "魔法森林塔防游戏", "海底收集金币小游戏"];

/* ================================================================= */
export default function CreatePage() {
  const router = useRouter();
  const qc = useQueryClient();
  const flash = useToast();
  const { user, loading } = useAuth();

  const [idea, setIdea] = useState("");
  const [files, setFiles] = useState<UploadedAsset[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [logsOpen, setLogsOpen] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login?intent=create");
  }, [loading, user, router]);

  const taskQ = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.task(taskId as string),
    enabled: !!taskId,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "pending" || s === "running" ? 800 : false;
    },
  });
  const task = taskQ.data;

  if (loading || !user) return null;

  const onPick = async (fl: FileList | null) => {
    if (!fl || !fl.length) return;
    try {
      const r = await api.upload(fl);
      setFiles((p) => [...p, ...r.assets].slice(0, 5));
    } catch {
      flash("素材上传失败");
    }
  };
  const generate = async () => {
    if (!idea.trim() || busy) return;
    setBusy(true);
    try {
      const r = await api.createTask(idea.trim(), files.map((f) => f.id));
      setTaskId(r.task_id);
    } catch {
      flash("创建生成任务失败");
    } finally {
      setBusy(false);
    }
  };
  const publish = async () => {
    if (!task?.game) return;
    setPublishing(true);
    try {
      await api.publish(task.game.id);
      flash(`《${task.game.title}》已发布到首页`);
      qc.invalidateQueries({ queryKey: ["games"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      router.push("/");
    } finally {
      setPublishing(false);
    }
  };
  const preview = () => task?.game && window.open(`/play/${task.game.id}`, "_blank", "noopener");
  const regenerate = () => { setTaskId(null); setLogsOpen(false); };

  return (
    <div style={{ background: PAGE, minHeight: "calc(100vh - 64px)", color: INK }}>
      <div style={{ maxWidth: 1340, margin: "0 auto", padding: "30px 28px 90px" }}>
        {taskId ? (
          <Dashboard task={task} onPreview={preview} onPublish={publish} onRegenerate={regenerate} onOpenLogs={() => setLogsOpen(true)} publishing={publishing} />
        ) : (
          <InputView idea={idea} setIdea={setIdea} files={files} setFiles={setFiles} onPick={onPick} generate={generate} busy={busy} />
        )}
      </div>
      {logsOpen && task && <LogDrawer task={task} onClose={() => setLogsOpen(false)} />}
    </div>
  );
}

/* ---------------- input view ---------------- */
function InputView(props: {
  idea: string; setIdea: (v: string) => void; files: UploadedAsset[];
  setFiles: React.Dispatch<React.SetStateAction<UploadedAsset[]>>;
  onPick: (fl: FileList | null) => void; generate: () => void; busy: boolean;
}) {
  const { idea, setIdea, files, setFiles, onPick, generate, busy } = props;
  const disabled = !idea.trim() || busy;
  return (
    <div style={{ maxWidth: 760, margin: "0 auto" }}>
      <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 30, fontWeight: 700, letterSpacing: "-.02em", marginBottom: 6 }}>创建一个游戏 <span style={{ color: INDIGO }}>✦</span></h1>
      <p style={{ fontSize: 15, color: SLATE, marginBottom: 24 }}>描述你的创意、附上参考素材，多 Agent 流水线会把它生成为可游玩的游戏。</p>

      <div style={{ ...card, padding: 22 }}>
        <label style={{ display: "block", fontSize: 12.5, fontWeight: 700, color: SLATE, marginBottom: 9 }}>描述你想生成的游戏</label>
        <textarea value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="例如：做一个 2D 像素风塔防小游戏，玩家放置蘑菇塔阻止史莱姆靠近生命水晶，成功防守 5 波后胜利。" style={{ width: "100%", minHeight: 130, resize: "vertical", border: `1px solid ${BORDER}`, borderRadius: 13, padding: 14, fontSize: 14.5, lineHeight: 1.6, outline: "none", background: "#fcfcfe", color: INK }} />
        <p style={{ fontSize: 12.5, color: SLATE_L, marginTop: 8 }}>你可以描述玩法、角色、风格、胜负条件、操作方式和参考素材用途。</p>

        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => setIdea(ex)} style={{ border: `1px dashed #cdd2e3`, background: "#fafbff", cursor: "pointer", color: INDIGO_D, fontSize: 12.5, padding: "6px 12px", borderRadius: 999 }}>✦ {ex}</button>
          ))}
        </div>

        <label onDrop={(e) => { e.preventDefault(); onPick(e.dataTransfer.files); }} onDragOver={(e) => e.preventDefault()}
          style={{ marginTop: 16, display: "flex", flexDirection: "column", alignItems: "center", gap: 6, border: `1.5px dashed #cdd2e3`, borderRadius: 13, padding: 22, cursor: "pointer", background: "#fafbff", textAlign: "center" }}>
          <div style={{ width: 38, height: 38, borderRadius: 10, background: INDIGO_BG, display: "flex", alignItems: "center", justifyContent: "center", color: INDIGO_D }}>↑</div>
          <div style={{ fontSize: 13.5, color: SLATE, fontWeight: 600 }}>上传素材 — 拖拽图片/视频/文件，或点击选择</div>
          <div style={{ fontSize: 12, color: SLATE_L }}>建议至少一张图片作为封面或素材 · 单文件 ≤10MB · 最多 5 个</div>
          <input type="file" multiple onChange={(e) => { onPick(e.target.files); e.target.value = ""; }} style={{ display: "none" }} />
        </label>

        {files.length > 0 && (
          <div style={{ display: "flex", gap: 9, flexWrap: "wrap", marginTop: 13 }}>
            {files.map((f, i) => (
              <div key={f.id} style={{ display: "flex", alignItems: "center", gap: 8, background: "#f7f8fc", border: `1px solid ${BORDER}`, borderRadius: 10, padding: "7px 9px", maxWidth: 220 }}>
                {f.kind === "image" ? <div style={{ width: 30, height: 30, borderRadius: 6, flex: "none", backgroundImage: `url(${f.url})`, backgroundSize: "cover", backgroundPosition: "center" }} /> : <div style={{ width: 30, height: 30, borderRadius: 6, background: "#e7e9f4", display: "flex", alignItems: "center", justifyContent: "center", color: SLATE_L }}>▤</div>}
                <span style={{ fontSize: 12, color: SLATE, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 120 }}>{f.name}</span>
                <button onClick={() => setFiles((p) => p.filter((_, j) => j !== i))} style={{ border: "none", background: "none", cursor: "pointer", color: SLATE_L, fontSize: 14 }}>✕</button>
              </div>
            ))}
          </div>
        )}

        <button onClick={generate} disabled={disabled} title={!idea.trim() ? "请输入游戏创意后开始生成" : ""}
          style={{ width: "100%", marginTop: 16, border: "none", borderRadius: 12, padding: 14, fontWeight: 700, fontSize: 15.5, cursor: disabled ? "not-allowed" : "pointer", background: disabled ? "#e2e5f0" : INDIGO, color: disabled ? SLATE_L : "#fff", boxShadow: disabled ? "none" : `0 8px 20px ${INDIGO}44` }}>
          {busy ? "正在创建生成任务…" : "生成游戏"}
        </button>
      </div>
    </div>
  );
}

/* ---------------- generation dashboard ---------------- */
function Dashboard({ task, onPreview, onPublish, onRegenerate, onOpenLogs, publishing }: {
  task?: Task; onPreview: () => void; onPublish: () => void; onRegenerate: () => void; onOpenLogs: () => void; publishing: boolean;
}) {
  const tokens = useCountUp(task?.tokens ?? 0);
  const summaries: StepSummary[] = task?.step_summaries ?? STAGES.map((s) => ({ step: s.key, title: s.title, status: "pending" as const }));
  const status = task?.status ?? "pending";
  const succeeded = status === "succeeded";
  const failed = status === "failed";

  let curIdx = summaries.findIndex((s) => s.status === "running");
  if (curIdx < 0) {
    let lastDone = -1;
    summaries.forEach((s, i) => { if (s.status === "completed") lastDone = i; });
    curIdx = succeeded ? STAGES.length - 1 : Math.min(lastDone + 1, STAGES.length - 1);
  }
  const cur = STAGES[curIdx] ?? STAGES[0];
  const doneCount = summaries.filter((s) => s.status === "completed").length;
  const stepNo = succeeded ? STAGES.length : Math.min(curIdx + 1, STAGES.length);

  const badge = succeeded ? { t: "已完成", c: EMERALD, bg: EMERALD_BG } : failed ? { t: "失败", c: RED, bg: RED_BG } : status === "pending" ? { t: "排队中", c: SLATE, bg: "#f1f5f9" } : { t: "运行中", c: INDIGO_D, bg: INDIGO_BG };

  return (
    <>
      {/* header strip */}
      <div style={{ ...card, display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap", marginBottom: 18 }}>
        <div style={{ width: 52, height: 52, borderRadius: 14, flex: "none", background: task?.game?.cover || "linear-gradient(135deg,#6366f1,#a855f7)", boxShadow: "inset 0 0 0 1px rgba(0,0,0,.05)" }} />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontFamily: "'Space Grotesk'", fontWeight: 700, fontSize: 20, letterSpacing: "-.01em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: 360 }}>{task?.game_title || "正在命名…"}</span>
            <span style={{ color: SLATE_L, display: "inline-flex" }}><IcPencil /></span>
          </div>
          <div style={{ fontSize: 12.5, color: SLATE_L }}>由多 Agent 流水线生成</div>
        </div>
        <div style={{ flex: 1 }} />
        <ArtifactChip icon={<IcLink />} label="Manifest URL" value={task?.manifest_url ?? null} />
        <ArtifactChip icon={<IcEye />} label="Preview URL" value={task?.preview_url ?? null} />
      </div>

      {/* two columns */}
      <div style={{ display: "grid", gridTemplateColumns: "340px 1fr", gap: 18, alignItems: "start" }}>
        {/* left: title + timeline */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div>
            <h1 style={{ fontFamily: "'Space Grotesk'", fontSize: 24, fontWeight: 700, letterSpacing: "-.02em" }}>正在生成你的游戏 <span style={{ color: INDIGO }}>✦</span></h1>
            <p style={{ fontSize: 13.5, color: SLATE, marginTop: 4, lineHeight: 1.5 }}>我们会把你的创意转换成一个可在浏览器中运行的小游戏。</p>
          </div>
          <div style={card}>
            <div style={{ fontFamily: "'Space Grotesk'", fontWeight: 700, fontSize: 15 }}>生成进度</div>
            <div style={{ fontSize: 12.5, color: SLATE_L, marginBottom: 14, fontFamily: MONO }}>{STAGES.length} 个阶段中的第 {stepNo} 步</div>
            <Timeline summaries={summaries} curIdx={curIdx} />
          </div>
        </div>

        {/* right: stage detail + cards */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <CurrentStageCard cur={cur} status={status} badge={badge} tokens={tokens} failed={failed} error={task?.error} repair={task?.repair_attempts} replan={task?.replan_attempts} />
          {task?.design && <DesignDraft design={task.design} cover={task?.game?.cover} />}
          {(task?.assets?.length ?? 0) > 0 && <AssetGrid assets={task!.assets!} />}
          <AgentSummary logs={task?.logs ?? []} onOpenLogs={onOpenLogs} />
        </div>
      </div>

      {/* action bar */}
      <ActionBar status={status} onPreview={onPreview} onPublish={onPublish} onRegenerate={onRegenerate} onOpenLogs={onOpenLogs} publishing={publishing} hasGame={!!task?.game} />
    </>
  );
}

function ArtifactChip({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | null }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, background: "#f7f8fc", border: `1px solid ${BORDER}`, borderRadius: 12, padding: "9px 14px", minWidth: 190, maxWidth: 280 }}>
      <span style={{ color: value ? INDIGO_D : SLATE_L, display: "inline-flex" }}>{icon}</span>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11, color: SLATE_L, fontWeight: 600 }}>{label}</div>
        <div style={{ fontFamily: MONO, fontSize: 11.5, color: value ? INK : SLATE_L, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{value ? value.replace(/^https?:\/\//, "") : "生成中…"}</div>
      </div>
    </div>
  );
}

function Timeline({ summaries, curIdx }: { summaries: StepSummary[]; curIdx: number }) {
  return (
    <div>
      {STAGES.map((stage, i) => {
        const s = summaries.find((x) => x.step === stage.key);
        const st = s?.status ?? "pending";
        const active = i === curIdx && st !== "completed" && st !== "failed";
        const done = st === "completed";
        const isFailed = st === "failed";
        const last = i === STAGES.length - 1;
        const dotColor = done ? EMERALD : isFailed ? RED : active ? INDIGO : "#cbd2e0";
        return (
          <div key={stage.key} style={{ display: "flex", gap: 12 }}>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              <div style={{ width: 26, height: 26, borderRadius: "50%", flex: "none", display: "flex", alignItems: "center", justifyContent: "center", color: done || isFailed ? "#fff" : active ? INDIGO : SLATE_L, background: done ? EMERALD : isFailed ? RED : "#fff", border: done || isFailed ? "none" : `2px solid ${active ? INDIGO : "#dfe3ee"}` }}>
                {done ? <IcCheck /> : isFailed ? <IcAlert /> : active ? <Spinner /> : <IcClock s={13} />}
              </div>
              {!last && <div style={{ width: 2, flex: 1, minHeight: 18, background: done ? "#bfe9d4" : "#e7e9f1", margin: "3px 0" }} />}
            </div>
            <div style={{ flex: 1, padding: "1px 0 16px", borderRadius: 8, ...(active ? { background: INDIGO_BG, margin: "-3px -8px 13px", padding: "5px 10px 9px" } : {}) }}>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: done ? INK : active ? INDIGO_D : isFailed ? RED : SLATE_L }}>{i + 1}. {stage.title}</div>
              {active && <div style={{ fontSize: 11.5, color: INDIGO_D, fontFamily: MONO, marginTop: 2, display: "flex", alignItems: "center", gap: 6 }}><Spinner s={10} /> 进行中</div>}
              {done && s?.summary && <div style={{ fontSize: 11.5, color: SLATE_L, marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{s.summary}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function CurrentStageCard({ cur, status, badge, tokens, failed, error, repair, replan }: {
  cur: { title: string; desc: string }; status: string; badge: { t: string; c: string; bg: string };
  tokens: number; failed: boolean; error?: string | null; repair?: number; replan?: number;
}) {
  const succeeded = status === "succeeded";
  return (
    <div style={card}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontSize: 12, color: SLATE_L, fontWeight: 600, letterSpacing: ".02em" }}>当前阶段</div>
          <div style={{ fontFamily: "'Space Grotesk'", fontSize: 21, fontWeight: 700, letterSpacing: "-.01em", marginTop: 3 }}>{succeeded ? "游戏生成完成" : failed ? "生成没有完成" : cur.title}</div>
        </div>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontFamily: MONO, fontSize: 12, fontWeight: 600, color: badge.c, background: badge.bg, padding: "5px 11px", borderRadius: 999, whiteSpace: "nowrap" }}>
          {!succeeded && !failed && <Spinner s={11} c={badge.c} />}{badge.t}
        </span>
      </div>
      <p style={{ fontSize: 14, color: SLATE, lineHeight: 1.55, marginTop: 10 }}>
        {succeeded ? "你现在可以预览、发布到首页，或者重新生成一个版本。" : failed ? (error || "我们在测试游戏时发现了无法自动修复的问题。可以重新生成，或简化创意后再试。") : cur.desc}
      </p>
      <div style={{ display: "flex", gap: 22, marginTop: 14, paddingTop: 14, borderTop: `1px solid ${BORDER}` }}>
        <Metric label="tokens" value={tokens.toLocaleString()} hot={!succeeded && !failed} />
        <Metric label="自动修复" value={`${repair ?? 0}`} />
        <Metric label="重新规划" value={`${replan ?? 0}`} />
      </div>
    </div>
  );
}
function Metric({ label, value, hot }: { label: string; value: string; hot?: boolean }) {
  return (
    <div>
      <div style={{ fontFamily: "'Space Grotesk'", fontSize: 19, fontWeight: 700, color: hot ? INDIGO_D : INK }}>{value}</div>
      <div style={{ fontSize: 11.5, color: SLATE_L, fontFamily: MONO }}>{label}</div>
    </div>
  );
}

function DesignDraft({ design, cover }: { design: NonNullable<Task["design"]>; cover?: string }) {
  const fields = design.fields;
  const mid = Math.ceil(fields.length / 2);
  const cols = [fields.slice(0, mid), fields.slice(mid)];
  return (
    <div style={card}>
      <SectionTitle icon={<IcDoc />} text="游戏设计草案" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 18, marginTop: 14, alignItems: "start" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px 18px" }}>
          {cols.map((col, ci) => (
            <div key={ci} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {col.map((f) => (
                <div key={f.label} style={{ fontSize: 13 }}>
                  <span style={{ color: SLATE_L, marginRight: 8 }}>{f.label}：</span>
                  <span style={{ color: INK, fontWeight: 500 }}>{f.value}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
        <div style={{ position: "relative", height: 168, borderRadius: 14, overflow: "hidden", background: cover || "linear-gradient(135deg,#34d399,#3b82f6)" }}>
          <div style={{ position: "absolute", width: 120, height: 120, borderRadius: "50%", background: "rgba(255,255,255,.18)", top: -34, right: -24 }} />
          <div style={{ position: "absolute", width: 60, height: 60, borderRadius: 16, background: "rgba(0,0,0,.12)", bottom: 20, left: 26, transform: "rotate(16deg)" }} />
          <span style={{ position: "absolute", bottom: 12, left: 14, fontFamily: MONO, fontSize: 11, color: "#fff", background: "rgba(0,0,0,.32)", padding: "4px 9px", borderRadius: 999 }}>2D Canvas 概念预览</span>
        </div>
      </div>
    </div>
  );
}

function AssetGrid({ assets }: { assets: NonNullable<Task["assets"]> }) {
  const tone = (ty: string) => ty === "uploaded" ? { c: INDIGO_D, bg: INDIGO_BG } : ty === "generated" ? { c: EMERALD, bg: EMERALD_BG } : { c: SLATE, bg: "#f1f5f9" };
  return (
    <div style={card}>
      <SectionTitle icon={<IcFolder />} text="素材处理" />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(190px,1fr))", gap: 12, marginTop: 14 }}>
        {assets.map((a, i) => {
          const t = tone(a.type);
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 11, border: `1px solid ${BORDER}`, borderRadius: 12, padding: 11 }}>
              {a.kind === "image" && a.url ? <div style={{ width: 38, height: 38, borderRadius: 8, flex: "none", backgroundImage: `url(${a.url})`, backgroundSize: "cover", backgroundPosition: "center" }} /> : <div style={{ width: 38, height: 38, borderRadius: 8, flex: "none", background: "#eef0f7", display: "flex", alignItems: "center", justifyContent: "center", color: SLATE_L }}>▤</div>}
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{a.name}</div>
                <span style={{ fontSize: 11, fontWeight: 600, color: t.c, background: t.bg, padding: "1px 7px", borderRadius: 999, display: "inline-block", marginTop: 3 }}>{a.status}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AgentSummary({ logs, onOpenLogs }: { logs: AgentLogItem[]; onOpenLogs: () => void }) {
  return (
    <div style={card}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <SectionTitle icon={<IcBot />} text="Agent 执行摘要" />
        <button onClick={onOpenLogs} style={{ display: "inline-flex", alignItems: "center", gap: 6, border: `1px solid ${BORDER}`, background: "#fff", cursor: "pointer", color: INDIGO_D, fontSize: 12.5, fontWeight: 600, padding: "6px 11px", borderRadius: 9 }}><IcDoc s={14} /> 查看日志</button>
      </div>
      <div style={{ marginTop: 12, display: "flex", flexDirection: "column" }}>
        {logs.length === 0 && <div style={{ fontSize: 13, color: SLATE_L, padding: "8px 0" }}>等待 Agent 执行…</div>}
        {logs.map((l, i) => {
          const running = l.status === "running";
          const failed = l.status === "failed";
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 11, padding: "9px 0", borderTop: i ? `1px solid #f1f2f7` : "none" }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", flex: "none", background: running ? INDIGO : failed ? RED : EMERALD }} />
              <span style={{ fontFamily: MONO, fontSize: 12, color: INDIGO_D, minWidth: 152 }}>{l.agent_name}</span>
              <span style={{ fontSize: 13, color: SLATE, flex: 1, minWidth: 0, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{l.message}</span>
              {l.duration && <span style={{ fontFamily: MONO, fontSize: 11.5, color: SLATE_L }}>{l.duration}</span>}
              <span style={{ color: running ? INDIGO : failed ? RED : EMERALD, display: "inline-flex" }}>{running ? <Spinner s={12} /> : failed ? <IcAlert s={14} /> : <IcCheck s={14} />}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SectionTitle({ icon, text }: { icon: React.ReactNode; text: string }) {
  return <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "'Space Grotesk'", fontWeight: 700, fontSize: 15 }}><span style={{ color: INDIGO_D, display: "inline-flex" }}>{icon}</span>{text}</div>;
}

function ActionBar({ status, onPreview, onPublish, onRegenerate, onOpenLogs, publishing, hasGame }: {
  status: string; onPreview: () => void; onPublish: () => void; onRegenerate: () => void; onOpenLogs: () => void; publishing: boolean; hasGame: boolean;
}) {
  const succeeded = status === "succeeded";
  const failed = status === "failed";
  const ghost: React.CSSProperties = { border: `1px solid ${BORDER}`, background: "#fff", cursor: "pointer", fontWeight: 600, fontSize: 14, padding: "11px 18px", borderRadius: 11, color: INK, display: "inline-flex", alignItems: "center", gap: 7 };
  const primary: React.CSSProperties = { border: "none", cursor: "pointer", background: INDIGO, color: "#fff", fontWeight: 700, fontSize: 14, padding: "11px 20px", borderRadius: 11, boxShadow: `0 6px 16px ${INDIGO}44`, display: "inline-flex", alignItems: "center", gap: 7 };
  return (
    <div style={{ position: "sticky", bottom: 18, marginTop: 20, display: "flex", alignItems: "center", gap: 12, background: "rgba(255,255,255,.85)", backdropFilter: "blur(8px)", border: `1px solid ${BORDER}`, borderRadius: 14, padding: 14, boxShadow: "0 8px 26px rgba(40,40,80,.08)" }}>
      <button onClick={onOpenLogs} style={ghost}><IcDoc /> 查看 Agent 执行日志</button>
      <div style={{ flex: 1 }} />
      {succeeded ? (
        <>
          <button onClick={onRegenerate} style={ghost}>重新生成</button>
          <button onClick={onPreview} style={ghost}><IcPlay /> 预览游戏</button>
          <button onClick={onPublish} disabled={publishing} style={{ ...primary, opacity: publishing ? 0.7 : 1 }}>{publishing ? "发布中…" : "发布到首页"}</button>
        </>
      ) : failed ? (
        <>
          <button onClick={onRegenerate} style={ghost}>编辑创意</button>
          <button onClick={onRegenerate} style={primary}>重新生成</button>
        </>
      ) : (
        <button disabled aria-disabled style={{ ...primary, background: "#c7cbe0", boxShadow: "none", cursor: "not-allowed" }}><Spinner s={13} c="#fff" /> 生成中，请稍候</button>
      )}
    </div>
  );
}

/* ---------------- log drawer ---------------- */
function LogDrawer({ task, onClose }: { task: Task; onClose: () => void }) {
  const logs = task.logs ?? [];
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 60, background: "rgba(15,23,42,.4)", display: "flex", justifyContent: "flex-end" }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: "min(560px,94vw)", height: "100%", background: "#fff", display: "flex", flexDirection: "column", boxShadow: "-12px 0 40px rgba(0,0,0,.18)", animation: "pfslidein .25s ease" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 22px", borderBottom: `1px solid ${BORDER}` }}>
          <div style={{ fontFamily: "'Space Grotesk'", fontWeight: 700, fontSize: 17 }}>Agent 执行日志</div>
          <button onClick={onClose} style={{ border: "none", background: "#f1f2f7", cursor: "pointer", width: 32, height: 32, borderRadius: 9, color: SLATE, display: "flex", alignItems: "center", justifyContent: "center" }}><IcX /></button>
        </div>
        <div style={{ flex: 1, overflow: "auto", padding: "16px 22px" }}>
          {logs.map((l, i) => {
            const failed = l.status === "failed";
            const running = l.status === "running";
            return (
              <div key={i} style={{ marginBottom: 16 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: running ? INDIGO : failed ? RED : EMERALD }} />
                  <span style={{ fontFamily: MONO, fontSize: 13, fontWeight: 600, color: INK }}>{l.agent_name}</span>
                  <span style={{ fontSize: 11.5, color: SLATE_L, fontFamily: MONO }}>· {l.step}</span>
                  <div style={{ flex: 1 }} />
                  {l.duration && <span style={{ fontSize: 11.5, color: SLATE_L, fontFamily: MONO }}>{l.duration}</span>}
                </div>
                <div style={{ marginTop: 7, background: failed ? RED_BG : "#f7f8fc", border: `1px solid ${failed ? "#fadcdc" : BORDER}`, borderLeft: `2.5px solid ${failed ? RED : running ? INDIGO : EMERALD}`, borderRadius: 9, padding: "9px 12px" }}>
                  {(l.lines.length ? l.lines : [l.message]).map((ln, j) => (
                    <div key={j} style={{ fontFamily: MONO, fontSize: 11.5, lineHeight: 1.75, color: "#475569", whiteSpace: "pre-wrap", wordBreak: "break-word" }}><span style={{ color: "#aab1c9" }}>›</span> {ln}</div>
                  ))}
                </div>
              </div>
            );
          })}
          {logs.length === 0 && <div style={{ color: SLATE_L, fontSize: 14, padding: 20, textAlign: "center" }}>暂无日志</div>}
        </div>
      </div>
    </div>
  );
}
