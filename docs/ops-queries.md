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
