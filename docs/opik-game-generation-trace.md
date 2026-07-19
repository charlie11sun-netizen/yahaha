# Opik 游戏生成流程追踪记录

本文记录 GameWeave 当前的 Opik 接入方式，以及如何按照一个游戏的完整生成流程检索、排查和导出 Agent 轨迹。

## 1. 目标

一次游戏生成可能包含规划、资产规划、代码生成、构建校验、游玩 QA、修复和发布等多个阶段。Opik 中需要能够回答：

- 这个游戏经历了哪些生成或修订任务？
- 每个阶段调用了什么模型、工具和参数？
- 哪一步失败、重试或触发了 replan？
- 某个版本的生成结果对应哪些 prompt、tool result 和评测结果？
- 成功请求和失败请求是否都能进入后续调优数据集？

当前方案使用一个游戏生成根 trace 聚合一次任务的生命周期，再用阶段 span 表示 LangGraph 节点；OpenAI、OpenAI Agents 和工具调用作为嵌套 observation 保留在对应阶段下面。

## 2. 部署与开关

本地 Docker 部署时，GameWeave 使用以下非敏感配置连接 Opik：

```dotenv
OPIK_ENABLED=true
OPIK_URL_OVERRIDE=http://host.docker.internal:15173/api
OPIK_PROJECT_NAME=gameweave-agent
OPIK_WORKSPACE=default
OPIK_ENVIRONMENT=staging
```

访问地址：

- Opik UI：<http://localhost:15173/>
- GameWeave API：<http://localhost:8000>
- Opik 项目：`gameweave-agent`

`OPIK_ENABLED=false` 时，埋点函数退化为空操作，不影响游戏生成；Opik 上报失败也采用 fail-open 策略，不会让生成任务因为日志系统故障而失败。

## 3. Trace 树结构

```text
game-generation:<游戏标题>
├── stage.intent_spec
├── stage.gameplay_planning
├── stage.asset_planning
├── stage.code_generation
├── stage.validation
├── stage.repair / stage.replan
└── stage.publish
    ├── LLM generation
    ├── tool call
    └── OpenAI Agents 子调用
```

根 trace 在 `run_generation()` 入口创建，阶段 span 由 `logged()` 装饰的 LangGraph 节点创建。任务结束时，根 trace 会补齐最终的游戏、版本、状态和错误信息，并调用 flush 将数据发送到 Opik。

实现位置：

- 根 trace、阶段 span 和更新函数：[backend/app/agents/opik_integration.py](../backend/app/agents/opik_integration.py#L83)
- 生成任务生命周期和最终元数据回填：[backend/app/agents/pipeline.py](../backend/app/agents/pipeline.py#L400)
- LangGraph 阶段 span：[backend/app/agents/tracing.py](../backend/app/agents/tracing.py#L253)

## 4. Schema 版本

当前 schema 版本：

```text
gameweave.opik.generation/2.1
```

以后新增或改变字段时，应升级该值，并在数据导出程序中保留兼容处理。

v2 在根 trace 和阶段 span 上增加可搜索的 DesignContract 字段；v2.1 补充 Opik trace 直接关联和 cache observability：

- 身份：`contract_hash`、`contract_revision`、`design_contract_schema_version`；
- Gate：`contract_gate_passed`、`contract_gate_code`、覆盖率和孤立 semantic ID 指标；
- Diff：资产、代码、验收影响标志，以及 semantic ID / requirement 变更计数；
- Acceptance：测试数、结果数、失败数和 `required_acceptance_pass`；
- FrameAudit：审计资产数、失败帧数、`failed_semantic_ids`、覆盖率、重生成数量和 `regeneration_semantic_ids`；
- Revision 资产路由：`contract_diff_asset_impacted` 是最终路由值，`contract_diff_contract_asset_impacted` 保留纯合同 diff 原值，`contract_diff_asset_impact_source=llm` 表示由 FeedbackUnderstandingAgent 根据反馈、父合同和现有资产清单做出判断；理由和置信度分别记录在 `contract_diff_asset_impact_rationale` / `contract_diff_asset_impact_confidence`；
- 版本语义：`contract_version` / `trace_contract_version` 表示 `agent-step/v2` trace envelope；DesignContract 修订号只使用 `contract_revision` / `design_contract_revision`。
- 直接关联：`opik_trace_id` 同时保存在 `generation_tasks`、根 trace metadata/output 和任务 API 中；
- Cache 汇总：`llm_call_count`、`llm_prompt_tokens`、`llm_cached_tokens`、`llm_uncached_tokens`、`llm_cache_hit_rate`、`llm_cache_write_rate`、retry/latency/cost 和 provider 上报覆盖数。阶段 span 是 step 汇总，根 trace 是整个 task 汇总。

### 4.1 根 trace

| 位置 | 字段 | 说明 |
| --- | --- | --- |
| `name` | `game-generation:<title>` | 生成完成后使用游戏标题；没有标题时使用 task ID |
| `thread_id` | `task:<task_id>` / `game:<game_id>` | 开始时按任务聚合，得到游戏 ID 后切换为游戏线程 |
| `metadata` | `schema_version` | 固定为当前 schema 版本 |
| `metadata` | `task_id` | 一次生成、revision 或 remix 任务的唯一 ID |
| `metadata` | `task_kind` | 例如 `generation`、`revision`、`remix` |
| `metadata` | `game_id` | 生成成功后的游戏 ID；失败的新游戏可能为空 |
| `metadata` | `base_game_id` | revision/remix 的原游戏 ID |
| `metadata` | `base_version` | revision/remix 的基准版本 |
| `metadata` | `version`、`version_id` | 生成产物版本 |
| `metadata` | `dimension` | 2D/3D 等生成维度 |
| `metadata` | `model` | 本次任务使用的主模型名称 |
| `metadata` | `status` | `running`、`succeeded`、`failed` 等最终状态 |
| `metadata` | `error_code`、`failed_stage` | 失败原因和失败阶段 |
| `metadata` | `opik_trace_id` | 与本地 `generation_tasks.opik_trace_id` 一致，可从数据库直接跳转/反查 |
| `metadata` | `llm_*` | task 级逐次调用、token、加权 cache 命中率、写入率、重试、延迟、成本和上报覆盖摘要 |
| `input` | `task_id`、`task_kind`、`prompt`、`asset_ids`、`dimension` | 任务输入；入库前应遵循统一脱敏策略 |
| `output` | `status`、`game_id`、`version`、`tokens`、`cost_usd`、`error_code` | 任务结果摘要 |
| `tags` | `gameweave`、`game-generation`、`task-kind:*`、`dimension:*`、`status:*` | 快速筛选标签 |

### 4.2 阶段 span

阶段 span 的名称为 `stage.<node_name>`，metadata 包括：

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 当前 schema 版本 |
| `task_id` | 所属生成任务 |
| `step_id` | LangGraph/任务步骤 ID |
| `node_name` | 节点名称，例如 `code_generation` |
| `agent` | 执行该阶段的 Agent |
| `display_name` | 面向 UI 的阶段名称 |
| `failed` | 是否在该阶段失败 |
| `llm_*` | 当前 step 的 cache/token/latency/cost 聚合；`llm_cache_metrics` 为同一组指标的嵌套摘要 |

阶段 output 会记录状态、token 摘要、repair/replan 次数、错误摘要和 `cache_observability`。完整的 LLM input/output、模型参数、延迟、token usage 和 tool arguments/result 由现有 OpenAI/Agents instrumentation 作为子 observation 记录。

## 5. 如何在 Opik 中查找一个游戏

### 5.1 查一个游戏的全部生成流程

在 `gameweave-agent` 项目中使用 OQL 过滤：

```text
metadata.game_id = "GAME_ID"
```

如果希望包含 revision/remix 的原始任务，也可以查：

```text
metadata.game_id = "GAME_ID" OR metadata.base_game_id = "GAME_ID"
```

打开返回的根 trace 后，可以按时间顺序查看所有阶段 span 及其 LLM/tool 子调用。

### 5.2 查一个具体任务

```text
metadata.task_id = "TASK_ID"
```

这适合排查单次失败或单次重试。对于尚未创建出 `game_id` 的失败任务，`task_id` 是主要检索入口。

### 5.3 按游戏线程查看版本演进

```text
thread_id = "game:GAME_ID"
```

该方式适合比较同一游戏的初次生成、revision、remix 和后续版本。

### 5.4 查某个阶段

```text
metadata.game_id = "GAME_ID" AND metadata.node_name = "code_generation"
```

也可以按状态筛选：

```text
metadata.game_id = "GAME_ID" AND tags contains "status:failed"
```

Opik 支持基于 trace metadata、tags 和 `thread_id` 的过滤；trace 创建后也可以更新 metadata，因此生成开始时未知的 `game_id` 可以在任务结束时回填。[创建当前 trace](https://www.comet.com/docs/opik/python-sdk-reference/context_manager/start_as_current_trace.html)、[更新当前 trace](https://www.comet.com/docs/opik/python-sdk-reference/opik_context/update_current_trace.html)、[Trace 搜索](https://www.comet.com/docs/opik/python-sdk-reference/Opik.html)

## 6. SDK 查询示例

```python
from opik import Opik

client = Opik(project_name="gameweave-agent")

traces = client.search_traces(
    project_name="gameweave-agent",
    filter_string='metadata.game_id = "GAME_ID"',
)

spans = client.search_spans(
    project_name="gameweave-agent",
    filter_string='metadata.task_id = "TASK_ID"',
)
```

如果只需要一个根 trace 的所有阶段，可以先取 trace ID，再用 `trace_id` 查询 spans。

## 7. 与 agent logs 的分工

| 系统 | 适合用途 |
| --- | --- |
| Opik | 跨阶段 trace 树、LLM/tool 调用、模型参数、延迟、token、成本、线程分组、评测和训练数据筛选 |
| `agent_trace_events` / agent logs | 详细事件 payload、状态快照、异常堆栈、代码产物和本地审计；适合精确重放和故障排查 |

两者通过 `task_id`、`step_id`、`run_id` 等字段关联。Opik 负责“看完整流程和做分析”，agent logs 负责“保留更细的本地事件和审计数据”。

`llm_cache_metrics` / `cache_observability` 是方便 Opik 展示的有界嵌套摘要，不替代原始日志。需要离线复盘、训练集构建或缓存优化时，使用：

```powershell
python -m app.tools.export_generation_analysis TASK_ID --pretty > generation-analysis.json
```

该分析包合并 task、完整 DesignContract、step decisions、agent logs、逐 provider response 的 LLM 账本和详细 trace events。`CODE_AGENT_TRACE_MAX_PAYLOAD_CHARS=0` 表示不截断 payload；正数表示只保存有明确截断标记的预览。详细事件仍受 `CODE_AGENT_TRACE_RETENTION_DAYS` 保留期约束，因此需要长期分析时应在过期前导出。

## 8. 验证记录

- 回归测试：`112 passed`（103 个合同/管线回归 + 9 个容器内 Opik 回归）
- 已验证容器内创建根 trace、阶段 span，并可按 `metadata.task_id` 查询
- 已验证根 trace 最终回填 `game_id`、`version`、`status` 和 `thread_id`
- 已从 Opik 反查 smoke trace，确认 v2 schema、合同 hash/revision、Gate、Acceptance 和 FrameAudit 字段已落库
- Worker 已重启，当前 Docker Compose 服务正常运行
- 使用合成 smoke trace 验证，未触发真实模型生成，不产生额外模型调用成本

## 9. 后续调优建议

1. 从 Opik 按 `game_id` 导出完整成功轨迹，建立成功样本集。
2. 按 `status:failed` 和 `failed_stage` 聚合失败，建立失败预测和修复样本集。
3. 按 `model`、prompt 版本、代码版本和产物版本切分实验，比较成功率、延迟、token 和缓存命中率。
4. 将人工反馈或自动评分写入 trace feedback，再导出为 SFT、DPO 或 tool-use 评测数据。
