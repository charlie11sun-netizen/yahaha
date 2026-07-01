# GameWeave 部署指南

> 两种部署方式:**A. 本地一条命令(docker compose)** · **B. Zeabur 托管(多服务)**。
> 文中所有密码、密钥、令牌、域名一律用 `<占位符>` 表示,部署时替换成你自己的值。

---

## 一、架构与游戏数据

GameWeave 由 6 个服务组成:

| 服务 | 作用 |
|---|---|
| `web` | Next.js 前端 |
| `api` | FastAPI 后端(REST + 站点密码门 + 启动时 `seed` 灌入旗舰游戏) |
| `worker` | Celery 后台进程,跑游戏生成管线(现场生成用) |
| `postgres` | 游戏 / 用户 / 任务等元数据 |
| `redis` | Celery 的消息队列 |
| `minio` | S3 兼容对象存储,存放可玩的游戏 bundle |

**游戏存在哪:**

- **元数据**(标题/封面/版本…)在 Postgres;**可玩的 bundle**(index.html/game.js/three.min.js)在对象存储。
- **curated 旗舰游戏**(Prism Break / Warp Spire / 火线突围)是仓库源码,`api` 启动时 `seed` 自动建进 DB + 上传到对象存储 → 换任何环境都会自动出现。
- **通过 Create 现场生成的游戏**只存在于当时那套 DB + 存储里,**不随仓库走**(换环境需迁移,见第六节)。

**站点密码门:** 设了 `SITE_PASSWORD` 即整站需先输密码(前端 middleware 拦页面、后端校验 `X-Gate-Token`)。

---

## 二、方式 A — 本地:一条命令

前提:装好 Docker。

```sh
git clone <REPO_URL> && cd yahaha
cp .env.prod.example .env          # 编辑 .env,填好下面这些
docker compose -f docker-compose.prod.yml up -d --build
```

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
```

打开 `PUBLIC_WEB_URL` → 输密码 → 看到 3 个旗舰、可玩;Create 可现场生成(worker 随 compose 已起好)。

> 能一条命令搞定,是因为 compose 在**一台机器**上把 6 个容器 + 私有网络 + 持久卷一次拉起,服务间用服务名互连。

---

## 三、方式 B — Zeabur(托管,多服务)

Zeabur 不吃 docker-compose,要在**一个项目里建 6 个独立服务**并手动连线。

### 0. 先把代码合并到 `main`
Zeabur 默认部署默认分支。确保要部署的代码在 `main`(或在服务设置里手动选对分支)。

### 1. 按顺序建 6 个服务(先依赖,后用依赖的)

| # | 服务 | 来源 | 根目录 | 启动命令 | 端口 | 公网域名 |
|---|---|---|---|---|---|---|
| 1 | postgres | 数据库 → PostgreSQL | — | — | — | ❌ 不暴露 |
| 2 | redis | 数据库 → Redis | — | — | — | ❌ 不暴露 |
| 3 | minio | Docker 镜像 `minio/minio` | — | `server /data --console-address ":9001"` | 9000(挂卷到 `/data`) | ✅ 绑 9000 |
| 4 | api | Git 仓库 | `backend` | `sh -c "python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"` | 8000 | ✅ 绑 8000 |
| 5 | worker | Git 仓库(同上) | `backend` | `celery -A app.tasks.celery_app.celery worker --loglevel=info` | — | ❌ 不绑(后台进程) |
| 6 | web | Git 仓库 | `frontend` | 默认 Dockerfile(dev 即可跑;生产用 `Dockerfile.prod`) | 3000 | ✅ 绑 3000 |

### 2. MinIO 额外两步(compose 里自动,Zeabur 要手动)
绑好 9000 公网域名后,在 **MinIO 容器终端**里建桶 + 放开匿名只读:

```sh
mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb --ignore-existing local/gameweave
mc anonymous set download local/gameweave
```

### 3. 各服务环境变量(粘进「编辑原始环境变量」)

**api 与 worker(基本相同):**

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
OPENAI_TIMEOUT=600
SITE_PASSWORD=<访问密码>
CORS_ORIGINS=https://<WEB_DOMAIN>     # 仅 api 需要;等 web 有域名后回填
```

> worker 不需要 `CORS_ORIGINS` / `SITE_PASSWORD`,带着也无害。

**web:**

```
NEXT_PUBLIC_API_BASE_URL=https://<API_DOMAIN>
SITE_PASSWORD=<访问密码,与 api 完全相同>
```

### 4. 连线心法(内网 vs 公网)
- **服务之间**走内网:`postgresql.zeabur.internal` / `redis.zeabur.internal` / `minio.zeabur.internal`。
- **浏览器要直连的**(api、minio 加载游戏)走**公网域名**。
- **交叉引用**:`web` 里放 `api` 的域名(`NEXT_PUBLIC_API_BASE_URL`);`api` 里放 `web` 的域名(`CORS_ORIGINS`)。

---

## 四、验收

```sh
# api 健康(白名单,不需密码)
curl https://<API_DOMAIN>/health      # → {"status":"ok"}
# api 受密码门保护(预期被挡)
curl https://<API_DOMAIN>/games       # → 401 {"detail":"Site locked..."}
```

- 浏览器打开 `https://<WEB_DOMAIN>` → 跳转输密码 → 进首页看到 **3 个旗舰(含火线突围)**,点进去能玩。
- 现场生成:Create 填创意 → 生成 → 「My Tasks」看进度 → worker 日志实时打印每一步;卡住先看 worker 日志。

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
