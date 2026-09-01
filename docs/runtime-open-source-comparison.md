# Agent 图运行时与展示实现对照

更新日期：2026-08-31

## 结论

ACG 不能只把 Case 事实投影成一张图。要让 Agent 真正借助图完成工作，需要把三类信息分开：

1. **State / Evidence**：输入、当前状态、观察、证据、论断、产物和记忆，回答“现在知道什么”。
2. **Control / Policy**：目标、决策、依赖、授权、门禁和验证规则，回答“为什么这样选、允许做什么”。
3. **Action / Interface**：Agent、Skill、Tool、Target 和 Action，回答“实际由谁通过什么接口做什么”。

Runtime Trace 不是第四个语义层，而是一次 Run 对上述节点的状态、attempt、Checkpoint、输入输出引用和错误覆盖，回答“这次实际走到了哪里”。

前端只消费这三层数据，不承担调度语义。

## 开源实现对照

| 项目 | 运行模型 | 最值得借鉴的部分 | ACG 不直接照搬的部分 |
| --- | --- | --- | --- |
| [LangGraph](https://github.com/langchain-ai/langgraph) | 有状态图、super-step、checkpoint、interrupt、resume/replay | Ready frontier、每个 super-step 持久化、失败后从 checkpoint 恢复、人工修改状态后 fork | 不在 MVP 引入完整 Pregel runtime 或 LangChain 依赖 |
| [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) | typed executor/message、super-step、edge group、checkpoint 与 HITL request | Checkpoint 绑定 graph signature；pending request 可随 checkpoint 恢复；输出和 intermediate output 明确 allow-list | 不在 local-first MVP 引入其服务和模型依赖 |
| [AutoGen GraphFlow](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/graph-flow.html) | Agent 节点组成有向图，支持顺序、并行、条件和循环 | 明确区分 execution graph 与 message graph；只给节点相关上下文可减少幻觉和上下文负担 | GraphFlow 标记为 experimental；[AutoGen 已进入 maintenance mode](https://github.com/microsoft/autogen)，新实现不以它作为基础 |
| [Apache Burr](https://github.com/apache/burr/blob/main/docs/concepts/overview.rst) | Action 读取/写入不可变 State，Transition 决定下一 Action | Action/Transition/State 分离，持久化和 telemetry 通过 hooks 扩展，和模型供应商解耦 | ACG 继续使用 append-only Ledger，不替换为 Burr State API |
| [PocketFlow](https://github.com/the-pocket/PocketFlow) | Node + action-labeled edge + shared state | `prep -> exec -> post` 的最小节点生命周期，适合定义轻量 executor contract | 其核心没有 ACG 所需的证据、授权、Checkpoint 和审计边界 |
| [Dify](https://github.com/langgenius/dify) | 队列式 Graph Engine、节点/图事件、暂停恢复与持久化层 | 控制命令、运行事件、持久化层分离；单节点运行和局部恢复 | 不复制其完整服务/队列基础设施 |
| [Flowise AgentFlow V2](https://github.com/FlowiseAI/FlowiseDocs/blob/main/en/using-flowise/agentflowv2.md) | 显式节点依赖、Execution Queue、Flow State、HITL 和 SSE | 图连接决定控制顺序，输出引用和共享状态分开；循环、子 Flow 和人工确认有明确节点 | 不把可视化编辑器当作事实源或运行时 |

LangGraph 的 checkpoint 文档进一步区分完整的 super-step checkpoint 与节点完成后的 pending writes；并说明 replay 会重新执行 checkpoint 之后的节点，包括 LLM、API 和 interrupt。因此 ACG 后续加入 replay 时，带外部副作用的 Action 必须重新经过 dry-run/授权门禁，而不能默认重放。参见 [LangGraph Checkpoints](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/checkpointers.mdx)。

## 展示层参考

| 项目 | 可借鉴模式 |
| --- | --- |
| [React Flow](https://reactflow.dev/learn/concepts/terms-and-definitions) | 自定义 node/edge、端口、子 Flow、选中局部邻域；只用作 UI 基础，不承担运行语义 |
| [Langflow](https://github.com/langflow-ai/langflow) | 组件级 trace、输入/输出/日志详情和逐步调试 |
| [Flowise AgentFlow](https://github.com/FlowiseAI/Flowise/blob/main/packages/agentflow/README.md) | Start、Agent、Condition、Tool、Iteration、Execute Flow 等不同节点契约，以及连接验证 |
| [Dify Workflow](https://github.com/langgenius/dify/blob/main/api/core/app/apps/workflow_app_runner.py) | 单节点执行、variable pool 与同一 GraphRuntimeState；适合局部重跑和状态检查 |
| [Three.js](https://github.com/mrdoob/three.js) | 适合长期实现固定坐标、正交相机和自定义交互；ACG 首版先用原生 SVG 保持单文件、无外部依赖 |
| [3d-force-graph](https://github.com/vasturiano/3d-force-graph) | 适合快速验证空间关系，但力导向结果不够确定，不能用位置暗示 ACG 因果 |
| [deck.gl](https://github.com/visgl/deck.gl) | 大规模节点/边与 GPU 图层有优势；当前 50 级节点规模不需要引入其运行时体积 |

ACG 不把所有职责塞进一张无限扩张的 Canvas，也不为每个模式复制图数据。当前工作台把同一语义目录按用户任务组织成五种模式：

- **Overview**：总览 State / Control / Action 三层闭环与 Case 边界，Runtime Trace 只叠加在原节点上。
- **Plan**：检查显式依赖、阻塞和候选调度；空间图与顺序检查器只在这里出现。
- **Run**：查看 Ready frontier 和当前状态；空状态压缩展示，避免五列挤占画布。
- **Review**：汇总记录边界、运行结论和证据缺口；需要逐帧检查时返回 Plan，而不是复制播放器。
- **Evidence**：枚举 `supports / explains / implemented_by / checks` 形成的所有显式分支路径，检查论证与验收，不按节点类型补造关系。

Plan 再提供两个互补的辅助视图：

- **Dependency Flow**：主画布用显式 `precedes` 解释计划偏序，Runtime 门禁与主要阻塞由同页检查器呈现。
- **Orthogonal Planes**：`XY State / XZ Control / YZ Action`，节点严格在一个面上，跨面关系经共享正轴转接。

四条顺序轨道保持语义分离：Ledger 记录回答“写入顺序”，计划依赖回答“约束顺序”，候选调度回答“可行顺序”，已观测执行回答“executor 实际顺序”。只有最后一条接受 execution telemetry；缺失时显示 unavailable 且不动画。统一详情侧栏承载节点属性、直接关系、来源、raw JSON 与 Lint；逐项顺序检查只在 Plan 中出现。

当前使用原生 SVG + HTML node card，是为了保证生成文件可离线直接打开、坐标确定、文本清晰且没有 CDN。节点规模或动画需求明显增长后，可把同一个 `spatial-0.2` catalog 接到固定版本的本地 Three.js bundle；渲染引擎变化不能改写 canonical graph 或 runtime 语义。公开 Quickstart 的 synthetic runtime 快照只用于展示 frontier 和门禁，不是 execution telemetry，因此已观测执行轨道保持 unavailable。

## ACG runtime-0.1 选择

首个垂直切片不自动执行任意命令，而是提供安全、可验证的控制面：

```text
frontier(run)
  -> 找到显式 runtime_managed 节点
  -> 检查 precedes / blocked_by / approved_by
  -> 输出 ready、running、blocked、completed、failed
  -> 为 Ready 节点生成最小上下文包

step-status(node, running|completed|failed|blocked|skipped)
  -> 校验当前节点是否真的 Ready
  -> 对 mutating Action 再检查 granted Approval
  -> 以 append-only node.recorded 事件写入 Checkpoint
  -> 重新计算下一 Ready frontier
```

实际的 Agent/工具调用仍在 executor adapter 中发生。这样图已经能选择、约束并推进真实 Agent 工作，同时不会在尚无权限模型、幂等协议和回滚策略时直接执行任意副作用。
