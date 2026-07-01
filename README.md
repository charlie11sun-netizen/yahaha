# GameWeave — AI Native 互动游戏平台（MVP）

面向玩家与创作者的 AI Native 互动游戏平台：创作者用自然语言 + 多模态素材，经 Multi-Agent 流水线生成可发布、可游玩的互动游戏；玩家从首页发现并即点即玩。

> 📋 **交付必看 —— [完成度说明](docs/完成度说明.md)**：逐项说明「已完成 / Mock 或简化 / 未完成」，以及「再给 1 周」的迭代计划。

> 设计文档见 [`docs/`](docs/)：[技术选型](docs/技术选型.md) · [系统架构](docs/系统架构.md) · [数据模型与接口](docs/数据模型与接口.md) · [Multi-Agent 设计](docs/multi-agent_design.md) · [记忆系统设计](docs/memory_system_design.md) · [安全与可观测性](docs/安全与可观测性.md) · [完成度说明](docs/完成度说明.md) · [访问密码门禁](docs/访问密码门禁.md) · [AI 协作记录](docs/AI协作记录.md)
> 部署见 [部署指南](deploy/DEPLOY.md)（本地 docker compose / Zeabur 托管 + 跨机数据迁移）。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | Next.js 15 + React 19 + TypeScript · Tailwind v4 + shadcn/ui |
| 后端 | Python · FastAPI |
| 异步任务 | Celery + Redis |
| Agent | LangGraph（`USE_REAL_MODEL=true` 时接 GPT-5.5；默认 mock 流水线离线可跑） |
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
- 3D《火线突围》（霓虹街区枪战）—— **由真实 Create 流水线（GPT-5.5）生成**，产物固化随 seed 发布并标 `source=create`，首页显示「✨ AI」角标、详情页显示生成 prompt。

因此**开箱即满足「≥3 个示例游戏、≥1 个来自 Create」的验收**，无需手动操作。此外，用户通过 Create 流程实时生成并发布的游戏（如《Neon Arena: Dronefall》）也会出现在首页。

> **整站访问密码（部署门禁）**：在 `.env` 设 `SITE_PASSWORD=你的密码` 后，打开网站需先在门禁页输入该密码才能进入；留空则不启用（本地开发默认开放）。密码仅服务端读取（Next middleware），cookie 存哈希令牌而非明文，与下文的用户注册/登录相互独立。

> **生产部署**：另有 `docker-compose.prod.yml` + `.env.prod.example`（强制站点密码、烧入公网地址、可跨机迁移 Create 生成的游戏数据），本地一条命令或 Zeabur 托管，详见 [部署指南](deploy/DEPLOY.md)。

## 核心链路（端到端）

```
注册/登录 → Create 输入创意 → 5-Agent 流水线生成（实时日志）
→ 产物 bundle + manifest 上传 MinIO → 发布 → 首页可见
→ Play 从 MinIO 远端加载 bundle，在沙箱 iframe 中运行
```

## 记忆系统（Memory）

GameWeave 已接入面向生成与修改流程的长期记忆系统：

- **原始证据层**：`memory_items` 保存用户原话、来源任务/游戏、版本和作用范围，作为可审计事实来源。
- **当前状态层**：`memory_profiles` 汇总当前生效偏好或约束，例如画风、难度、操作手感；只有 `active` Profile 会注入生成 Prompt。
- **历史层**：`memory_profile_versions` 记录创建、强化、自动晋升、取代、修正、删除和效用反馈。
- **检索策略**：生成前优先注入当前 game/task/user 的 active Profile，再用 BM25 + 向量混合检索和 RRF 从原始记忆中补充相关证据。
- **自动更新**：成功 preview / revision 后写入新证据；启用真实模型时 LLM 只建议 claim，程序仍验证 `evidence_span`、作用范围和状态机。
- **冲突处理**：明确新偏好可直接取代旧值；模糊反馈进入后台 `candidate`，不会进入 Prompt，也不显示 Accept/Reject；candidate 只有在重复独立证据支持后才自动晋升为 active。
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
├── docker-compose.yml       # 本地：web / api / worker / postgres / redis / minio
├── docker-compose.prod.yml  # 生产：站点密码门禁 + 公网地址
└── .env.example · .env.prod.example
```

## 与设计文档的已知差异（MVP 取舍）

- **鉴权**：邮箱 JWT（注册/登录/me/改密码/改资料/删号，登录校验 `is_active`）+ **真实 Google/GitHub OAuth 授权码流程**（`/auth/oauth/{provider}/start`+`/callback`，填好 client id/secret 即启用，留空前端回退 demo）。
- **迁移**：已接入 **Alembic**（`backend/migrations`，`alembic upgrade head`）；开箱即跑仍以 `create_all` 兜底，生产走迁移。
- **测试 / CI**：`backend/tests` pytest 套件（SQLite 内存库，覆盖 auth / games / tasks / uploads / 限流）+ GitHub Actions（`.github/workflows/ci.yml`：后端 pytest + 前端 tsc）。
- **加固**：Redis IP 限流、安全响应头、上传大小/类型校验、播放计数防刷、`/health/ready` 就绪检查（DB/Redis/S3）。
- **生成**：默认 `USE_REAL_MODEL=false` 走 mock 流水线（保留 5-Agent 步骤与日志，从模板产出真实可玩 bundle 并上传 OSS）；置 `true` 走 **LangGraph 真实链路**（planner→designer→coder→sandbox QA，QA 不过自动回 coder 重试），调用 GPT-5.5 生成全新游戏代码、校验后上传 OSS。两条路径共用同一套步骤/日志流式展示。
- **记忆**：已实现原始证据、Profile 汇总、版本历史、混合检索和自动冲突处理；candidate 记忆后台积累并按重复证据自动晋升，不要求用户确认。
- **沙箱**：Sandbox QA 的 gVisor 执行在 MVP 为 mock（返回冒烟结果），接口边界已预留。
- **前端样式**：已迁移到 **Tailwind v4 + shadcn/ui**（设计令牌按品牌调色，组件在 `frontend/components/ui`），核心页优先；早期从设计稿移植的 `pf-*` 内联/CSS 仍共存，逐页替换中。

完整的「已完成 / Mock / 未完成 + 再给 1 周怎么迭代」清单见 **[完成度说明](docs/完成度说明.md)**；安全相关已知问题另见 `docs/安全与可观测性.md`。
