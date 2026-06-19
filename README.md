# PlayForge — AI Native 互动游戏平台（MVP）

面向玩家与创作者的 AI Native 互动游戏平台：创作者用自然语言 + 多模态素材，经 Multi-Agent 流水线生成可发布、可游玩的互动游戏；玩家从首页发现并即点即玩。

> 完整设计文档见 [`docs/`](docs/)：[技术选型](docs/技术选型.md) · [系统架构](docs/系统架构.md) · [数据模型与接口](docs/数据模型与接口.md) · [安全与可观测性](docs/安全与可观测性.md)

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | Next.js 15 + React 19 + TypeScript（内联样式移植自设计稿） |
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

首次启动 `api` 会自动建表并写入 **3 个示例游戏**（其中 1 个标记为 Create 流程产出），并把它们的 bundle 上传到 MinIO。

## 核心链路（端到端）

```
注册/登录 → Create 输入创意 → 5-Agent 流水线生成（实时日志）
→ 产物 bundle + manifest 上传 MinIO → 发布 → 首页可见
→ Play 从 MinIO 远端加载 bundle，在沙箱 iframe 中运行
```

## 目录结构

```
.
├── docs/                 # 系统设计文档
├── backend/              # FastAPI + Celery + LangGraph
│   └── app/
│       ├── api/          # 路由：auth / games / tasks / uploads
│       ├── models/       # SQLAlchemy 模型
│       ├── schemas/      # Pydantic DTO
│       ├── agents/       # LangGraph 生成流水线（mock + 真实可切换）
│       ├── tasks/        # Celery app + 生成任务
│       ├── storage/      # boto3 / S3 封装
│       └── seed.py       # 示例数据
├── frontend/             # Next.js（Home / Detail / Auth / Create / Play）
├── docker-compose.yml    # web / api / worker / postgres / redis / minio
└── .env.example
```

## 与设计文档的已知差异（MVP 取舍）

- **鉴权**：邮箱 JWT（注册/登录/me/改密码/改资料/删号，登录校验 `is_active`）+ **真实 Google/GitHub OAuth 授权码流程**（`/auth/oauth/{provider}/start`+`/callback`，填好 client id/secret 即启用，留空前端回退 demo）。
- **迁移**：已接入 **Alembic**（`backend/migrations`，`alembic upgrade head`）；开箱即跑仍以 `create_all` 兜底，生产走迁移。
- **测试 / CI**：`backend/tests` pytest 套件（SQLite 内存库，覆盖 auth / games / tasks / uploads / 限流）+ GitHub Actions（`.github/workflows/ci.yml`：后端 pytest + 前端 tsc）。
- **加固**：Redis IP 限流、安全响应头、上传大小/类型校验、播放计数防刷、`/health/ready` 就绪检查（DB/Redis/S3）。
- **生成**：默认 `USE_REAL_MODEL=false` 走 mock 流水线（保留 5-Agent 步骤与日志，从模板产出真实可玩 bundle 并上传 OSS）；置 `true` 走 **LangGraph 真实链路**（planner→designer→coder→sandbox QA，QA 不过自动回 coder 重试），调用 GPT-5.5 生成全新游戏代码、校验后上传 OSS。两条路径共用同一套步骤/日志流式展示。
- **沙箱**：Sandbox QA 的 gVisor 执行在 MVP 为 mock（返回冒烟结果），接口边界已预留。
- **前端样式**：为保真，直接移植设计稿的内联样式，未引入 Tailwind；后续可抽象为 Tailwind / CSS Modules。

完成度详见各阶段提交与 `docs/安全与可观测性.md` 的「已知问题」。
