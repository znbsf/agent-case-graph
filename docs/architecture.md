# Agent Case Graph MVP Architecture

## 1. Product statement

Agent Case Graph 是一个以 `Case` 为聚合根、以 append-only `Event` 为事实记录、以
`Evidence -> Claim` 为推理溯源、以 `Approval -> Action -> Verification` 为状态变更边界、
以 `Pattern -> SkillVersion -> EvalCase` 为知识晋升链的图协议和本地工具。runtime-0.1
进一步把显式 `precedes / blocked_by / approved_by` 关系编译为 Agent 的 Ready frontier。

## 2. Three graph families

### Definition Graph

描述“允许怎样处理问题”：Workflow、StepDefinition、Agent、Skill、Tool、Policy、Verifier。

### Run Graph

描述“这一次实际发生什么”：Case、Run、Step、Artifact、Action、Approval、Verification、Event。

### Knowledge Graph

描述“从多个 Case 学到了什么”：Claim、RootCause、Pattern、Runbook、SkillVersion、EvalCase。

它们共享稳定 ID，但由不同 Projection 展示，避免一张总图变成无法阅读的蜘蛛网。

## 3. Node model

MVP 支持以下节点类型：

```text
Graph
ProblemType
Case
Goal
AcceptanceCriterion
Run
Step
Actor
Capability
Agent
Skill
Tool
Target
EnvironmentSnapshot
Artifact
Observation
Claim
RootCause
Decision
Uncertainty
ScopeBoundary
Action
Approval
Policy
Verification
VerificationReceipt
Pattern
Runbook
SkillVersion
EvalCase
DriftFinding
ExternalIssue
```

建成节点的判断标准：需要独立引用、版本化、授权、验证、复用，或者拥有独立生命周期。
时间、置信度、Git SHA、平台、Hash 等通常是属性。

## 4. Edge model

MVP 支持带方向和语义的边：

```text
instance_of
contains
has_run
targets
runs_in
uses
invokes
precedes
produces
derived_from
supports
refutes
explains
approved_by
guarded_by
modifies
checks
verified_by
satisfies
blocked_by
retry_of
regression_of
generalizes_to
implemented_by
tested_by
supersedes
deprecated_by
references
```

## 5. Event sourcing

Ledger 只追加四种基础事件：

```text
graph.declared
node.recorded
edge.recorded
state.changed
```

领域语义位于 node/edge type 中，基础事件保持稳定。事件必须包含：

```text
schema_version
event_id
case_id
sequence
occurred_at
kind
actor
provenance.capture_mode = live | reconstructed | synthetic
```

状态变化不覆盖旧值；当前状态由 `state.changed` 历史投影得到。

## 6. Case lifecycle

```text
intake -> observe -> analyze -> plan -> authorize -> execute -> verify -> close
                                |                         |
                                +---- blocked <-----------+

close -> promote | reopen | regress
```

MVP 只允许协议中声明的状态转换。失败 Run 和被反驳 Claim 不删除。

## 7. Evidence semantics

```text
Artifact      原始文件、输出、日志、代码、DB、测试结果
Observation   从 Artifact 直接提取的事实
Claim         人或 Agent 提出的解释
```

`confidence` 只描述推理者信心，不代表真实性。确认状态还必须考虑：

```text
support / refutation
freshness
scope
independent verification
source provenance
```

## 8. Bootstrap levels

### Level 0: Seed

用手工 JSONL 记录用户授权、目标、完成标准和计划。这是唯一的人工 Seed。

### Level 1: Self projection

Projector 读取 Seed Ledger，生成自身的 graph.json、Mermaid 和 HTML。

### Level 2: Self recording

CLI 用 append-only 命令记录实现、测试和验证事件。

### Level 3: Historical reconstruction

Importer 只读导入一个真实 Case；所有事后重建事件标记为 reconstructed。

### Level 4: Live dogfooding

后续新 Case 从 intake 开始实时写入 Ledger。

## 9. MVP deterministic lint

至少检查：

1. Root node 缺失或不是 Case。
2. Edge 引用不存在的节点。
3. Case 没有 Run。
4. confirmed Claim 没有 supports 证据。
5. mutating Action 没有 Approval。
6. completed/closed Case 没有 VerificationReceipt。
7. Artifact 缺少来源、SHA256 或 capture mode。
8. 非法 Case 状态转换。
9. SkillVersion 没有来源 Pattern 或 EvalCase。

## 10. Historical importer boundary

Importer 第一版只读取指定 Issue 目录中的：

```text
README.md
EVIDENCE.md
MANIFEST.md
MANIFEST.json
```

它不会递归扫描整个 workspace，不会读取任意附件，也不会改写输入。输出路径必须显式指定。

## 11. Projection views

- Orthogonal Planes：在 `x/y/z >= 0` 的第一卦限三面角中斜向展示 `XY = Knowledge`、`XZ = Control`、`YZ = Execution`；X/Y/Z 三条正向共享轴分别表达 Knowledge-Control、Execution-Knowledge、Control-Execution 接口。
- Parallel Layers：Knowledge、Control、Execution 是三张平行投影面；同一 canonical node 可以有多个显示实例，但共享同一个 source ID 与选中状态。
- Single-layer Projection：从任一主视图切换到 Knowledge、Control 或 Execution，正视该层并展开节点细节。
- Unified Drawer：节点属性、直接关系、来源、原始 JSON、事件时间线和 Lint 共用一个侧栏，不再形成独立主页面。

`spatial-0.1` 是 Projector 生成的确定性语义目录，包括 layer membership、三组 pairwise interface、所选 runtime instance，以及 canonical relation 的 `flow_kind / actual / animated`。它不保存坐标、相机或避让结果。两个主视图是同一目录的不同投影，不是两份事实。

空间图只绘制显式 canonical edge。`first_sequence` 只能用于稳定排序与布局，不能被解释成因果；移动粒子也只叠加在所选 Run 的显式关系上。历史图没有 runtime catalog 时，Execution membership、instance 和动态执行流保持为空，并显示缺失边界。

HTML 使用内嵌数据和原生 JavaScript，不依赖 CDN；JSON 和 Mermaid 用于审查与版本比较。

### 11.1 Visual replay catalog

Projector 从同一份 canonical graph 与原始 Ledger 派生 `replay-0.1`。它不新增事实，也不调用 executor：

- `actual.frames` 只按 Ledger `sequence` 排序；墙上时间只显示，不参与因果排序。
- 连续 `node.recorded` 的状态变化可以从前一事件推断，但必须标记为 inferred。
- `capture_mode=live/reconstructed/synthetic` 的证据边界必须随轨迹显示。
- `visual_only=true` 且 `reexecutes_actions=false` 是协议级安全边界。

`retrospective` 只在所选 Run 的 runtime-managed `Step / Action / Verification` 子图上工作，并且只接受显式 `precedes`。无环时输出稳定拓扑顺序；有环时拒绝生成。当前没有声明成本函数，也没有证明候选图完备，因此固定输出 `optimality=not_proven`，只能称为“复盘推荐路径”。实际记录与复盘推荐各自保留独立游标，不能相互改写。

## 12. Runtime control plane

### 12.1 三层分离

```text
Knowledge / Provenance Graph
  Case、Evidence、Claim、Decision、Action、Verification
                       |
                       | 显式选择 runtime_managed 节点
                       v
Control Graph
  Run contains Step/Action/Verification + precedes/blocked_by/approved_by
                       |
                       | next-actions / step-status
                       v
Execution Overlay
  pending/ready/running/blocked/completed/failed + checkpoint event
```

展示层只能投影以上数据，不能自行决定节点是否 Ready。历史 Action 默认不是执行任务；只有
`attrs.runtime_managed=true` 且被 Run `contains` 的 `Step / Action / Verification` 进入控制图。

### 12.2 Ready frontier

Runtime 只使用显式关系，不从 label、DOM 布局或 `first_sequence` 猜测依赖：

1. `precedes: A -> B` 表示 A 成功后 B 才可能 Ready。
2. `blocked_by: A -> X` 表示 X 未解决时 A 被阻塞。
3. mutating Action 必须有 `targets/modifies`、scope 覆盖的 granted Approval、live Run，并且 Case 当前处于 `execute`。
4. `precedes` 有环时整个 Run 标记为 invalid，不选择下一节点。
5. 多个 Ready 节点按 `(priority, first_sequence, node_id)` 稳定排序；这只是选择优先级，不是伪造因果。

### 12.3 Context packet

Ready 节点不会接收整张 Case 图。Runtime 只选取：

- Case 与当前 Run；
- 直接 `targets / uses / invokes / approved_by / guarded_by / checks / satisfies` 邻居；
- 显式前置节点及其 `produces` 输出；
- Run 级目标和引用。

输出同时报告 `selected_node_count / full_graph_node_count`，使上下文裁剪可以被测量。原始
payload 继续通过 Artifact/source ref 引用，不能直接塞到边或上下文包中。

### 12.4 Checkpoint boundary

`step-status` 是 runtime-0.1 的持久化门：

```text
Ready -> Running -> Completed | Failed
```

Running 之前重新计算所有图门禁；Completed/Failed 只能从 active 状态写入。状态仍通过
append-only `node.recorded` 事件保存，Checkpoint ID 绑定事件序号，因此崩溃后可由 Ledger
重建当前 frontier。

runtime-0.1 不自动执行任意命令，也没有并发 lease、条件边、join、retry、执行级 replay 或 fork。
这些能力必须在明确 executor contract、幂等键、超时、输出上限、权限和副作用恢复协议后增加。
现有 `replay-0.1` 只读回放 Ledger 的视觉状态；它不能、也不会重放 mutating Action。
