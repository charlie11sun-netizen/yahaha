import http from "node:http";

const taskId = "a5d9791e-0bf7-4402-91ce-4f2794fd0fd3";
const gameId = "mock-game-7a1c";
const previewHtml = encodeURIComponent(`<!doctype html><html><body style="margin:0;background:linear-gradient(135deg,#111827,#312e81);display:grid;place-items:center;height:100vh;color:#c4b5fd;font:700 20px system-ui"><div>遺迹深潜者</div></body></html>`);

const task = {
  id: taskId,
  idea: "制作一款俯视角动作地牢游戏",
  game_title: "遗迹深潜者",
  status: "succeeded",
  progress: 1,
  current_step: 9,
  dimension: "2D",
  task_kind: "generation",
  tokens: 1008205,
  repair_attempts: 0,
  replan_attempts: 0,
  max_repair_attempts: 4,
  max_replan_attempts: 1,
  step_summaries: [
    { title: "Idea checked", step: "idea", status: "succeeded", summary: "Requirements validated." },
    { title: "Game spec created", step: "spec", status: "succeeded", summary: "Core systems outlined." },
    { title: "Assets processed", step: "assets", status: "succeeded", summary: "Assets ready." },
    { title: "Game designed", step: "design", status: "succeeded", summary: "Game structure designed." },
    { title: "Files generated", step: "files", status: "succeeded", summary: "Bundle generated." },
    { title: "Validating build", step: "validate", status: "succeeded", summary: "Build checks passed." },
    { title: "Playtesting game", step: "playtest", status: "succeeded", summary: "Gameplay QA passed." },
    { title: "Preparing preview", step: "preview", status: "succeeded", summary: "Preview mounted." },
    { title: "Ready to publish", step: "publish", status: "succeeded", summary: "Ready to publish." },
  ],
  steps: [],
  logs: [],
  game: {
    id: gameId,
    title: "遗迹深潜者",
    summary: "在古代遗迹中探索、战斗并解开深埋的秘密。",
    author: "Charlie",
    author_id: "mock-user",
    author_init: "C",
    bundle_url: `data:text/html,${previewHtml}`,
    manifest_url: "http://localhost:8000/games/mock/manifest",
    oss_path: "games/mock/index.html",
    cover: null,
    date: "2026-07-16",
    genre: "action_roguelike",
    tags: ["2D", "Phaser"],
    source: "AI generated",
    status: "published",
    from_create: true,
    likes: 0,
    likes_str: "0",
    plays: 0,
    plays_str: "0",
    version: "v1",
  },
  manifest_url: "http://localhost:8000/games/mock/manifest",
  preview_url: "/play/mock-game-7a1c",
  feedback_brief: null,
  feedback_text: null,
  created_at: "2026-07-14T12:00:00Z",
  updated_at: "2026-07-16T12:00:00Z",
};

function json(res, body, status = 200) {
  res.writeHead(status, {
    "Access-Control-Allow-Origin": "http://localhost:3000",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Headers": "Content-Type, X-Gate-Token",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Content-Type": "application/json",
  });
  res.end(JSON.stringify(body));
}

const server = http.createServer((req, res) => {
  if (req.method === "OPTIONS") return json(res, {});
  if (req.url === "/health") return json(res, { status: "ok" });
  if (req.url === "/auth/me") {
    return json(res, { id: "mock-user", email: "charlie@example.com", name: "Charlie", init: "C" });
  }
  if (req.url === `/tasks/${taskId}`) return json(res, task);
  if (req.url === `/tasks/${taskId}/events`) return json(res, { detail: "events unavailable" }, 404);
  if (req.url === `/tasks/${taskId}/generated-assets`) return json(res, { items: [] });
  return json(res, { detail: "Not found" }, 404);
});

server.listen(8000, "127.0.0.1", () => console.log("mock-api listening on 8000"));
