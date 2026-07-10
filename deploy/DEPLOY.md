# GameWeave 部署指南

> 两种部署方式:**A. 本地一条命令(docker compose)** · **B. Zeabur 托管(多服务)**。
> 文中所有密码、密钥、令牌、域名一律用 `<占位符>` 表示,部署时替换成你自己的值。

---

## 一、架构与游戏数据

GameWeave 由 9 个长期运行的核心服务组成:

| 服务 | 作用 |
|---|---|
| `web` | Next.js 前端 |
| `api` | FastAPI 后端(REST + 站点密码门 + 启动时 `seed` 灌入旗舰游戏) |
| `worker` | Celery 后台进程,跑游戏生成管线(现场生成用) |
| `outbox-worker` | Celery 可靠投递补偿进程,独立于长耗时生成队列 |
| `beat` | 定时触发未投递/超时生成任务的补偿扫描 |
| `sandbox` | Playwright/Chromium 隔离运行生成 bundle；生产 worker 强制依赖 |
| `postgres` | 游戏 / 用户 / 任务等元数据 |
| `redis` | Celery 的消息队列 |
| `minio` | S3 兼容对象存储,存放可玩的游戏 bundle |

**游戏存在哪:**

- **元数据**(标题/封面/版本…)在 Postgres;**可玩的 bundle**(index.html/game.js/three.min.js)在对象存储。
- **curated 旗舰游戏**(Prism Break / Warp Spire / 火线突围)是仓库源码,`api` 启动时 `seed` 自动建进 DB + 上传到对象存储 → 换任何环境都会自动出现。
- **通过 Create 现场生成的游戏**只存在于当时那套 DB + 存储里,**不随仓库走**(换环境需迁移,见第五节)。

**站点密码门:** 设了 `SITE_PASSWORD` 即整站需先输密码(前端 middleware 拦页面、后端校验 `X-Gate-Token`)。
Demo 可设置 `GATE_PUBLIC_BROWSE=true`：首页、Explore、Game 详情、作者页和 Play 对匿名访客开放；Create、Studio、登录/注册入口仍在密码门后。

---

## 二、方式 A — 本地:一条命令

前提:装好 Docker。

```sh
git clone <REPO_URL> && cd yahaha
cp .env.prod.example .env          # 编辑 .env,填好下面这些
docker compose -f docker-compose.prod.yml up -d --build
```

生产 Compose 会为 Redis 启用 AOF 持久化并挂载 `redisdata`，避免 Broker 重启丢失已确认的生成消息。它还会启动独立 `sandbox`，并给 worker 固定设置 `SANDBOX_REQUIRED=true`；sandbox 不健康时 worker 不启动，运行时不可达则生成任务失败而不是跳过浏览器 QA。

`.env` 必填:

```
SITE_PASSWORD=<访问密码>
PUBLIC_WEB_URL=http://<本机IP>:3000
PUBLIC_API_URL=http://<本机IP>:8000
PUBLIC_S3_URL=http://<本机IP>:9000
POSTGRES_PASSWORD=<强密码>
MINIO_ROOT_PASSWORD=<强密码>
S3_SECRET_KEY=<与 MINIO_ROOT_PASSWORD 相同>
JWT_SECRET=<长随机串>
OPENAI_API_KEY=<模型 key>
OPENAI_BASE_URL=<模型地址>
MODEL_NAME=<模型名>
USE_REAL_MODEL=true
GATE_PUBLIC_BROWSE=false
```

打开 `PUBLIC_WEB_URL` → 输密码 → 看到 3 个旗舰、可玩;Create 可现场生成(worker 随 compose 已起好)。

公开 Demo 建议组合：

```
GATE_PUBLIC_BROWSE=true
MAX_ACTIVE_TASKS_PER_USER=1
TASK_TOKEN_BUDGET=300000
USE_REAL_MODEL=false   # 只展示/试玩时最省预算；需要现场生成再改 true
```

如使用单域名 TLS 反代，可启用可选 edge profile：

```sh
PUBLIC_HOST=<your-domain>
PUBLIC_WEB_URL=https://<your-domain>
PUBLIC_API_URL=https://<your-domain>/api
PUBLIC_S3_URL=https://<your-domain>/s3
docker compose -f docker-compose.prod.yml --profile edge up -d --build
```

Caddy 会自动申请证书，并把 `/api/*` 转发到后端、`/s3/*` 转发到 MinIO，其余请求转发到 web。`/s3/*` 只承载短期签名对象 URL；桶本身保持私有，未签名请求应返回 AccessDenied。

> 能一条命令搞定,是因为 compose 在**一台机器**上把核心容器 + 私有网络 + 持久卷一次拉起,服务间用服务名互连。

> **迁移基线已 squash(一次性)**:迁移链已压缩为单一固化基线 `0001_baseline`(全新库直接 `alembic upgrade head` 即可)。
> 如果你的 Postgres 卷是在 squash **之前**建的(alembic_version 还停在旧的 `0011_memory_pgvector`),升级代码后在 api 容器里执行一次:
> `alembic stamp 0001_baseline --purge && alembic upgrade head` —— 先对齐到固化基线，再顺序应用后续增量迁移。

> **首次升级到 `0008_generation_dispatch_outbox`** 时，先停止旧版 `api / worker / beat`，再执行迁移并启动新栈；这样旧 worker 不会与 `generation-v2` worker 同时处理迁移回填的 pending 任务：
> `docker compose -f docker-compose.prod.yml stop api worker beat && docker compose -f docker-compose.prod.yml run --rm migrate && docker compose -f docker-compose.prod.yml up -d --build`

---

## 三、方式 B — Zeabur(托管,多服务)

Zeabur 不吃 docker-compose,要在**一个项目里建 9 个长期运行服务**并手动连线。Compose 中的 `migrate` 在这里并入 api 启动命令，`createbuckets` 改为一次性手动初始化；可选的 `clamav` / `edge` 不计入这 9 个服务。

### 0. 先把代码合并到 `main`
Zeabur 默认部署默认分支。确保要部署的代码在 `main`(或在服务设置里手动选对分支)。

### 1. 按顺序建 9 个服务(先依赖,后用依赖的)

| # | 服务 | 来源 | 根目录 | 启动命令 | 端口 | 公网域名 |
|---|---|---|---|---|---|---|
| 1 | postgres | 数据库 → PostgreSQL | — | — | — | ❌ 不暴露 |
| 2 | redis | 数据库 → Redis | — | — | — | ❌ 不暴露 |
| 3 | minio | Docker 镜像 `minio/minio` | — | `server /data --console-address ":9001"` | 9000(挂卷到 `/data`) | ✅ 绑 9000 |
| 4 | sandbox | Git 仓库 | `sandbox` | 使用 Dockerfile 默认命令 | 8001 | ❌ 不绑(仅 worker 内网访问) |
| 5 | api | Git 仓库 | `backend` | `sh -c "alembic upgrade head && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"` | 8000 | ✅ 绑 8000 |
| 6 | worker | Git 仓库(同上) | `backend` | `celery -A app.tasks.celery_app.celery worker --loglevel=info --queues=celery,generation-v2 --concurrency=2 --max-tasks-per-child=20` | — | ❌ 不绑(后台进程) |
| 7 | outbox-worker | Git 仓库(同上) | `backend` | `celery -A app.tasks.celery_app.celery worker --loglevel=info --queues=generation-outbox --concurrency=1 --max-tasks-per-child=100` | — | ❌ 不绑(后台进程) |
| 8 | beat | Git 仓库(同上) | `backend` | `celery -A app.tasks.celery_app.celery beat --loglevel=info` | — | ❌ 不绑(后台进程) |
| 9 | web | Git 仓库 | `frontend` | 使用 `Dockerfile.prod` | 3000 | ✅ 绑 3000 |

> `sandbox` 至少预留约 1 vCPU / 768 MiB 内存，不绑定公网域名。Zeabur 通常不支持自定义 gVisor runtime，因此使用平台容器隔离；服务仍必须保持非 root、仅内网可达，并保留下面的文件大小和并发限制。

### 2. MinIO 额外两步(compose 里自动,Zeabur 要手动)
绑好 9000 公网域名后，在 **MinIO 容器终端**里建桶并关闭所有匿名访问。公网域名只用于短期签名 URL；`games/` 与 `uploads/` 都保持私有：

```sh
mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb --ignore-existing local/gameweave
mc anonymous set none local/gameweave
mc anonymous get local/gameweave   # 应显示 none
```

不要执行 `mc anonymous set download .../games`。公开试玩仍先经过 API 的游戏可见性检查，manifest 中的文件地址是带时效 token 的 `/games/{id}/files/...` API 路由；知道 MinIO 对象 key 也不能绕过 API 直接下载草稿或历史版本。

### 3. 各服务环境变量(粘进「编辑原始环境变量」)

**api、worker、outbox-worker 与 beat(基本相同):**

```
DATABASE_URL=postgresql+psycopg://<DB_USER>:<DB_PASSWORD>@postgresql.zeabur.internal:5432/<DB_NAME>
REDIS_URL=redis://default:<REDIS_PASSWORD>@redis.zeabur.internal:6379/0
S3_ENDPOINT=http://minio.zeabur.internal:9000
S3_PUBLIC_ENDPOINT=https://<MINIO_DOMAIN>
S3_ACCESS_KEY=<MINIO_USER>
S3_SECRET_KEY=<MINIO_PASSWORD>
S3_BUCKET=gameweave
JWT_SECRET=<长随机串>
OPENAI_API_KEY=<模型 key>
OPENAI_BASE_URL=<模型地址>
MODEL_NAME=<模型名>
USE_REAL_MODEL=true
ENABLE_OAUTH_DEMO=false
OPENAI_TIMEOUT=600
SITE_PASSWORD=<访问密码>
GATE_PUBLIC_BROWSE=false
CORS_ORIGINS=https://<WEB_DOMAIN>     # 仅 api 需要;等 web 有域名后回填
```

> 三个 Celery 后台服务不需要 `CORS_ORIGINS` / `SITE_PASSWORD`,带着也无害。

**worker 额外必填（不要加到 outbox-worker / beat）：**

```env
SANDBOX_URL=http://sandbox.zeabur.internal:8001
SANDBOX_REQUIRED=true
SANDBOX_TIMEOUT_MS=5000
SANDBOX_HTTP_TIMEOUT_OVERHEAD_MS=10000
```

`SANDBOX_REQUIRED=true` 是生产安全门禁：sandbox 未配置、超时或返回错误时，worker 必须让生成步骤失败，不能降级为“跳过 QA”。

**sandbox：**

```env
SANDBOX_RUNNER_CONCURRENCY=1
SANDBOX_RUNNER_CHROMIUM_NO_SANDBOX=true
SANDBOX_RUNNER_MAX_FILE_BYTES=2000000
SANDBOX_RUNNER_MAX_TOTAL_BYTES=5000000
```

这里的 `CHROMIUM_NO_SANDBOX=true` 只是托管容器内 Chromium 的兼容开关，不代表可以省略独立 sandbox 服务；外层容器、内网边界、非 root 用户和资源限制仍是安全边界。

**web:**

```
NEXT_PUBLIC_API_BASE_URL=https://<API_DOMAIN>
API_INTERNAL_BASE_URL=http://api.zeabur.internal:8000
SITE_PASSWORD=<访问密码,与 api 完全相同>
GATE_PUBLIC_BROWSE=false
```

### 4. 连线心法(内网 vs 公网)
- **服务之间**走内网:`postgresql.zeabur.internal` / `redis.zeabur.internal` / `minio.zeabur.internal` / `sandbox.zeabur.internal`；web 的 Server Components 通过 `API_INTERNAL_BASE_URL` 访问 api，worker 通过 `SANDBOX_URL` 访问 sandbox。
- **浏览器访问** web 与 api 公网域名；MinIO 公网域名只接受带签名的对象 URL。游戏 manifest 和 bundle 文件通过 API 的可见性检查与短期文件 token 加载，不配置匿名 bucket/prefix。
- **交叉引用**:`web` 里放 `api` 的域名(`NEXT_PUBLIC_API_BASE_URL`);`api` 里放 `web` 的域名(`CORS_ORIGINS`)。

---

## 四、验收

```sh
# api 健康(白名单,不需密码)
curl https://<API_DOMAIN>/health      # → {"status":"ok"}
# api 受密码门保护(预期被挡)
curl https://<API_DOMAIN>/games       # → 401 {"detail":"Site locked..."}

# 在 worker 容器终端验证 sandbox 内网健康；sandbox 不应有公网域名
curl http://sandbox.zeabur.internal:8001/health
```

- 浏览器打开 `https://<WEB_DOMAIN>` → 跳转输密码 → 进首页看到 **3 个旗舰(含火线突围)**,点进去能玩。
- 现场生成:Create 填创意 → 生成 → 「My Tasks」看进度 → worker 日志实时打印每一步;卡住先看 worker 日志。
- MinIO 未签名对象 URL应返回 AccessDenied；Play 仍能通过 API 返回的限时文件 URL 正常加载。
- worker 日志应出现真实 browser sandbox QA；如果 sandbox 不可达，任务应以 sandbox unavailable 失败，不能显示 QA skipped 后继续发布。

---

## 五、迁移已有的 Create 生成游戏(可选)

curated 旗舰随仓库自动重建;Create 现场生成的游戏只在原环境的 DB + 存储里。要带到新环境:

```sh
# 旧环境(stack 在跑)
sh deploy/migrate-export.sh           # 导出 DB + 存储桶 → ./pf-backup/
# 新环境:用 psql 还原 db.sql 到新 Postgres;用 mc mirror 把桶推到新 MinIO
```

详见 [`deploy/migrate-export.sh`](migrate-export.sh) / [`deploy/migrate-import.sh`](migrate-import.sh)。

---

## 附:占位符对照

| 占位符 | 含义 / 从哪拿 |
|---|---|
| `<DB_PASSWORD>` / `<REDIS_PASSWORD>` / `<MINIO_PASSWORD>` | 各服务密码(Zeabur 自动生成,从对应服务「环境变量 → PASSWORD」**复制**) |
| `<DB_USER>` / `<DB_NAME>` / `<MINIO_USER>` | 各服务的用户名 / 库名(同上,从服务环境变量看) |
| `<JWT_SECRET>` | 后端 JWT 签名密钥(长随机串,自定) |
| `<SITE_PASSWORD>` | 整站访问密码(**api 与 web 必须一致**) |
| `<OPENAI_API_KEY>` / `<OPENAI_BASE_URL>` / `<MODEL_NAME>` | 模型服务凭据与地址(需公网可达) |
| `<API_DOMAIN>` / `<WEB_DOMAIN>` / `<MINIO_DOMAIN>` | 三个对外服务各自的公网域名 |
| `<REPO_URL>` | 你的 Git 仓库地址 |
