# 部署 GameWeave（带访问密码，不公开）

整套是 **前端(Next) + 后端(FastAPI) + Celery worker + Postgres + Redis + MinIO**。
游戏分两类：

| 类型 | 存哪 | 迁移时 |
| --- | --- | --- |
| **curated 旗舰**（Prism Break / Warp Spire / 火线突围） | 仓库源码 → 后端启动时 `seed` 自动灌入 DB+存储 | 自动重建，无需迁移 |
| **Create 生成的游戏**（如 create 版 Neon Arena: Dronefall） | 只在 `pgdata` / `miniodata` 卷里 | **必须迁移**，否则丢 |

> 同一台机器上从 dev 切到 prod compose（`name` 都是 `gameweave`）会**复用同一批命名卷**，
> 数据本来就在，**不用迁移**。下面的迁移只在**换机器**时才需要。

---

## Part A — 迁移现有数据到新机器（保住 Create 游戏）

**1. 旧机器**（stack 正在运行的那台，仓库根目录执行）：
```sh
sh deploy/migrate-export.sh        # 生成 ./pf-backup/（db.sql + bucket/）
```
把 `pf-backup/` 整个拷到新机器的仓库根目录。

**2. 新机器**（先把仓库 clone 过去、配好 `.env` 见 Part B）：
```sh
docker compose -f docker-compose.prod.yml up -d postgres redis minio createbuckets
sh deploy/migrate-import.sh        # 还原 DB + 存储桶
```
> 顺序很重要：**先还原，再起 api**（api 启动会跑 seed，幂等、只刷新 3 个旗舰，不动你的 Create 游戏）。

---

## Part B — 带密码部署（不公开访问）

**1. 配置 `.env`**（仓库根目录）：
```sh
cp .env.prod.example .env
```
重点填这几项：
- `SITE_PASSWORD=<一段强口令>` —— **整站访问密码**。设了它，任何人打开网站都要先输密码，
  后端 API 也要求匹配令牌（直连后端被 401 挡掉）。留空 = 公开，prod compose 会直接报错拒启。
- `PUBLIC_WEB_URL` / `PUBLIC_API_URL` / `PUBLIC_S3_URL` —— 访客实际访问的公网地址
  （裸 VPS 填 `http://服务器IP:3000|8000|9000`；有域名+反代就填 https 域名）。
- `POSTGRES_PASSWORD` / `MINIO_ROOT_PASSWORD`（=`S3_SECRET_KEY`）/ `JWT_SECRET` —— 都换成强随机值。
- 想线上真生成游戏：`USE_REAL_MODEL=true` + 填好 `OPENAI_API_KEY` 等。

**2. 起服务：**
```sh
docker compose -f docker-compose.prod.yml up -d --build
```
首次会构建镜像、起库、`createbuckets` 建桶并放开 games 前缀只读、`api` 跑 `seed`。
打开 `PUBLIC_WEB_URL` → 会被弹到 `/gate` 输密码 → 进站。

只对外暴露 **web(3000) / api(8000) / minio S3(9000)**；Postgres、Redis、MinIO 控制台不对外。

---

## 注意事项

- **改了 `PUBLIC_API_URL` 要重新 build 前端**：它是 `NEXT_PUBLIC_*`，构建时就烧进客户端包了。
  `docker compose -f docker-compose.prod.yml up -d --build web`。
- **TLS / 域名**：生产建议在前面加个反代（Caddy/Nginx）做 HTTPS，把 web/api/s3 收到一个域名下，
  再把三个 `PUBLIC_*` 改成对应 https 地址。
- **密码门的边界（诚实说明）**：`SITE_PASSWORD` 保护的是**网站 + API**。游戏 bundle 是从对象存储
  (MinIO 9000) 以匿名只读供 `<iframe>` 加载的，**不在密码门后**——也就是说，知道某个游戏
  bundle 的确切 UUID 地址的人，能直接抓到那一个静态文件（但列表/站点/接口都进不去）。
  对私有 demo 通常够用。要彻底锁死，需要把 bundle 也走鉴权（签名 URL 或经网关代理），那是另一档工作量——需要的话告诉我。
- **改密码**：`SITE_PASSWORD` 是运行时变量，改完 `up -d` 重启 `api` + `web` 即可，无需重建前端。
