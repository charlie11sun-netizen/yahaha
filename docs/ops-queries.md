# Ops 查询手册

以下 SQL 面向 PostgreSQL，表名与 2026-07 批次 C 迁移后的 schema 对齐。

## 日成本

```sql
select
  date_trunc('day', created_at) as day,
  count(*) as llm_calls,
  sum(prompt_tokens) as prompt_tokens,
  sum(completion_tokens) as completion_tokens,
  sum(total_tokens) as total_tokens,
  sum(cost_usd) as cost_usd
from llm_calls
group by 1
order by 1 desc;
```

## 每个成功游戏均价

```sql
select
  date_trunc('day', finished_at) as day,
  count(*) as successful_tasks,
  sum(cost_usd) as total_cost_usd,
  avg(cost_usd) as avg_cost_per_success_usd
from generation_tasks
where status = 'succeeded'
  and finished_at is not null
group by 1
order by 1 desc;
```

## 失败任务浪费额

```sql
select
  date_trunc('day', finished_at) as day,
  error_code,
  failed_stage,
  count(*) as failed_tasks,
  sum(tokens_used) as agent_tokens,
  sum(cost_usd) as wasted_cost_usd
from generation_tasks
where status = 'failed'
group by 1, 2, 3
order by 1 desc, wasted_cost_usd desc nulls last;
```

## 节点烧钱排行

```sql
select
  s.agent,
  s.name as step_name,
  count(c.id) as llm_calls,
  sum(c.total_tokens) as total_tokens,
  sum(c.cost_usd) as cost_usd,
  avg(c.latency_ms) as avg_latency_ms
from llm_calls c
join agent_steps s on s.id = c.step_id
group by 1, 2
order by cost_usd desc nulls last, total_tokens desc;
```

> 注：`CODE_AGENT_ENABLED=true` 时，`repair_code` / `revision_repair` 步骤的一次修复可能是**多轮工具循环**（每轮一条 `llm_calls`，`step_id` 都指向同一修复步骤），因此这两个节点的 `llm_calls` 计数会大于 `agent_steps` 里的 attempt 数，成本也相应集中——属预期，不是重复计费。

## 节点失败率与尝试次数

```sql
select
  name as step_name,
  attempt,
  count(*) as runs,
  count(*) filter (where status = 'failed') as failures,
  round(
    100.0 * count(*) filter (where status = 'failed') / nullif(count(*), 0),
    2
  ) as failure_rate_pct
from agent_steps
group by 1, 2
order by failure_rate_pct desc, runs desc;
```

## Repair / Replan 溯源链路

```sql
select
  repair.task_id,
  repair.seq as repair_seq,
  repair.name as repair_step,
  repair.attempt as repair_attempt,
  cause.seq as caused_by_seq,
  cause.name as caused_by_step,
  cause.status as caused_by_status
from agent_steps repair
left join agent_steps cause on cause.id = repair.caused_by_step_id
where repair.caused_by_step_id is not null
order by repair.created_at desc;
```

## Prompt cache 加权命中率

命中率必须按 token 加权，不能直接平均每次调用的百分比。下面同时按 workflow 和多轮请求序号观察缓存预热过程：

```sql
select
  coalesce(workflow_name, '<missing>') as workflow_name,
  coalesce(request_index, 0) as request_index,
  count(*) as calls,
  sum(prompt_tokens) as prompt_tokens,
  sum(cached_tokens) as cached_tokens,
  sum(prompt_tokens - cached_tokens) as uncached_tokens,
  round(
    100.0 * sum(cached_tokens) / nullif(sum(prompt_tokens), 0),
    2
  ) as weighted_cache_hit_pct,
  round(
    100.0 * sum(cache_write_tokens)
      / nullif(sum(prompt_tokens - cached_tokens), 0),
    2
  ) as cache_write_pct
from llm_calls
group by 1, 2
order by 1, 2;
```

## Cache usage 上报覆盖率

`cache_read_reported=false` 表示 provider 没有提供该字段，与“明确上报 0 个 cached token”不同。优化命中率前先确认覆盖率：

```sql
select
  provider,
  provider_route,
  model,
  count(*) as calls,
  count(*) filter (where cache_read_reported) as cache_read_reported_calls,
  count(*) filter (where cache_write_reported) as cache_write_reported_calls,
  round(100.0 * count(*) filter (where cache_read_reported) / count(*), 2)
    as cache_read_reporting_pct,
  round(100.0 * count(*) filter (where cache_write_reported) / count(*), 2)
    as cache_write_reporting_pct
from llm_calls
group by 1, 2, 3
order by calls desc;
```

## Cache key / prompt / toolset 漂移

以下字段只保存 SHA-256，不保存原始 cache key、prompt 前缀或工具 schema：

```sql
select
  prompt_cache_namespace,
  prompt_version,
  prompt_cache_key_hash,
  cache_prefix_hash,
  toolset_hash,
  cache_bypass_reason,
  count(*) as calls,
  round(
    100.0 * sum(cached_tokens) / nullif(sum(prompt_tokens), 0),
    2
  ) as weighted_cache_hit_pct
from llm_calls
group by 1, 2, 3, 4, 5, 6
order by calls desc;
```

同一 workflow 出现多个 `cache_prefix_hash` 或 `toolset_hash`，通常意味着稳定前缀或工具定义发生漂移；`cache_bypass_reason` 可直接解释为何未走显式/路由缓存。

## 导出一个任务的完整分析包

```powershell
python -m app.tools.export_generation_analysis TASK_ID --pretty > generation-analysis.json
```

导出内容包括 task/spec/design/DesignContract、全部 step decision、agent logs、逐次 `llm_calls`、缓存聚合和详细 `agent_trace_events`。默认 `CODE_AGENT_TRACE_MAX_PAYLOAD_CHARS=0`，保存完整事件 payload；如部署方设置了正数上限，导出会用 `payload_truncated` 和 `truncated_trace_event_count` 明确标记历史截断。
