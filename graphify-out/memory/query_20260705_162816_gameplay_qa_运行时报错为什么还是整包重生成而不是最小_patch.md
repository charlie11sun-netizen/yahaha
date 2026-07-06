---
type: "query"
date: "2026-07-05T16:28:16.064162+00:00"
question: "gameplay QA 运行时报错为什么还是整包重生成而不是最小 patch"
contributor: "graphify"
outcome: "useful"
source_nodes: ["gameplay_repair_node()", "enabled()", "_classify_gameplay_failure()"]
---

# Q: gameplay QA 运行时报错为什么还是整包重生成而不是最小 patch

## Answer

Expanded from original query via vocab: [gameplay, repair, runtime, failure, classify, patches, code, agent, regeneration, route]. 根因：patch 路径代码齐全（_classify_gameplay_failure 正确判为 runtime，openai-agents 0.17.7 已装，use_real=true），但本地 .env 缺 CODE_AGENT_ENABLED=true（config.py 默认 False），gameplay_repair_node 的 'if failure_kind==runtime and code_agent.enabled(state)' 整体为 False 被静默跳过，直接落 balance 调参+整包重生成，且无任何日志说明原因（RepairAgent 0.0s 是特征）。修复：.env 加 CODE_AGENT_ENABLED=true；nodes.py gameplay_repair_node 增加 elif 分支，禁用回落时记日志 'code agent disabled (needs CODE_AGENT_ENABLED=true and a real-model task)'；test_gameplay_repair_legacy_path_when_disabled 断言该日志。

## Outcome

- Signal: useful

## Source Nodes

- gameplay_repair_node()
- enabled()
- _classify_gameplay_failure()