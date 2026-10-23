# Agent Case Graph

[![tests](https://github.com/znbsf/agent-case-graph/actions/workflows/tests.yml/badge.svg)](https://github.com/znbsf/agent-case-graph/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://www.python.org/)

**Append-only agent ledger → one canonical typed graph → one offline page.**

Agent Case Graph（ACG）把 Agent 处理问题的过程（目标、动作、证据、结论、状态）保存为 append-only JSONL，
再确定性地投影成一张有类型的图，回答：

- 我们知道什么，证据来自哪里？
- 哪个动作现在允许执行，为什么？
- 哪些结论经过验证，哪些仍是 reconstructed / synthetic？

## 数据流

```text
events.jsonl   append-only · live | reconstructed | synthetic
     |
     v
graph.json     稳定 ID · typed nodes/edges · lint · runtime gates
     |
     v
graph.html     自上而下分层图；点击节点看属性、出入边与来源记录
```

页面位置和 Ledger 时间都不会自动成为因果；只有显式 edge 才画成箭头（`contains` 用虚线表示作用域）。

## 快速开始

```bash
git clone https://github.com/znbsf/agent-case-graph.git
cd agent-case-graph
python -m venv .venv
python -m pip install -e .

acg validate-ledger examples/quickstart/events.jsonl
acg lint --strict examples/quickstart/events.jsonl
acg project examples/quickstart/events.jsonl --out-dir examples/quickstart/generated
```

打开 `examples/quickstart/generated/graph.html`。`project` 只输出四个文件：
`graph.json`、`graph.html`、`lint.json`、`projection-receipt.json`（含各文件 SHA256）。
HTML 单文件、无 CDN、有 CSP，可离线打开。PowerShell 用户可以直接运行仓库根目录的 `acg.ps1`。

有业务节点时，Case / Run 默认折叠，可用页面按钮展开；点击详情中的容器链接也会自动展开。折叠只影响显示，不删除节点、关系或来源。回退线从主流程侧面绕行；关系属性中的 `label`、`condition` 或 `条件` 会直接显示在线旁。

## 底层能力保留

- canonical node/edge 和稳定 ID；
- append-only Ledger 与 SHA256 receipt；
- `live / reconstructed / synthetic` 真实性边界；
- deterministic lint；
- runtime Ready frontier、Approval scope 和 Checkpoint。

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
graph.json + graph.html = rebuildable projections
```

生成的 HTML 内嵌全部节点与属性。公开前必须检查 Ledger、来源引用和生成物，禁止提交客户日志、内部路径、凭证或未脱敏证据。仓库 Quickstart 全部是 synthetic 数据。

## 命令

```text
doctor            检查 Python、schema 和可选 Ledger
init-case         创建 live/synthetic Ledger
validate-ledger   校验 JSONL 与连续 sequence
lint              执行确定性协议检查
project           生成 graph.json / graph.html / lint.json / receipt
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

CI 覆盖 Windows / Ubuntu 的 Python 3.11–3.13。设计细节见 [architecture.md](docs/architecture.md)。

## License

[MIT](LICENSE)

## Source-bound project planning

The optional [project-planning plugin](docs/project-planning-plugin.md) provides
bounded repository inspection, exact path or Python-module queries, static
one-hop Python import neighbors, and snapshot-bound pagination. CJS and MJS
checker/build sources participate in source hashes and evidence freshness.

`acg plan-project`, `check-plan`, `record-project-plan`, `run-plan-check` and
`review-project-plan` support proposal → explicit command evidence → revision.
Plans remain proposals: passed checks do not authorize execution or assert
semantic acceptance. Stale sources, disconnected checks and superseded plans
are rejected. Install `.[mcp]` to serve six read-only MCP tools; mutations and
commands remain explicit CLI operations. See the guide for limits and examples.
