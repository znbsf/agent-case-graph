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

## 11. Workspace modes and projections

HTML 工作台用五种任务模式组织同一份事实，而不是生成五份图：

- Overview：汇总 State / Evidence、Control / Policy、Action / Interface 三层闭环与 Case 边界；Runtime Trace 只叠加状态。
- Plan：承载显式依赖图、当前候选调度和顺序检查器。
- Run：只呈现 runtime frontier 与状态，零数量状态压缩为摘要。
- Review：归纳记录边界、运行结论和未闭合缺口；需要逐步检查时跳回 Plan。
- Evidence：枚举 `supports / explains / implemented_by / checks` 形成的所有显式分支路径，审查论证和验收；不按节点类型推断缺失边。

Plan 提供两个辅助视图，它们共享 canonical ID、选中状态和详情侧栏：

- Dependency Flow：主画布只显示显式 `precedes` 偏序，Runtime 门禁与主要阻塞由同页检查器呈现；不从布局或记录顺序推断因果。
- Orthogonal Cuboid：六个面分工而不是共享轴复用。三个相邻节点面是 `z=0: State`、`y=0: Control`、`x=0: Action`；三个相对线路面是 `x=L: State↔Control`（平行于 Action）、`z=L: Control↔Action`（平行于 State）、`y=L: Action↔State`（平行于 Control）。每个节点只属于一个节点面；同层线留在节点面，跨层线进入唯一对应的线路面，并由只改变一个坐标的正交折线连接。

Unified Drawer 统一承载节点属性、直接关系、来源、原始 JSON 和 Lint；Ledger 逐项检查只在 Plan 的顺序检查器中出现，不再为每种模式复制详情卡片或播放器。

`spatial-0.2` 是 Projector 生成的确定性语义目录，包括唯一 `primary_layer`、三组 pairwise interface、所选 runtime overlay，以及 canonical relation 的 `from_layer / to_layer / flow_kind / runtime_touched / animated`。它不保存坐标、相机或避让结果。五种模式和两个 Plan 视图都只是同一目录的不同投影，不是不同事实源。

空间图只绘制显式 canonical edge。`first_sequence` 只能用于稳定排序与布局，不能被解释成因果。Runtime snapshot 只表示当前 frontier，不能自动生成“真实走过”的动画；只有显式 execution telemetry 才能驱动有限的 Runtime Trace。历史图没有 runtime catalog 时，overlay 保持为空，并显示缺失边界。

HTML 使用内嵌数据和原生 JavaScript，不依赖 CDN；JSON 和 Mermaid 用于审查与版本比较。

### 11.1 Sequence inspector catalog

Projector 从同一份 canonical graph 与原始 Ledger 派生 `replay-0.1`。它不新增事实，也不调用 executor：

- Ledger 记录轨道（协议中的 `actual.frames`）只按 Ledger `sequence` 排序；墙上时间只显示，不参与因果排序。它表示记录顺序，不自动升级为 execution telemetry。
- 计划依赖轨道直接来自 runtime-managed 子图和显式 `precedes`，只读展示约束，不设置播放动画。
- 候选调度轨道（协议中的 `retrospective`）只从 runtime 门禁和显式依赖派生稳定拓扑候选。
- 已观测执行轨道只接受明确标记的 execution telemetry；缺失时必须显示 unavailable、禁用播放，并且不得用 Ledger 或 synthetic runtime 状态补造流动动画。
- 连续 `node.recorded` 的状态变化可以从前一事件推断，但必须标记为 inferred。
- `capture_mode=live/reconstructed/synthetic` 的证据边界必须随轨迹显示。
- `visual_only=true` 且 `reexecutes_actions=false` 是协议级安全边界。

`retrospective` 只在所选 Run 的 runtime-managed `Step / Action / Verification` 子图上工作，并且只接受显式 `precedes`。无环时输出稳定拓扑顺序；有环时拒绝生成。当前没有声明成本函数，也没有证明候选图完备，因此固定输出 `optimality=not_proven`，只能称为“候选调度”。计划依赖轨道保持静态只读；Ledger、候选和已观测执行各自保留独立游标，不能相互改写。

公开 Quickstart 的 `capture_mode=synthetic` runtime 快照只演示 frontier、状态叠加与阻塞原因，不是 executor 产生的 execution telemetry；因此已观测执行轨道必须保持 unavailable。

## 12. Runtime control plane

### 12.1 三层分离

```text
State / Evidence Graph
  Case、输入、Observation、Claim、Artifact、VerificationReceipt
                       |
                       | supports / explains / feeds
                       v
Control / Policy Graph
  Goal、Decision、Run、Step、Approval、Policy、Verification + gates
                       |
                       | implements / invokes / targets
                       v
Action / Interface Graph
  Actor、Agent、Capability、Skill、Tool、Target、Action
                       |
                       | produces / observes / verifies
                       +---------------------------> State / Evidence

Runtime Trace Overlay
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
