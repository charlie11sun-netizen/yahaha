# GameWeave AI Create 页面重新设计说明

> 目标：将 Create 页面从“信息密集的三栏控制台”重新设计为一个更简洁、更聚焦、更适合桌面端的 AI 游戏创作工作台。  
> 页面风格：明亮、简洁、现代、低噪音、以任务状态为核心。

---

## 1. 设计背景

GameWeave AI 的 Create 页面承担的是平台最核心的创作者旅程：

```text
输入创意 / 上传素材
→ 创建生成任务
→ Multi-Agent 生成游戏
→ 校验和修复
→ 生成远端产物
→ 预览
→ 发布到首页
```

上一版设计完整展示了输入、上传、Agent Workflow、日志、Preview、Artifact Status、操作按钮等内容，但视觉上存在几个问题：

1. 三栏同时展示，信息密度过高。
2. 过多卡片、边框、状态字段让页面像后台控制台。
3. 技术信息提前暴露，普通用户理解成本较高。
4. 生成前、生成中、成功后展示内容没有明显区分。
5. Publish、Artifact URL、Repair/Replan 等信息在不需要时也一直出现，造成噪音。

因此新版采用 **两栏布局 + 分阶段展示 + 渐进披露** 的设计策略。

---

## 2. 核心设计原则

### 2.1 聚焦当前任务

用户在不同阶段关注的信息不同：

| 阶段 | 用户最关心什么 | 页面应该突出什么 |
|---|---|---|
| 生成前 | 我要输入什么，怎么开始 | Prompt 输入、素材上传、Generate 按钮 |
| 生成中 | 系统是不是还在运行，现在做到哪了 | 当前步骤、最近更新时间、连接状态、简化步骤流 |
| 出错修复中 | 是不是失败了，系统有没有自救 | Issue found、Auto-repairing、Retry / Repair 状态 |
| 成功后 | 能不能试玩，能不能发布 | Preview、Publish、Generated artifact |
| 失败后 | 为什么失败，下一步怎么办 | 失败原因、Retry、View activity、Regenerate |

因此页面不应该在所有状态下都展示同一套复杂面板。

---

### 2.2 渐进披露

默认只展示用户需要理解的内容。

技术信息放在可展开层级中：

```text
默认展示：
- 当前步骤
- 最近更新
- 简化状态
- 最近 3 条用户可读活动

点击展开后展示：
- 完整 Agent Activity
- 技术日志
- Manifest URL
- Bundle URL
- Repair/Replan 详细信息
```

这样既满足工程 Demo 的可验证性，也不会让普通用户被技术细节淹没。

---

### 2.3 Agent-aware，但不 Agent-heavy

页面需要反映真实 Multi-Agent 工作流，但 UI 不应该把所有 Agent 名称都直接堆给用户。

真实后端节点可以是：

```text
SafetyIntake
IntentSpec
AssetProcessing
GameDesign
CodeGeneration
BuildValidation
RepairCode / ReplanGameDesign
PublishArtifact
Done
```

但用户看到的是更友好的步骤：

```text
Idea checked
Game spec created
Assets processed
Game designed
Files generated
Validating build
Preparing preview
Ready to publish
```

这样用户可以理解流程，同时设计仍然能映射真实 Agent 架构。

---

## 3. 新版页面信息架构

新版 Create 页面采用桌面端 **2 栏布局**。

```text
Header

Create with AI
Describe your idea, upload references, and generate a playable web game.

┌──────────────────────────────────────────────┐ ┌──────────────────────┐
│ Main Workspace                               │ │ Preview / Status     │
│                                              │ │                      │
│  Game brief                                  │ │  Preview placeholder │
│  Creating your game                          │ │  Runtime status      │
│  Recent updates                              │ │  Current actions     │
│                                              │ │                      │
└──────────────────────────────────────────────┘ └──────────────────────┘
```

### 推荐桌面尺寸

```text
Canvas: 1440 × 1000 或 1512 × 982
Main content max-width: 1360px
Outer padding: 32px
Column gap: 20–24px
Left/main column: flexible, approximately 65–68%
Right column: 340–380px
```

---

## 4. 顶部导航设计

### 内容

```text
GameWeave AI    Explore    Create    My Games    How It Works          My Tasks    Save Draft    Avatar
```

### 设计要求

- `Create` 处于 active 状态，可使用蓝紫色下划线。
- `My Tasks` 用轻量按钮，方便用户查看历史生成任务。
- `Save Draft` 只在有输入内容时突出。
- Avatar 保持简洁，不需要复杂下拉菜单常驻展示。

---

## 5. 页面标题区

新版不再使用营销式大 Hero，而是使用紧凑工具页标题。

```text
Create with AI
Describe your idea, upload references, and generate a playable web game.
```

### 设计理由

Create 页面是工作台，不是首页。标题区应帮助用户确认当前位置，而不是占用过多首屏空间。

---

## 6. 主工作区设计

## 6.1 Game Brief 卡片

在生成中状态下，不再展示完整大表单，而是展示压缩后的任务摘要。

```text
Game brief
[Cyberpunk cat runner]
2 assets uploaded · Arcade · Cyberpunk · Browser runtime

[Edit brief]
```

### 设计理由

用户提交后，输入内容已经不是主任务。将输入区折叠成摘要，可以让页面把注意力转移到生成进度上。

### 字段建议

| UI 字段 | 来源 |
|---|---|
| brief title | `game_spec.title` 或 prompt 摘要 |
| assets count | `asset_ids.length` |
| genre | `game_spec.genre` 或 options.genre |
| art style | options.art_style |
| runtime | `runtime` / `target_runtime` |

---

## 6.2 Creating Your Game 主状态卡

这是生成中页面的视觉核心。

### 顶部状态

```text
Creating your game
Step 6 of 8 · Validating build

Last update 4s ago    Connected    Elapsed 38s
You can leave this page
```

### 状态字段

| UI | 字段 |
|---|---|
| Step 6 of 8 | 根据 `current_step` 映射得到 |
| Validating build | `current_step_label` |
| Last update 4s ago | `last_event_at` |
| Connected | SSE 连接状态（断线时指数退避重连） |
| Elapsed 38s | `now - task.created_at` |
| You can leave this page | 任务已持久化并可从 My Tasks 恢复 |

---

## 6.3 简化步骤流

新版不展示所有技术节点，而是展示 8 个用户友好步骤。

```text
✓ Idea checked
✓ Game spec created
✓ Assets processed
✓ Game designed
✓ Files generated
→ Validating build
○ Preparing preview
○ Ready to publish
```

### Agent 映射关系

| 用户看到的步骤 | 真实 Agent / Node |
|---|---|
| Idea checked | SafetyIntakeAgent |
| Game spec created | IntentSpecAgent |
| Assets processed | AssetAgent |
| Game designed | GameDesignAgent |
| Files generated | GameCodeAgent |
| Validating build | BuildValidateAgent / RepairCodeNode / ReplanGameDesignNode |
| Preparing preview | PublishArtifactAgent |
| Ready to publish | Done Handler |

---

## 6.4 Repair / Replan 的展示方式

Repair 和 Replan 不再作为单独的大卡片常驻展示，而是嵌入到当前步骤下。

### Repair 状态示例

```text
Validating build

Issue found · Auto-repairing
Repair attempt 1 of 2 — Removing unsupported browser API from game.js
```

### Replan 状态示例

```text
Validating build

Design is too complex for the current runtime
Replanning a simpler playable version · Attempt 1 of 1
```

### 设计理由

用户不需要理解完整的 bounded ReAct repair loop，但需要知道：

1. 系统发现了问题。
2. 问题不是最终失败。
3. 系统正在自动修复或重新规划。
4. 如果最终失败，会给出可操作出口。

---

## 6.5 Recent Updates

默认只显示最近 3 条用户可读活动。

```text
Recent updates

4s ago    Repair attempt started
9s ago    Validation found an issue
18s ago   Assets processed successfully

View full activity →
```

### 设计原则

- 默认不要显示完整日志。
- 文案面向用户，而不是工程师。
- 每条日志应该说明“发生了什么”，而不是堆原始 JSON。
- 完整 Agent 日志放到 Activity Drawer 或 Technical Logs 中。

---

## 7. 右侧 Preview / Status 面板

右侧只保留与预览直接相关的信息。

```text
Preview

[ browser/game placeholder illustration ]
Preparing runtime...

✓ Sandbox ready
○ Manifest pending
○ Bundle pending

[View Activity]
[Cancel task]
```

### 生成中不展示

以下信息不要在生成中默认展示：

```text
Bundle URL
Manifest URL
Repair attempts
Replan attempts
Runtime technical details
Disabled Publish button
```

这些信息会让页面显得技术化、杂乱。可以在成功后或展开技术详情时展示。

---

## 8. 不同状态下的页面变化

## 8.1 初始状态

用户还没有点击 Generate。

### 主区域

```text
What do you want to create?

[Large prompt input]

Prompt examples:
Pixel racing game / Cozy forest puzzle / Cyberpunk cat runner

Upload references
Advanced options collapsed

[Generate Game]
```

### 右侧

```text
Preview
Your playable preview will appear here.

Runtime: Browser iframe-html
Sandbox: enabled
Object storage: ready
```

---

## 8.2 生成中状态

用户已经提交任务，Agent 正在执行。

### 主区域

```text
Game brief
Cyberpunk cat runner
2 assets uploaded · Arcade · Cyberpunk · Browser runtime

Creating your game
Step 6 of 8 · Validating build
Last update 4s ago · Connected · Elapsed 38s

✓ Idea checked
✓ Game spec created
✓ Assets processed
✓ Game designed
✓ Files generated
→ Validating build
  Issue found · Auto-repairing
  Repair attempt 1 of 2 — Removing unsupported browser API from game.js
○ Preparing preview
○ Ready to publish

Recent updates
4s ago Repair attempt started
9s ago Validation found an issue
18s ago Assets processed successfully

View full activity
```

### 右侧

```text
Preview
Preparing runtime...

✓ Sandbox ready
○ Manifest pending
○ Bundle pending

[View Activity]
[Cancel task]
```

---

## 8.3 成功状态

生成完成后，页面从“进度展示”切换到“预览与发布”。

### 主区域

```text
Game ready
Neon Alley Cat

✓ Runtime validation passed
✓ Manifest uploaded
✓ Metadata saved
✓ Preview ready

Generated files
index.html
style.css
game.js
manifest.json

[View manifest]
[Regenerate]
```

### 右侧

```text
Play Preview
[iframe preview]

[Play Preview]
[Publish to Home]
```

---

## 8.4 失败状态

任务最终失败时，页面要给出清晰原因和操作出口。

```text
Generation stopped
Build validation could not pass after repair attempts.

Reason:
Unsupported browser API remained in game.js

Actions:
[Retry from validation]
[Regenerate simpler version]
[View full activity]
```

失败状态不应该只显示红色错误，也不应该白屏。

---

## 9. 长任务体验设计

为了避免用户怀疑系统卡住，需要区分真实 Agent 事件和 UI 心跳提示。

### 9.1 真实事件

来自后端 AgentLog / task event。

例如：

```text
Repair attempt started
Validation found an issue
Manifest uploaded
```

### 9.2 UI 心跳提示

这是前端根据时间计算出来的提示，不伪造成 Agent 日志。

```text
No new event for 4s? That’s normal during code repair.
We’ll keep updating this view.
```

### 9.3 建议阈值

| 条件 | UI 提示 |
|---|---|
| 0–8 秒无新事件 | 只更新 Last update |
| 8–20 秒无新事件 | Still working on current step |
| 20–45 秒无新事件 | This step is taking longer than usual |
| 45 秒以上无新事件 | Show View activity / Keep waiting / Cancel |
| 连接断开 | Reconnecting to task updates |
| 重连成功 | Reconnected. Latest task state restored |

---

## 10. 推荐前端字段

前端 Create 页面建议从任务接口获得以下字段。

```ts
interface GenerationTaskViewModel {
  id: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed';

  currentStep: string;
  currentStepLabel: string;
  currentAgent?: string;

  stepIndex: number;
  totalSteps: number;

  lastEventAt: string;
  createdAt: string;
  updatedAt: string;

  connectionStatus: 'connected' | 'reconnecting' | 'disconnected';

  briefTitle: string;
  assetCount: number;
  genre?: string;
  artStyle?: string;
  runtime: string;

  repairAttempts: number;
  maxRepairAttempts: number;
  replanAttempts: number;
  maxReplanAttempts: number;

  currentIssue?: {
    type: 'validation' | 'repair' | 'replan' | 'upload' | 'runtime';
    title: string;
    message: string;
  };

  recentUpdates: Array<{
    time: string;
    level: 'info' | 'success' | 'warning' | 'error';
    message: string;
  }>;

  previewStatus: {
    sandboxReady: boolean;
    manifestReady: boolean;
    bundleReady: boolean;
    previewUrl?: string;
  };

  result?: {
    gameId: string;
    versionId: string;
    manifestUrl: string;
    previewUrl: string;
  };

  errorMessage?: string;
}
```

---

## 11. 视觉规范建议

### 颜色

```text
Background: #F8FAFC / #FFFFFF
Card: #FFFFFF
Border: #E5E7EB
Text primary: #0F172A
Text secondary: #64748B
Primary accent: #5B5FF7 / #6D5DF6
Success: #16A34A
Warning: #F59E0B
Danger: #EF4444
Info background: #EEF2FF
```

### 圆角

```text
Card radius: 16px
Button radius: 10–12px
Chip radius: 999px
```

### 间距

```text
Page padding: 32px
Column gap: 20–24px
Card padding: 24px
Section spacing: 16–24px
```

### 字体层级

```text
Page title: 28–32px / 700
Card title: 18–20px / 700
Body: 14–15px / 400–500
Meta: 12–13px / 400
```

---

## 12. 和上一版相比的主要变化

| 上一版 | 新版 |
|---|---|
| 三栏布局 | 两栏布局 |
| 输入、进度、日志、预览、Artifact 全量展示 | 按状态展示核心信息 |
| Agent 节点全部平铺 | 用户友好步骤 + 技术详情折叠 |
| Repair / Replan 单独占用流程行 | 嵌入当前验证步骤下 |
| Artifact Status 常驻 | 成功后或展开后展示 |
| Disabled Publish 常驻 | 成功后才显示 Publish |
| Recent Activity 展示较多 | 默认只显示最近 3 条 |
| 工程控制台感强 | AI 创作工具感更强 |

---

## 13. 最终设计目标

新版 Create 页面要让用户获得三个明确感受：

1. **我知道现在进行到哪一步了。**  
   通过 `Step 6 of 8`、简化步骤流和当前状态实现。

2. **我知道系统没有卡住。**  
   通过 `Last update`、`Connected`、`Elapsed`、心跳提示和 Recent updates 实现。

3. **我知道出问题时系统会处理。**  
   通过 `Issue found · Auto-repairing`、Repair attempt、Replan 状态和失败出口实现。

最终页面应该像一个成熟的 AI 创作工具，而不是一个后台日志面板。

---

## 14. 推荐落地优先级

### P0：必须实现

- 两栏桌面布局
- Prompt 提交后折叠为 Game Brief
- 简化步骤流
- 当前步骤展示
- Last update / Connected / Elapsed
- 最近 3 条用户可读更新
- Preview pending 状态
- 成功后 Preview / Publish
- 失败后 Retry / View activity

### P1：增强体验

- Full Activity Drawer
- Technical Logs 折叠面板
- Repair / Replan 子状态
- SSE 实时更新 + 30 秒低频查询兜底
- 任务离开页面后可恢复

### P2：加分项

- Agent 日志可回放
- 任务耗时统计
- Token / 成本统计
- 生成质量评分
- 版本对比 / Regenerate history
- Play 页面加载埋点联动
