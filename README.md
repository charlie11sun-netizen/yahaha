# GameWeave — AI Native 互动游戏平台（MVP）

面向玩家与创作者的 AI Native 互动游戏平台：创作者用自然语言 + 多模态素材，经 Multi-Agent 流水线生成可发布、可游玩的互动游戏；玩家从首页发现并即点即玩。

> 📋 **交付必看 —— [完成度说明](docs/完成度说明.md)**：逐项说明「已完成 / Mock 或简化 / 未完成」，以及「再给 1 周」的迭代计划。

> 设计文档见 [`docs/`](docs/)：[技术选型](docs/技术选型.md) · [系统架构](docs/系统架构.md) · [数据模型与接口](docs/数据模型与接口.md) · [Multi-Agent 设计](docs/multi-agent_design.md) · [记忆系统设计](docs/memory_system_design.md) · [安全与可观测性](docs/安全与可观测性.md) · [完成度说明](docs/完成度说明.md) · [加固路线图](docs/加固路线图-2026-07.md) · [访问密码门禁](docs/访问密码门禁.md) · [AI 协作记录](docs/AI协作记录.md)
> 部署见 [部署指南](deploy/DEPLOY.md)（本地 docker compose / Zeabur 托管 + 跨机数据迁移）。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | Next.js 15 + React 19 + TypeScript · Tailwind v4 + shadcn/ui |
| 后端 | Python · FastAPI |
| 异步任务 | Celery + Redis |
| Agent | LangGraph 固定工作流 + OpenAI-compatible Model（默认模型由 `MODEL_NAME` 配置；mock/real 可切换） |
| 数据库 | PostgreSQL 16 + SQLAlchemy |
| 对象存储 | MinIO（S3 兼容，boto3） |
| 部署 | Docker Compose |

## 快速开始

前置：Docker + Docker Compose。

```bash
cp .env.example .env          # 默认值即可直接跑（mock 生成，无需模型 key）
docker compose up --build
```

启动后：

| 服务 | 地址 |
| --- | --- |
| 前端 Web | http://localhost:3000 |
| 后端 API（OpenAPI 文档） | http://localhost:8000/docs |
| MinIO 控制台 | http://localhost:9001 （账号见 `.env`） |

首次启动 `api` 会自动建表并写入 **3 个旗舰示例游戏**，bundle 上传 MinIO（3D 游戏的 `three.min.js` 随包同前缀上传）：

- 2D《Prism Break》（霓虹打砖块）、3D《Warp Spire》（自托管 Three.js 隧道飞行）—— 手工打造（`source=seed`）。
- 3D《火线突围》（霓虹街区枪战）—— **由真实 Create 流水线生成**，产物固化随 seed 发布并标 `source=create`，首页显示「✨ AI」角标、详情页显示生成 prompt。

因此**开箱即满足「≥3 个示例游戏、≥1 个来自 Create」的验收**，无需手动操作。此外，用户通过 Create 流程实时生成并发布的游戏（如《Neon Arena: Dronefall》）也会出现在首页。

> **整站访问密码（部署门禁）**：在 `.env` 设 `SITE_PASSWORD=你的密码` 后，打开网站需先在门禁页输入该密码才能进入；留空则不启用（本地开发默认开放）。密码仅服务端读取（Next middleware），cookie 存哈希令牌而非明文，与下文的用户注册/登录相互独立。

> **生产部署**：另有 `docker-compose.prod.yml` + `.env.prod.example`（强制站点密码、烧入公网地址、可跨机迁移 Create 生成的游戏数据），本地一条命令或 Zeabur 托管，详见 [部署指南](deploy/DEPLOY.md)。

## 核心链路（端到端）

```
注册/登录 → Create 输入创意 → LangGraph 节点流水线生成（实时 SSE 日志）
→ sandbox 构建/QA → 产物 bundle + manifest 上传私有 MinIO → 发布 → 首页可见
→ Play 从 API token 文件代理加载 bundle，在沙箱 iframe 中运行
```

### 可选的生成素材与 Phaser/Vite 构建

- `ASSET_GENERATION_ENABLED=true` 启用 `generate_game_assets`，图片、音频、视频按模态分别通过
  `ASSET_IMAGE_*` / `ASSET_AUDIO_*` / `ASSET_VIDEO_*` 路由供应商；默认 `local` 图片供应商生成离线占位 SVG，避免意外外部费用。
- `TILEMAP_GENERATION_ENABLED=true` 为适用的 2D archetype 生成确定性的 Tiled JSON + 同源 tileset。
- 所有新 2D 游戏强制生成模块化 Phaser 3.90 + TypeScript 源工程，由独立 sandbox 使用固定依赖完成
  `tsc --noEmit` 和 Vite 构建；只将静态 `dist` 写入公开游戏 manifest 和 MinIO。
- Vite 源工程保存到私有 `game-sources/{game}/{version}` 前缀，Revision 从源码继续修改，不编辑压缩后的产物。
- 新工程原生使用 TypeScript，并按 `src/scenes`、`src/entities`、`src/systems`、`src/ui`、`src/config`
  分层。开启 `CODE_AGENT_AUTHOR_ENABLED=true` 后，`GameCodeAgent` 内部运行有界团队：只读
  `DesignContractAgent` 冻结状态/事件/所有权契约；`RulesAndSimulationCoder`、`WorldAndContentCoder`、
  `PresentationAndInteractionCoder` 基于同一骨架快照在工具级目录白名单内产出隔离候选；唯一的
  `IntegrationAgent` 负责场景组合，并通过 `tsc --noEmit` 与隔离 Vite 构建后再进入外层验证。
- 内部团队不新增顶层 LangGraph 节点，不改变 checkpoint、任务恢复或日志表；外层
  `build_validation → gameplay_qa → repair/replan` 门禁保持不变。

### 可选的 GameCodeAgent 完整追踪

- `CODE_AGENT_DETAILED_LOGGING_ENABLED=false` 为默认值；关闭时不会写入任何完整追踪数据。
- 开启后，每轮模型输入/输出、完整 system/task prompt、工具参数与结果、最终会话历史、生成代码和异常堆栈
  会写入独立的 `agent_trace_events` 表。该表不进入普通任务详情或 SSE，避免拖慢 Create 页面。
- 这些数据包含用户内容和大量源代码，且增长很快，只应在受控调试环境短期开启。
- 按任务导出 JSONL：`docker compose exec api python -m app.tools.export_agent_traces <task-id>`；
  加 `--step-id` / `--run-id` 可缩小范围，`--pretty` 输出一个格式化 JSON 数组。

## 记忆系统（Memory）

GameWeave 已接入面向生成与修改流程的长期记忆系统：

- **原始证据层**：`memory_items` 保存用户原话、来源任务/游戏、版本和作用范围，作为可审计事实来源。
- **当前状态层**：`memory_profiles` 汇总当前生效偏好或约束，例如画风、难度、操作手感；只有 `active` Profile 会注入生成 Prompt。
- **历史层**：`memory_profile_versions` 记录创建、强化、自动晋升、取代、修正、删除和效用反馈。
- **检索策略**：生成前优先注入当前 game/task/user 的 active Profile，再用 BM25 + 向量混合检索和 RRF 从原始记忆中补充相关证据。
- **自动更新**：成功 preview / revision 后写入新证据；启用真实模型时 LLM 只建议 claim，程序仍验证 `evidence_span`、作用范围和状态机；LLM 可下调（不可虚高）置信度，拿不准的 claim 自动进入 candidate 轨道。
- **偏好聚合**：换一种说法的同一偏好会归并到同一 `profile_key`——LLM 模式下提取上下文携带 active + candidate key 并要求逐字复用；规则模式下用向量最近邻认领已有 key，向量不可用才回退哈希。
- **冲突处理**：明确新偏好可直接取代旧值；模糊反馈进入后台 `candidate`，不会进入 Prompt，也不显示 Accept/Reject；game 级 candidate 按重复独立证据晋升，user 级（跨游戏偏好）必须在 ≥2 个不同游戏中出现一致证据才晋升，同一游戏内重复不计。
- **用户控制**：Studio Memory 页展示 active Profile 和原始记忆，用户可手动新增、删除原始记忆，或 Correct 当前 Profile。

完整规则见 [记忆系统设计](docs/memory_system_design.md)。

## 目录结构

```
.
├── docs/                    # 系统设计文档
├── backend/                 # FastAPI + Celery + LangGraph
│   ├── app/
│   │   ├── api/             # 路由：auth / games / tasks / uploads
│   │   ├── agents/          # LangGraph 生成流水线（mock + 真实可切换）
│   │   ├── services/        # 业务编排（生成、发布、计数…）
│   │   ├── tasks/           # Celery app + 生成任务
│   │   ├── storage/         # boto3 / S3 封装
│   │   ├── models/ · schemas.py     # SQLAlchemy 模型 / Pydantic DTO
│   │   └── seed.py          # 旗舰示例游戏
│   ├── migrations/          # Alembic 迁移
│   └── tests/               # pytest 套件
├── frontend/                # Next.js（Home / Detail / Auth / Create / Play）
│   └── app · components/ui（shadcn） · lib
├── deploy/                  # 部署指南 + 跨机数据迁移脚本
├── docker-compose.yml       # 本地：web / api / worker / outbox-worker / beat / postgres / redis / minio
├── docker-compose.prod.yml  # 生产：站点密码门禁 + 公网地址
└── .env.example · .env.prod.example
```

## 与设计文档的已知差异（MVP 取舍）

- **鉴权**：邮箱登录与 OAuth 统一签发 HttpOnly/SameSite JWT Cookie（不向 JS 暴露 token），受保护写请求校验 `Origin` 防 CSRF；注册/登录/me/改密码/改资料/删号均校验 `is_active`。**真实 Google/GitHub OAuth 授权码流程**配好 client id/secret 即启用；demo 仅本地显式开启。
- **迁移**：已接入 **Alembic**（`backend/migrations`，单一固化基线 `0001_baseline`，空库可直接 `alembic upgrade head`，测试守护迁移 schema ≡ ORM schema）；开发以 `create_all` 兜底（`AUTO_CREATE_ALL`），生产 compose 关闭兜底、只走迁移。squash 之前建的库先执行 `alembic stamp 0001_baseline --purge`，再执行 `alembic upgrade head`。
- **测试 / CI**：`backend/tests` pytest 套件（SQLite 内存库，覆盖 auth / games / tasks / uploads / 限流）+ GitHub Actions（`.github/workflows/ci.yml`：后端 pytest；前端依赖审计、OpenAPI 生成物漂移检查、ESLint、TypeScript 和 `next build`）。前端请求通过 `openapi-fetch` 消费生成的 `paths`，后端契约变化需执行 `cd frontend && npm run openapi:generate` 并提交 `lib/api-types.ts`。
- **加固**：Redis IP 限流、安全响应头、上传 MIME 嗅探/图片重编码/EXIF 清理/ZIP 约束、播放计数防刷、发布时向 bundle 注入 CSP（`connect-src 'self'`，浏览器层强制同前缀资源）、API token 文件代理、未发布游戏的评论/排行/manifest 与详情页同一可见性规则、`/health/ready` 就绪检查（DB/Redis/S3）。
- **生成**：默认 `USE_REAL_MODEL=false` 走离线启发式流水线；置 `true` 走 **LangGraph 真实链路**（含 Memory、规划、素材、Phaser/Vite 构建、sandbox QA、repair/replan、revision/remix），模型由 `MODEL_NAME` 配置。`CODE_AGENT_ENABLED` / `CODE_AGENT_AUTHOR_ENABLED` 可分别启用 Repair Agent 和 2D 有界 Author Team。
- **记忆**：已实现原始证据、Profile 汇总、版本历史、混合检索和自动冲突处理；candidate 记忆后台积累并自动晋升（game 级按重复证据、user 级按跨游戏证据），不要求用户确认；自然表达的全局偏好通过「影子 candidate + 跨游戏晋升」通道自动形成，无需特定措辞。
- **沙箱**：Compose 默认使用独立 Playwright/Chromium `sandbox` 服务；生产可选 `SANDBOX_RUNTIME=runsc` 启用 gVisor，裸 pytest 才允许 V8 mock 降级。
- **前端样式**：已迁移到 **Tailwind v4 + shadcn/ui**（设计令牌按品牌调色，组件在 `frontend/components/ui`），核心页优先；早期从设计稿移植的 `pf-*` 内联/CSS 仍共存，逐页替换中。

完整的「已完成 / Mock / 未完成 + 再给 1 周怎么迭代」清单见 **[完成度说明](docs/完成度说明.md)**；安全相关已知问题另见 `docs/安全与可观测性.md`。
