# Agent Case Graph

[![tests](https://github.com/znbsf/agent-case-graph/actions/workflows/tests.yml/badge.svg)](https://github.com/znbsf/agent-case-graph/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)

**Append-only agent traces with a graph-first key path, visible outcomes and source-bound local expansion.**

Agent Case Graph（ACG）把 Agent 的操作、证据、产物和结论先保存为 append-only JSONL，再投影为同一个 `paper-trace-0.1` 模型：

- `trace.puml`：可评审、可版本比较的 PlantUML 静态基准图；
- `sequence.puml`：按显式时序关系线性化的 PlantUML 单次执行投影，保留源记录号；
- `graph.html`：默认主路径图；主路径与旁支、节点内结果、点击后的局部动作 → 结果 → 结论；
- `reader.html`：辅助阅读页，保留逐阶段的问题、动作、结果、边界与来源；
- `story-model.json`：图形展示模型，可选来源绑定的主路径 / 旁支与结果短句；
- `workbench.html`：证据工作台，阶段总览 / 阶段关系 / 证据链 / 单次执行 / 原始记录；
- `workbench-model.json`：无损展示分区、聚合边的原始见证与研究依据；`workbench-legacy.html` 保留旧技术视图用于对照；
- `review-model.json`：有源节点引用的阶段阅读索引，不回写账本、不产生新的验收结论；
- `loop-model.json`：由 canonical graph 派生的双循环聚合索引；
- `sequence-model.json`：单次执行生命线、步骤和 ExecutionIteration 作用域；
- `trace-model.json`：技术图共享的展示模型，阅读索引在其聚合关系上继续派生；
- `graph.json`：完整 canonical typed graph。

默认图先回答三个问题，原始记录和完整关系按需查看：

1. 最初想解决什么，记录停在哪里？
2. 每一步做了什么、得到什么结果，为什么调整方向？
3. 结论的证据和边界是什么，哪些信息仍然缺失？

## 论文对应

视觉语法主要来自：

- [Graph of Trace, ACL 2026](https://aclanthology.org/2026.acl-demo.29/)：左侧逐步操作、中间自上而下 DAG、右侧节点详情；
- [LEDGER, arXiv:2608.18398](https://arxiv.org/abs/2608.18398)：`Trace Records -> Evidence Nodes -> Workflow Nodes`，以及 `context / plan / inspect / execute / validate / claim` 六阶段；
- [AgentDiagnose, EMNLP 2025](https://aclanthology.org/2025.emnlp-demos.15/)：不同诊断视图联动，但不把所有分析塞进核心 DAG。

这里借鉴的是可读性和审计结构，不复制论文界面或数据，也不把论文结果当成本实现的验收。
新版工作台还参考 Shneiderman 的按需详情原则与 Gansner 等人的有向图布局方法；
逐项原文、实现选择、测试和限制见 [工作台结构依据](docs/workbench-research-basis.md)。LEDGER 是预印本。

![PlantUML paper-trace quickstart](docs/assets/paper-trace-quickstart.svg)

仓库保留一份可直接评审的 [Quickstart PlantUML 基准](examples/paper-trace/quickstart.puml)；CLI 生成结果仍以 Ledger 为准，可随时重建。

## 数据流

```text
events.jsonl
  append-only · live | reconstructed | synthetic
        |
        v
Canonical Graph
  stable IDs · typed nodes/edges · lint · runtime gates
        |
        v
paper-trace-0.1 + loop-projection-0.1 + sequence-projection-0.1
  Dialogue Round · Execution Iteration · Sequence · Workflow Phase · Evidence · Trace
        |
        +--> trace.puml
        +--> sequence.puml
        +--> graph.html
```

页面位置、Ledger 时间和卡片顺序都不会自动成为因果。只有显式 edge 才进入关系图。

## 快速开始

```bash
git clone https://github.com/znbsf/agent-case-graph.git
cd agent-case-graph
python -m venv .venv
python -m pip install -e .

acg validate-ledger examples/quickstart/events.jsonl
acg lint --strict examples/quickstart/events.jsonl
acg project examples/quickstart/events.jsonl \
  --out-dir examples/quickstart/generated \
  --title "Agent Case Graph Quickstart" \
  --default-locale zh-CN
```

打开 `examples/quickstart/generated/graph.html`，或使用 PlantUML 渲染 `trace.puml`：

```powershell
.\scripts\render-plantuml.ps1 `
  -InputPath .\examples\quickstart\generated\trace.puml `
  -JarPath C:\path\to\plantuml.jar `
  -Format svg
```

将输入改成 `examples/quickstart/generated/sequence.puml` 即可生成时序图。时序投影先按 `precedes / invokes / produces / checks / supersedes` 等显式关系构造偏序，同级节点再用源记录号稳定排序。线性化后的相邻步骤不一定互为因果；因果仍以 canonical typed edge 为准。

PowerShell 用户可以直接运行仓库根目录的 `acg.ps1`。

## 先看路径和结果，再展开证据

打开 `graph.html`，直接看主路径和节点内的结果；点击节点在原位置下方展开动作、结果、结论和反证，不切走全图。
虚线只表示复盘顺序 / 主题分组；局部箭头来自真实 typed edge。未知结果不会从标题的情绪或 PASS 字样猜测。
`reader.html` 保留长文阅读；两种入口都使用同一阶段作用域，不借共享 Case/Run 引入全图。

需要编辑主路径和旁支时，显式传入 `--presentation graph-presentation.json`。
该可选 JSON 必须声明 `version: "case-story-0.1"`、匹配账本的 `source_sha256` 和 `cards`。
每张卡片包含唯一 `id`、`title`、`stage_ids` / `node_ids`，旁支用 `parent_id` 指向主节点；所有阶段必须恰好出现一次。
可选 `summary`、`boundary`、`results`（最多 3 条）仅改变展示；每条结果含 `text`、范围内的 `source_ids` 和 `tone`。
`tone` 可选 `recorded / gain / open / negative / hypothesis / paused`，不是新的运行验收状态。
哈希、引用、覆盖与父子关系均校验；没有 presentation 时按阶段展示源记录，不自动猜测旁支和成败。
短句和引用仍需人工审核：结构校验能阻止失配，不能证明文字总结正确。

历史重建、合成示例以及已记录的正文缺失数量在页首显示。页面不会通过解析描述中的 PASS 字样来推断成功；
也不会把上一阶段用来影响计划的输出当成下一阶段自己产生的结果。阶段只是阅读分组，不等于原生执行迭代。

右上角进入 `workbench.html`，保留以下五个技术视图；技术视图可返回主路径图：

- **阶段总览**：先看阶段与源结论；每条聚合边均可追到原始边，不按位置补关系。
- **阶段关系**：同阶段的目标、动作、结果、结论放在一起；展开后局部自上而下，关联上下文用虚框标出。
- **证据链**：从 Claim 反查支持、反证、产物和检查；保留原状态，不新增验收。
- **单次执行**：按阶段选择对应执行作用域，查看 User / Agent / Tool / Evidence / Evaluator 的时序。
- **原始记录**：按 Ledger `sequence` 分页查看全部事件；顺序不是因果。

左侧是可收起的阶段导航，中间优先留给关系图，右侧详情只在点击后出现。
卡片完整换行；搜索、单跳聚焦、真实缩放和平移帮助定位。默认收起结构边，来源始终可查。
旧 Loop Overview 和六阶段 Workflow 保留在 `workbench-legacy.html`，不是新版默认布局。

Sequence 负责回答“单次执行先后发生了什么”；Workflow / Evidence 负责回答“为什么这样计划、什么证据改变了计划、哪些检查支撑结论”。两者来自同一 canonical graph，互为投影而不是互相替代。

## 双循环与图化简

```text
DialogueRound (外层：用户输入/反馈 -> Goal 修订 -> AgentResponse)
  └─ ExecutionIteration (内层：Plan -> ToolCall -> ToolOutput -> Evaluation)
```

`contains` 只声明作用域，不声明因果；同层先后仍必须使用显式 `precedes`。聚合点只存在于 projection，不会写回 Ledger。每个聚合点保存 `member_ids / internal_edge_ids / cycle_edge_ids`，跨组边保存原始 edge ID、端点和 provenance。未归组节点与边显式列在 `unmapped_node_ids / unmapped_edge_ids`，因此化简不会冒充事实删除。

没有 `UserFeedback` 或父子 `contains` 证据时，Plan fallback 只叫 display/execution span，不声称它就是一次真实用户对话。`accepted` 缺失时，首轮是否成功始终为 unknown。

## 底层能力保留

- canonical node/edge 和稳定 ID；
- append-only Ledger 与 SHA256 receipt；
- `live / reconstructed / synthetic` 真实性边界；
- deterministic lint；
- runtime Ready frontier、Approval scope 和 Checkpoint；
- visual-only replay，不重新执行工具或副作用。

## Graph-native Runtime（最小闭环）

`graph-runtime-0.1` 是 canonical graph 的只读控制面：它不会调用 Tool，也不会把推断写成原生 telemetry。

- 只有 `Run` 作用域内显式标记 `runtime_managed=true` 的 `Action`、`ToolCall`、`Step`、`Verification` 才进入 Runtime。`ToolCall` 可以作为安全的下一步建议，但建议不等于已经调用。
- 所有 `mutating=true` 的可执行节点共享门禁：显式 live Run、Case 处于 execute、scope 匹配的 granted Approval，以及 `targets -> Target` 或 `modifies -> Target/Artifact`。`approved_by` 指向其他节点类型、缺失采集模式或未批准的 ToolCall 都不能通过。
- `acg advise` 汇总 Ready frontier、Claim 的缺失证据和可执行的 `Action`/`ToolCall`；候选到 Claim 的映射只沿已声明的 `produces -> supports/refutes` 关系，找不到作者声明的动作时会明确留空，而不会编造工具调用。
- `Claim` / `RootCause` 的确认 gate 默认至少需要一条来自已完成、非 derived 证据节点的显式 `supports` 边；derived `supports` 关系也不能开启 gate。Claim、证据和支持关系必须唯一属于同一 `Run`（或三者均为 global），不会把其他 Run、global 或多 Run 证据自动借来确认。可在 Claim attrs 中加 `minimum_support_count`、`required_evidence_ids`、`required_evidence_types`、`required_capture_modes` 收紧条件；`refutes` 证据会阻止确认。`acg claim-status --status confirmed` 会执行此 gate，并在未传 `--run-id` 时只推断 Claim 的唯一 Run owner。
- `acg record-recommendation` 把当时的建议快照 append 为 `Decision`，其中 `data_origin=derived`、`not_native_telemetry=true`、输入 Ledger SHA256、候选 ID 和 gate 摘要都会保留。之后的实际路径只从 Ledger 的后续 runtime node records 提取。
- `acg review-paths` 使用 Ledger `sequence` 比较已记录的建议与实际 runtime records；比较本身也是 derived，绝不重放工具或补全缺失操作。
- 历史复用需要显式相同的 `attrs.reuse_key`（或 `reuse_keys`），不会按 label 相似度猜测。只有 Case 已关闭/完成，且**同一历史 Run**有非 derived 的 `VerificationReceipt`，才标记为 verified success path；`reconstructed` 或 `synthetic` 历史始终只是 advisory template，不能充当当前 live Run 的执行证明。

例如：

```bash
acg advise current-events.jsonl --run-id run:CASE:001 \
  --history-ledger known-good-case.jsonl
acg record-recommendation --ledger current-events.jsonl --run-id run:CASE:001
acg claim-status --ledger current-events.jsonl --claim-id claim:root-cause --status confirmed
acg review-paths current-events.jsonl
```

`project` 还会生成 `runtime-advice.json`。这是当前图状态的可再建派生物；它不替代 Ledger，也不证明动作实际发生过。

`step-status`、`claim-status` 和 `record-recommendation` 在追加前，会在 Ledger 锁内检查输入快照的 sequence 与 SHA256。若验证后其他写入改变了 Ledger，命令拒绝提交，调用者需要重新读取并计算；不会自动重用旧授权或旧证据。`step-status` 的 Checkpoint 保留所属 Run 的采集模式，synthetic 演示不会被标记为 live。

证据必须显式填写适合其类型的完成状态，例如 Observation 的 `confirmed`、ToolOutput 的 `completed`、Verification 的 `passed`。缺失、未知、blocked、skipped 状态均不能确认 Claim；历史成功路径也必须有明确完成的 VerificationReceipt。`minimum_support_count` 是正整数，按不同证据节点计数，重复 supports 边不增加证据数量。完整状态表见 [架构说明](docs/architecture.md#evidence-completion-states)。

上下文包提供 `task`、相关节点、目标路径、输入/输出引用、来源记录和哈希，不内嵌完整工具日志。邻接关系复用一次构建的索引。`selected_node_count` 包括任务本身；`node_reduction_ratio` 和兼容字段 `context_reduction_ratio` 都按节点数量计算，`measurement_basis=node_count`，不代表 token 节省或任务成功率提升。

## 从图反推流程

ACG 可以显式记录 `Goal -> Plan -> ToolCall -> ToolOutput -> Claim`：

- `frames`：Goal 为 Plan 提供上下文和边界；
- `informs`：新证据或可见 reasoning summary 改变下一版 Plan；
- `supersedes`：Goal/Plan 的版本修订；
- `invokes / produces / supports`：计划调用工具、工具产生结果、结果支撑结论。

`infer-workflow` 只读取 canonical graph，反推每版 Plan 的 Goal 上下文、动作、产出和结论，并报告缺失的 Goal/Plan/Output/Evidence 关系。它不读取或恢复隐藏 chain-of-thought。

```bash
acg infer-workflow examples/quickstart/events.jsonl --output inferred-workflow.json
```

## 事实与隐私边界

```text
events.jsonl + original artifacts = source of truth
graph.json + trace-model.json + trace.puml + graph.html = rebuildable projections
```

生成的 HTML 内嵌 Trace 数据。公开前必须检查 Ledger、来源引用和生成物，禁止提交客户日志、内部路径、凭证或未脱敏证据。仓库 Quickstart 全部是 synthetic 数据。

## 命令

```text
doctor            检查 Python、schema 和可选 Ledger
init-case         创建 live/synthetic Ledger
validate-ledger   校验 JSONL 与连续 sequence
lint              执行确定性协议检查
project           生成 PlantUML / HTML / JSON / Lint / receipt
next-actions      计算 Ready frontier 与阻塞原因
step-status       追加受门禁保护的 runtime Checkpoint
advise             派生证据缺口、Claim gate 与下一步 Action/ToolCall
record-recommendation  append-only 记录 derived 推荐快照
claim-status       通过 Claim gate 追加确认/阻塞状态
review-paths       对比已记录推荐和后续 Ledger 实际路径
import-issue      只读导入历史 Issue
infer-workflow    仅从 canonical graph 反推 Goal/Plan/Tool/Output/Claim
record-node       追加节点事件
record-edge       追加关系事件
record-state      追加状态变化
```

## 开发验证

```bash
python -m unittest discover -s tests -v
python -m compileall -q agent_case_graph
python -m pip wheel --no-deps --wheel-dir .artifacts/wheel .
```

CI 覆盖 Windows / Ubuntu 的 Python 3.11–3.13，并单独检查浏览器离线页面。浏览器检查使用可选开发依赖，覆盖五个视图、节点与 Trace/详情联动、键盘选择，以及中英文 390×844 窄屏；详情栏在窄屏下移到画布下方。运行方法见 [Contributing](CONTRIBUTING.md#browser-checks)。这些 synthetic 检查验证功能行为，不构成真实 Agent 收益实验。

设计细节见 [architecture.md](docs/architecture.md) 和 [paper visualization notes](docs/runtime-open-source-comparison.md)。

## License

[MIT](LICENSE)
