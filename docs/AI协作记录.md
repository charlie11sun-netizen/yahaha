# AI 协作记录

> 本文记录开发过程中**人类提出的需求/问题**与 **AI 做出的对应改动**，同时作为测试可选交付项「AI 协作记录」。

## 概述

- **AI 工具**：Claude Code（Claude Opus 4.x）。
- **协作模式**：对话式迭代。人类负责提需求、真机测试、贴日志/截图、纠偏与提供设计文档；AI 负责写后端/前端代码、设计文档、调试与提交。
- **AI 贡献比例**：代码与文档约 **95%+ 由 AI 生成**；人类主要贡献为需求与设计输入（`docs/multi-agent_design.md`、`docs/create-page-design.md`、PlayForge 设计稿）、真机验证与问题反馈。
- **Review / 测试方法**：
  - 真机 `docker compose up` 跑全栈，人工点测各页面，出问题贴 `docker compose logs` / 截图。
  - AI 侧用 `python -m compileall` 做语法自检 + `configure_mappers` 接线自检；并直接 `curl` 后端、查 MinIO/DB 定位问题。
  - 局限：AI 本地无法联网装 `langgraph`/`npm` 全量依赖，**前端与真实模型链路主要靠真机验证**（AI 已在每次坦白说明）。

## 时间线（我提的问题 → AI 改动 → 提交）

### 阶段一 · 设计与选型（纯文档，不动代码）
| 我提的 | AI 改动 | 提交 |
|---|---|---|
| 先确定技术选型，不要改代码 | 通读需求，给出全栈选型建议 | — |
| ts 是什么 | 解释 TypeScript 及为何前端用它 | — |
| 我更熟 Python，用 Python agent | 选型定为 **Python 后端**（FastAPI+LangGraph+Celery）+ Next.js 前端 | — |
| 把选型写入文档 + 提交 | `docs/技术选型.md` | `f450a12` |
| 继续：架构图 / 目录 / 依赖 | `docs/系统架构.md`（Mermaid 架构图+时序图+目录+依赖）并渲染架构图 | `aa7a180` |
| 补设计文档：数据模型 + 核心接口 | `docs/数据模型与接口.md`；需求文档移入 `docs/` | `9603035` `bad062b` |
| 补：安全 / 失败恢复 / 可观测 / 已知问题 | `docs/安全与可观测性.md` | `2d82307` |
| handoff 文件夹加进 gitignore | `.gitignore` | `2533b69` |

### 阶段二 · 脚手架（参考 PlayForge 设计稿）
| 我提的 | AI 改动 | 提交 |
|---|---|---|
| 进脚手架，页面参考 handoff | 基础设施：docker-compose / .env.example / Dockerfile / README | `3e1d253` |
| 〃 | 后端：FastAPI + 数据模型 + REST + Celery + **mock 生成流水线** + seed 3 个示例游戏 | `598f8dc` |
| 〃 | 前端：Next.js 五页面（Home / Detail / Auth / Create / Play，沙箱 iframe 远端加载） | `9aaecc4` |

### 阶段三 · 跑起来 + 联调修复
| 我提的 | AI 改动 | 提交 |
|---|---|---|
| 安装命令 / 在哪设 api / could not start generation | 诊断并修：**bcrypt 与 passlib 不兼容**致 seed 崩溃→改用 bcrypt；Dockerfile 加国内 pip/npm 镜像；layout `suppressHydrationWarning`；提示 schema 变更需 `down -v` | `d06da41` |
| Play 游戏显示不完整 | iframe 用确定高度 `min(72vh,640px)`，画布填满 | `af59cbc` |
| demo 可玩性差、太快、方块无解 | 动作游戏加 **60fps 限帧** + 降速 + **障碍最小间距保证可解** | `1974c29` |

### 阶段四 · 真实 Create 链路 + 多 Agent 重构
| 我提的 | AI 改动 | 提交 |
|---|---|---|
| 搭建真实 create 链路 | LangGraph + GPT-5.5（planner→designer→coder→QA，QA 不过重试） | `c94f38a` |
| 这是 multiagent 吗 | 诚实评估：当时偏"提示词链"，给出强化方案 | — |
| 按 `multi-agent_design.md` 完成 multiagent | 重构为 **9 节点固定 LangGraph 工作流**（safety→intent→asset→design→code→validate→repair≤2→replan≤1→publish），Jinja2 模板渲染多文件产物 + manifest v1 | `4677315` |
| USE_REAL_MODEL=true 却走 mock | 诊断：`OPENAI_BASE_URL` 仍指向 openai.com → **401**，应填 Yahaha 端点 | — |
| preview 还是 mock？ | 诊断：`code_generation` 写整 game.js **超时回退模板**；real 模式改为**模型直接写 game.js** | `b4cbdc2` |
| 超时再调大、去掉紧凑限制 | 模型超时 120→300→**600s** | `21fa4a7` `d85ddcc` |

### 阶段五 · 生成可视化与体验
| 我提的 | AI 改动 | 提交 |
|---|---|---|
| 任务可视化差、不动态、太丑 | 后端 `tracing` 每节点**先 running 再 done** 实时落库；前端重设计成暖色时间线 + 运行步 spinner | `c15defe` |
| 动态显示 token | header token **平滑递增动画** | `158c825` |
| 结合图片+文档重设计 Create 页 | 重做为**生成控制台**：7 阶段时间线 / 当前阶段卡 / 游戏设计草案 / 素材卡 / Agent 摘要 / 日志抽屉 / 操作区；后端 `task_out` 扩展 step_summaries/design/assets/耗时/产物 URL | `f7f3878` |

### 阶段六 · 个人页与社交
| 我提的 | AI 改动 | 提交 |
|---|---|---|
| 还缺一个个人页面 | `/me` 主页（我的作品 + 收藏 + 统计）；GameCard 加草稿/预览角标；导航头像可进入 | `8792bf4` |
| 〃（让收藏可用） | 详情页 **♥点赞 / ★收藏** 按钮，后端返回 liked/favorited | `65793ae` |
| 用 skill 了吗 / web-artifacts-builder | 说明：全程未用 skill，均手写；该 skill 当时不在可用列表 | — |
| 记录我们的对话 | 本文件 `docs/AI协作记录.md` | （本次） |

## 人工 Review / 测试发现、AI 修复的典型问题

1. **bcrypt × passlib 不兼容** —— seed 启动崩溃、API 起不来；改用 `bcrypt` 直连。
2. **schema 改动忘了 `down -v`** —— 新增列未进旧表，建任务 500；明确"改 schema 必须重建卷"。
3. **国内网络** —— Docker Hub / PyPI / npm 拉取超时；配镜像源 + Dockerfile 国内镜像。
4. **真实模型链路** —— `OPENAI_BASE_URL` 配错导致 401 静默回退；`code_generation` 超时回退模板 → 调超时 + 模型直写 game.js。
5. **游戏体验** —— 高刷显示器 2 倍速、障碍无解、iframe 高度致画面残缺；限帧 + 可解性 + 确定高度修复。

> 复现核心链路与启动方式见 `README.md`；各设计决策见 `docs/` 其余文档。
