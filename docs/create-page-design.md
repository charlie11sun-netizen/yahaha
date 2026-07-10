# Create 页面设计文档

## 1. 页面目标

Create 页面用于让创作者通过自然语言创意和多模态素材生成一个可发布、可游玩的互动游戏。

页面需要覆盖两类目标：

1. **产品体验目标**
   - 用户能清楚知道当前正在做什么。
   - 用户不会只看到一个黑盒 loading。
   - 用户能在等待过程中看到游戏设计逐步成型。
   - 用户能在生成成功后快速预览和发布。
   - 用户在失败时能理解原因，并知道下一步怎么操作。

2. **工程验收目标**
   - 展示生成任务状态。
   - 展示当前关键步骤。
   - 展示 Agent 执行摘要或日志。
   - 展示产物地址，例如 `manifest_url`、`preview_url`。
   - 支持 Preview / Publish 闭环。
   - 能证明生成结果不是前端本地写死，而是来自后端任务和对象存储产物。

---

## 2. 页面范围

本文档只描述 Create 页面，包括：

```text
Create 输入页
Create 生成状态页
Create 生成成功页
Create 生成失败页
Agent 日志抽屉
预览与发布操作区
```

不包括：

```text
登录注册页
Home 游戏流
Play 游戏运行页
完整后端 Agent 实现
数据库详细建模
```

---

## 3. 页面信息架构

Create 页面可以分成两个阶段：

```text
阶段 1：用户输入创意和上传素材
阶段 2：系统生成游戏并展示进度
```

整体页面结构：

```text
CreatePage
├── PageHeader
├── PromptComposer
├── AssetUploader
├── ExamplePrompts
├── GenerateButton
└── GenerationStatusPanel, after task created
```

生成任务创建后，页面切换到生成状态视图：

```text
GenerationStatusPanel
├── GenerationHeader
├── ArtifactStatusStrip
├── GenerationTimeline
├── CurrentStepCard
├── GameDesignPreviewCard
├── AssetProcessingCard
├── AgentSummaryCard
├── AgentLogDrawer
└── ActionBar
```

---

## 4. 页面整体布局

推荐使用左右分栏布局。

```text
┌──────────────────────────────────────────────────────────────┐
│ Top Nav                                                      │
├──────────────────────────────────────────────────────────────┤
│ 页面标题 / 游戏名称 / Manifest URL / Preview URL              │
├───────────────────────┬──────────────────────────────────────┤
│ 左侧生成进度 Timeline  │ 右侧当前阶段详情                      │
│                       │  游戏设计草案                         │
│                       │  素材处理                             │
│                       │  Agent 执行摘要                        │
├───────────────────────┴──────────────────────────────────────┤
│ 底部操作区：查看日志 / 预览 / 发布 / 重新生成                  │
└──────────────────────────────────────────────────────────────┘
```

推荐布局参数：

```text
页面最大宽度：1280px - 1440px
左侧 Timeline 宽度：320px - 380px
右侧内容自适应
卡片圆角：16px - 24px
卡片间距：16px - 24px
主色：Blue / Indigo / Violet
成功色：Emerald
失败色：Red
等待色：Slate / Gray
```

---

## 5. Create 输入页设计

## 5.1 页面目标

输入页的目标是让用户快速表达创意，并上传至少一个素材。

页面核心操作：

```text
输入游戏创意
上传图片 / 文件 / 视频
点击生成游戏
```

---

## 5.2 输入区结构

```text
PromptComposer
├── 标题：描述你想生成的游戏
├── 多行文本框
├── 创意提示 chips
├── 上传素材区域
└── 生成按钮
```

---

## 5.3 Prompt 输入框

建议 placeholder：

```text
例如：做一个 2D 像素风塔防小游戏，玩家需要放置蘑菇塔，阻止史莱姆靠近生命水晶。成功防守 5 波怪物后胜利。
```

输入框下方提示：

```text
你可以描述玩法、角色、风格、胜负条件、操作方式和参考素材用途。
```

---

## 5.4 示例 Prompt

页面可以提供 3 个快捷示例：

```text
像素风太空躲避游戏
魔法森林塔防游戏
海底收集金币小游戏
```

点击示例后自动填入 Prompt 输入框。

---

## 5.5 素材上传区

上传区文案：

```text
上传素材
支持图片、视频或音频。MVP 阶段建议至少上传一张图片作为封面或游戏素材。
```

支持格式：

```text
png
jpg
jpeg
webp
gif
mp3
mp4
```

MVP 建议：

```text
优先支持图片上传
单文件大小限制：10MB
最多上传：5 个文件
```

上传后的展示：

```text
forest.png
已上传
1.2MB
可用于封面 / 背景 / 角色素材
```

---

## 5.6 生成按钮

默认状态：

```text
生成游戏
```

输入为空时禁用：

```text
请输入游戏创意后开始生成
```

上传中状态：

```text
素材上传中...
```

点击后状态：

```text
正在创建生成任务...
```

---

## 6. 生成状态页设计

## 6.1 页面目标

生成状态页不应该只是一个 spinner，而应该展示：

```text
用户可理解的创作进度
+ 可展开的 Agent 技术日志
+ 产物地址和预览发布操作
```

普通用户看到的是：

```text
检查创意
理解玩法
整理素材
设计规则
生成游戏
测试游戏
准备预览
```

评审或开发者可以展开看到：

```text
SafetyIntakeAgent
IntentSpecAgent
AssetAgent
GameDesignAgent
GameCodeAgent
BuildValidateAgent
RepairCodeNode
ReplanGameDesignNode
PublishArtifactAgent
```

---

## 6.2 页面 Header

Header 展示：

```text
正在生成你的游戏 ✦
我们会把你的创意转换成一个可在浏览器中运行的小游戏。
```

游戏标题区域：

```text
游戏图标 / 封面缩略图
魔法森林守卫战
编辑标题按钮
```

右上角产物状态：

```text
Manifest URL: 生成中...
Preview URL: 生成中...
```

生成成功后：

```text
Manifest URL: http://localhost:9000/...
Preview URL: /play/game_123?preview=1
```

---

## 6.3 左侧生成进度 Timeline

Timeline 固定展示 7 个主阶段：

```text
1. 检查创意和素材
2. 理解你的游戏创意
3. 整理素材
4. 设计玩法规则
5. 生成游戏代码
6. 测试游戏是否可运行
7. 准备预览版本
```

状态视觉：

| 状态 | 视觉 |
|---|---|
| completed | 绿色 check icon |
| running | 蓝色高亮圆点 + 当前行浅蓝背景 |
| pending | 灰色 clock / circle |
| failed | 红色 warning icon |
| repair | 橙色提示 |
| replan | 紫色提示 |

Timeline 顶部显示：

```text
生成进度
7 个阶段中的第 4 步
```

---

## 6.4 当前阶段卡片

当前阶段卡片用于告诉用户系统正在做什么。

结构：

```text
当前阶段
正在设计玩法规则
我们正在设计怪物、塔、防御范围、金币、波次和胜负条件。
[运行中]
```

状态 badge：

| 任务状态 | Badge |
|---|---|
| pending | 排队中 |
| running | 运行中 |
| succeeded | 已完成 |
| failed | 失败 |

---

## 6.5 游戏设计草案卡片

该卡片在 `game_design` 阶段后展示。

标题：

```text
游戏设计草案
```

内容示例：

```text
标题：魔法森林守卫战
类型：塔防
主题：魔法森林
初始金币：100
初始生命：10
防御塔价格：30
总波次：5
怪物：史莱姆
防御塔：蘑菇塔 / 水晶塔
```

右侧可以展示概念预览：

```text
2D Canvas 概念预览
森林地图
道路
史莱姆
防御塔
生命水晶
```

MVP 可以先用 CSS 占位图，不一定需要真实生成图片。

---

## 6.6 素材处理卡片

标题：

```text
素材处理
```

展示内容：

```text
forest.png   已上传
cover.png    已生成
slime.png    默认素材
tower.png    默认素材
```

每个素材卡片字段：

```text
文件名
缩略图
状态
来源类型
```

来源类型：

```text
uploaded
generated
default
```

---

## 6.7 Agent 执行摘要卡片

标题：

```text
Agent 执行摘要
```

展示简要日志：

```text
SafetyIntakeAgent    Prompt and assets passed safety check       0.8s   ✓
IntentSpecAgent      识别为魔法森林塔防游戏                       1.2s   ✓
AssetAgent           已处理 1 张上传图片，并补齐默认素材           2.3s   ✓
GameDesignAgent      正在生成波次、金币、生命值和防御塔规则        进行中
```

该区域默认展示摘要，不展示完整 JSON。

点击：

```text
查看 Agent 执行日志
```

后打开日志抽屉。

---

## 6.8 Agent 日志抽屉

抽屉内容：

```text
Agent 名称
执行步骤
日志级别
输入摘要
输出摘要
耗时
错误堆栈
token 统计，可选
```

示例：

```text
GameDesignAgent
Step: game_design
Level: info
Message: Created game design with entities: monster, tower, bullet, crystal
Cost: 2.8s
```

失败时展示：

```text
BuildValidateAgent
Step: build_validation
Level: warn
Message: Forbidden pattern found in game.js: fetch()
```

Repair 时展示：

```text
GameCodeAgentRepair
Step: repair_code
Message: Removed external API dependency and replaced meteor positions with local random generation.
```

Replan 时展示：

```text
GameDesignAgentReplan
Step: replan_game_design
Message: Replanned from 3D multiplayer tower defense to single-player 2D Canvas tower defense.
```

---

## 6.9 底部操作区

操作区根据状态变化。

| 状态 | 操作 |
|---|---|
| pending | 取消生成 |
| running | 查看日志 / 取消生成 |
| repair_code | 查看日志 / 继续等待 |
| replan_game_design | 查看调整说明 / 继续等待 |
| succeeded | 预览游戏 / 发布到首页 / 重新生成 |
| failed | 编辑创意 / 重新生成 / 查看日志 |

成功状态 CTA：

```text
预览游戏
发布到首页
重新生成
查看生成日志
```

失败状态 CTA：

```text
编辑创意
重新生成
查看技术日志
```

---

## 7. 生成状态文案设计

## 7.1 pending

```text
任务已创建
正在排队准备生成你的游戏...
```

按钮：

```text
取消生成
```

---

## 7.2 safety_intake

```text
正在检查创意和素材
我们会确认上传内容格式正确，并过滤不安全的生成请求。
```

高级日志：

```text
SafetyIntakeAgent started
Prompt accepted
1 image asset accepted
```

---

## 7.3 intent_spec

```text
正在理解你的游戏创意
我们正在提取游戏类型、核心玩法、胜负条件和操作方式。
```

动态摘要：

```text
已识别：
- 游戏类型：塔防
- 主题：魔法森林
- 核心目标：保护生命水晶
```

---

## 7.4 asset_processing

```text
正在整理素材
我们正在处理你上传的图片，并补齐游戏需要的默认素材。
```

素材摘要：

```text
forest.png 已上传
cover.png 已生成
slime.png 使用默认素材
tower.png 使用默认素材
```

---

## 7.5 game_design

```text
正在设计玩法规则
我们正在设计怪物、塔、防御范围、金币、波次和胜负条件。
```

设计预览：

```text
玩法草案
- 初始金币：100
- 初始生命：10
- 防御塔价格：30
- 总波次：5
- 怪物抵达终点：生命 -1
```

---

## 7.6 code_generation

```text
正在生成可运行游戏
我们正在把玩法设计转换成浏览器可运行的 Canvas 游戏。
```

更详细文案：

```text
正在生成游戏场景、怪物逻辑、防御塔攻击逻辑和 UI 面板。
```

---

## 7.7 build_validation

```text
正在测试游戏
我们正在检查游戏文件是否完整、安全，并确认它可以在浏览器中运行。
```

校验项：

```text
index.html 已生成
game.js 已生成
style.css 已生成
未发现危险 API
正在生成 manifest
```

---

## 7.8 repair_code

```text
正在自动修复一个小问题
我们发现生成的游戏文件有一处不兼容，正在自动修复。
```

用户层不直接显示错误堆栈。

Debug 层显示：

```text
BuildValidateAgent failed:
Forbidden pattern found in game.js: fetch()

GameCodeAgentRepair attempt #1 started
```

---

## 7.9 replan_game_design

```text
正在调整设计方案
原始设计有些功能超出了当前浏览器运行环境，我们正在简化为稳定可玩的版本。
```

例如：

```text
已调整：
- 多人联机 → 单人模式
- 3D 场景 → 2D Canvas
- 大地图 → 单屏塔防地图
```

---

## 7.10 publish_artifact

```text
正在准备预览版本
我们正在上传游戏文件，并生成可游玩的预览链接。
```

摘要：

```text
游戏文件已上传
Manifest 已生成
数据库记录已保存
```

---

## 7.11 succeeded

```text
游戏生成完成！
你现在可以预览、发布，或者重新生成一个版本。
```

按钮：

```text
预览游戏
发布到首页
重新生成
查看生成日志
```

---

## 7.12 failed

普通用户层：

```text
生成没有完成
我们在测试游戏时发现了无法自动修复的问题。你可以重新生成，或简化创意后再试一次。
```

Debug 层：

```text
Failed at: build_validation
Reason: Missing required files: game.js
Repair attempts: 2 / 2
Replan attempts: 1 / 1
```

---

## 8. 进度展示策略

## 8.1 不建议使用假百分比

不建议展示：

```text
生成中 37%
```

如果没有真实进度，假百分比会降低用户信任。

推荐展示阶段式进度：

```text
7 个阶段中的第 4 步
正在设计玩法规则
```

---

## 8.2 如果需要百分比

可以使用步骤权重：

```python
STEP_PROGRESS = {
    "safety_intake": 10,
    "intent_spec": 20,
    "asset_processing": 35,
    "game_design": 50,
    "code_generation": 70,
    "build_validation": 85,
    "publish_artifact": 95,
    "done": 100,
}
```

Repair 和 Replan 时不建议大幅回退：

```text
正在修复，当前进度保持在 85%
正在调整设计，当前进度保持在 70%
```

---

## 9. 前端数据结构

## 9.1 GenerationTask

```ts
type StepStatus = "pending" | "running" | "completed" | "failed"

type StepSummary = {
  step: string
  title: string
  summary?: string
  status: StepStatus
}

type AgentLog = {
  agent_name: string
  message: string
  duration?: string | null
  status: StepStatus
}

type AssetItem = {
  name: string
  status: string
  type: "uploaded" | "generated" | "default"
}

type DesignPreview = {
  title: string
  type: string
  theme: string
  initial_gold: number
  initial_life: number
  tower_cost: number
  waves: number
  monster: string
  towers: string
}

type GenerationTask = {
  id: string
  status: "pending" | "running" | "succeeded" | "failed"
  current_step: string
  current_agent: string
  progress: number
  game_title: string
  manifest_url?: string | null
  preview_url?: string | null
  repair_attempts: number
  replan_attempts: number
  step_summaries: StepSummary[]
  design_preview?: DesignPreview | null
  assets: AssetItem[]
  logs: AgentLog[]
  error_message?: string | null
}
```

---

## 9.2 接口响应示例

```json
{
  "id": "task_123",
  "status": "running",
  "current_step": "game_design",
  "current_agent": "GameDesignAgent",
  "progress": 57,
  "game_title": "魔法森林守卫战",
  "manifest_url": null,
  "preview_url": null,
  "repair_attempts": 0,
  "replan_attempts": 0,
  "step_summaries": [
    {
      "step": "safety_intake",
      "status": "completed",
      "title": "检查创意和素材",
      "summary": "Prompt and assets passed safety check"
    },
    {
      "step": "intent_spec",
      "status": "completed",
      "title": "理解你的游戏创意",
      "summary": "识别为魔法森林塔防游戏"
    },
    {
      "step": "asset_processing",
      "status": "completed",
      "title": "整理素材",
      "summary": "已处理 1 张上传图片，并补齐默认素材"
    },
    {
      "step": "game_design",
      "status": "running",
      "title": "设计玩法规则",
      "summary": "正在生成波次、金币、生命值和防御塔规则"
    }
  ],
  "design_preview": {
    "title": "魔法森林守卫战",
    "type": "塔防",
    "theme": "魔法森林",
    "initial_gold": 100,
    "initial_life": 10,
    "tower_cost": 30,
    "waves": 5,
    "monster": "史莱姆",
    "towers": "蘑菇塔 / 水晶塔"
  },
  "assets": [
    {
      "name": "forest.png",
      "status": "已上传",
      "type": "uploaded"
    },
    {
      "name": "cover.png",
      "status": "已生成",
      "type": "generated"
    },
    {
      "name": "slime.png",
      "status": "默认素材",
      "type": "default"
    },
    {
      "name": "tower.png",
      "status": "默认素材",
      "type": "default"
    }
  ],
  "logs": [
    {
      "agent_name": "SafetyIntakeAgent",
      "message": "Prompt and assets passed safety check",
      "duration": "0.8s",
      "status": "completed"
    },
    {
      "agent_name": "IntentSpecAgent",
      "message": "识别为魔法森林塔防游戏",
      "duration": "1.2s",
      "status": "completed"
    },
    {
      "agent_name": "AssetAgent",
      "message": "已处理 1 张上传图片，并补齐默认素材",
      "duration": "2.3s",
      "status": "completed"
    },
    {
      "agent_name": "GameDesignAgent",
      "message": "正在生成波次、金币、生命值和防御塔规则",
      "duration": null,
      "status": "running"
    }
  ]
}
```

---

## 10. 实时更新策略

当前实现：

```text
主通道：SSE
降级：30 秒低频查询
```

SSE：

```text
GET /tasks/:task_id/events
```

Worker/API 每次状态、步骤或日志事务提交后，通过 Redis Pub/Sub 发布轻量失效信号；SSE API 再从 PostgreSQL 读取完整任务快照。Redis 不保存业务状态。

降级查询：

```text
GET /tasks/:task_id
30s，仅用于 SSE 断线兜底
```

事件示例：

```json
{
  "type": "step_started",
  "step": "code_generation",
  "title": "正在生成可运行游戏"
}
```

```json
{
  "type": "step_completed",
  "step": "code_generation",
  "summary": "已生成 index.html、style.css、game.js"
}
```

```json
{
  "type": "repair_started",
  "attempt": 1,
  "message": "发现一个小问题，正在自动修复"
}
```

---

## 11. 页面组件设计

## 11.1 组件列表

```text
CreatePage
PromptComposer
AssetUploader
ExamplePromptList
GenerationStatusPanel
GenerationTimeline
CurrentStepCard
GameDesignPreviewCard
AssetProcessingCard
AgentSummaryCard
AgentLogDrawer
ArtifactStatusStrip
ActionBar
```

---

## 11.2 GenerationStatusPanel

职责：

```text
拉取任务状态
聚合步骤信息
维护 SSE 连接、重连和 30 秒兜底查询
根据任务状态渲染页面
```

Props：

```ts
type GenerationStatusPanelProps = {
  taskId: string
}
```

---

## 11.3 GenerationTimeline

职责：

```text
展示 7 个生成阶段
高亮当前步骤
显示 completed / running / pending / failed
```

Props：

```ts
type GenerationTimelineProps = {
  steps: StepSummary[]
  currentStep: string
}
```

---

## 11.4 CurrentStepCard

职责：

```text
展示当前阶段的用户友好文案
展示状态 badge
展示 repair / replan 的特殊说明
```

Props：

```ts
type CurrentStepCardProps = {
  status: GenerationTask["status"]
  currentStep: string
  errorMessage?: string | null
}
```

---

## 11.5 GameDesignPreviewCard

职责：

```text
展示 GameDesignAgent 生成的游戏设计草案
```

Props：

```ts
type GameDesignPreviewCardProps = {
  design?: DesignPreview | null
}
```

---

## 11.6 AgentSummaryCard

职责：

```text
展示 Agent 执行摘要
支持打开完整日志
```

Props：

```ts
type AgentSummaryCardProps = {
  logs: AgentLog[]
  onOpenLogs: () => void
}
```

---

## 12. 页面状态机

Create 页面自身可以有以下状态：

```text
idle
editing
uploading_assets
creating_task
generating
succeeded
failed
```

状态流转：

```text
idle
→ editing
→ uploading_assets
→ creating_task
→ generating
→ succeeded / failed
```

对应 UI：

| 页面状态 | UI |
|---|---|
| idle | 空输入页 |
| editing | Prompt 输入 + 素材上传 |
| uploading_assets | 上传进度 |
| creating_task | 创建任务 loading |
| generating | GenerationStatusPanel |
| succeeded | Preview / Publish CTA |
| failed | Retry / Edit CTA |

---

## 13. 成功页设计

成功页展示：

```text
游戏生成完成
预览确认没问题后，就可以发布到首页让其他玩家游玩。
```

信息：

```text
Game ID
Version ID
Manifest URL
Preview URL
生成耗时
Agent 步骤数
Repair 次数
Replan 次数
```

按钮：

```text
预览游戏
发布到首页
重新生成
查看日志
```

发布成功后：

```text
已发布到首页
去首页查看
打开 Play 页面
```

---

## 14. 失败页设计

失败页展示：

```text
生成没有完成
系统已经尝试自动修复和重新规划，但仍未能生成可运行版本。你可以简化创意后再次生成。
```

展示字段：

```text
失败阶段
失败原因
Repair attempts
Replan attempts
最后错误
```

按钮：

```text
编辑创意
重新生成
查看技术日志
```

建议提供提示：

```text
你可以尝试：
- 减少复杂功能
- 避免多人联机、3D、大地图
- 使用 2D Canvas 可以实现的玩法
- 上传更清晰的图片素材
```

---

## 15. 移动端适配

桌面端：

```text
左侧 Timeline
右侧内容区
```

移动端：

```text
顶部显示当前阶段
Timeline 折叠成横向步骤条
游戏设计草案全宽展示
Agent 日志默认折叠
底部固定操作按钮
```

断点建议：

```text
>= 1024px: 双栏布局
768px - 1023px: Timeline 顶部横向，内容单栏
< 768px: 单栏卡片布局
```

---

## 16. 可访问性设计

建议：

```text
所有按钮有明确 label
状态颜色同时配合文字说明
loading spinner 配合文字
错误状态使用 aria-live
Timeline 当前步骤使用 aria-current
禁用按钮说明原因
```

示例：

```html
<button disabled aria-disabled="true">
  生成中，请稍候
</button>
```

---

## 17. MVP 实现优先级

## P0 必须实现

```text
Prompt 输入
素材上传
创建生成任务
生成状态 Timeline
当前阶段卡片
Agent 执行摘要
成功后预览按钮
成功后发布按钮
失败后重新生成按钮
```

## P1 加分实现

```text
游戏设计草案卡片
素材处理卡片
Manifest URL / Preview URL 展示
Agent 日志抽屉
repair / replan 特殊状态文案
SSE 实时推送
```

## P2 后续优化

```text
生成过程动画
阶段耗时统计
成本统计
版本历史
Remix 派生
生成过程截图
用户可编辑 GameSpec
```

---

## 18. 推荐测试用例

Create 输入：

```text
做一个 2D 像素风塔防小游戏，名字叫《魔法森林守卫战》。

游戏场景是一片魔法森林，怪物会从屏幕左侧沿着道路走向右侧的生命水晶。玩家需要在道路旁边放置防御塔来阻止怪物。

玩法规则：
- 玩家初始有 100 金币和 10 点水晶生命值。
- 怪物会一波一波出现，每一波怪物数量更多、速度更快。
- 玩家可以点击地图上的可建造格子放置防御塔。
- 每个防御塔花费 30 金币。
- 防御塔会自动攻击范围内最近的怪物。
- 怪物被击败后玩家获得 10 金币。
- 怪物走到终点会让水晶生命值 -1。
- 水晶生命值归零则失败。
- 成功防守 5 波怪物则胜利。

风格要求：
- 像素风
- 魔法森林背景
- 防御塔可以是蘑菇塔或水晶塔
- 怪物可以是史莱姆
- 游戏需要显示金币、生命值、当前波次、开始下一波按钮
- 适合在浏览器 Canvas 中运行
```

上传素材：

```text
forest.png
```

预期状态展示：

```text
检查创意和素材
→ 理解你的游戏创意
→ 整理素材
→ 设计玩法规则
→ 生成游戏代码
→ 测试游戏是否可运行
→ 准备预览版本
→ 游戏生成完成
```

---

## 19. 设计总结

Create 页面不是简单的输入框和 loading，而应该是一个可观测的生成控制台。

它需要同时满足：

```text
用户体验：
让用户知道系统正在认真创作，等待过程不焦虑。

工程验收：
让评审看到 Agent 流程、状态、日志、产物地址和 Preview / Publish 闭环。
```

最终页面应呈现：

```text
用户看得懂的创作进度
+ 面试官看得见的 Agent 执行证据
+ 可验证的远端产物链接
+ 成功后的预览与发布操作
```
