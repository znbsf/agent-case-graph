# 工作台：结构依据与验证边界

目标是让人先看清阶段和结果，再沿具体关系检查来源。`workbench.html` 是只读投影，不是新的执行日志或实验报告。论文支撑设计原则；本项目的分组规则和交互实现仍须单独验证。

## 设计与原文对应

| 设计问题 | 原始研究依据 | 本项目实现 | 不能据此声称 |
| --- | --- | --- | --- |
| 全图、局部、详情如何分工 | Shneiderman, *The Eyes Have It*, IEEE Visual Languages 1996：overview、zoom/filter、details-on-demand、relate、history 等任务。[原文](https://hci.stanford.edu/courses/cs448b/papers/shneiderman96eyes.pdf) | 阶段总览 → 局部关系；搜索与单跳聚焦；可关闭详情；真实缩放、滚动和平移；URL 定位 | 该原则证明本界面更快、更易懂，或已完成用户实验 |
| 如何从图回到执行记录 | Gao et al., *Graph of Trace*, ACL 2026 System Demonstrations，§3.4–3.5、§4：声明依赖、节点元数据与记录联动；§8 将大图语义分组、折叠和渐进展开列为限制。[原文](https://aclanthology.org/2026.acl-demo.29/) | 阶段只作为展示分组；节点详情显示来源；聚合边可展开到每条原始边；原始记录独立分页 | 论文已经实现或验证这里的折叠方案。该文的 5 位专家、7 个案例不能转移成本项目验收 |
| 结论与证据为何分层 | Kim, Miao & Liu, *LEDGER*, arXiv:2608.18398 **v1 预印本**，§3.1–3.3：Trace Records / Evidence / Workflow；高层表达是解释而非原始记录。[原文](https://arxiv.org/html/2608.18398v1) | 保留动作、输出、检查、结论与 supports/refutes 等类型；证据链可查反证和原始字段；状态显示为“源状态” | 预印本等于同行评审；支持关系自动证明结论为真；历史报告等于本次实测 |
| 布局如何不改写关系 | Gansner et al., *A Technique for Drawing Directed Graphs*, IEEE TSE 1993，§1.1、§1.4、§2.1：布局目标、分层/排序/坐标/布线分工，箭头保持原方向。[原文](https://graphviz.org/documentation/TSE93.pdf) | 局部图自上而下；可变高度卡片；确定性分层和中位数排序；正交路径避让节点；回边仍保留原方向 | 已复现完整 dot/network-simplex 算法；交叉数最优；所有标签均无重叠；已证明可用性提升 |

## 本项目的工程规则

这些是可审计的实现选择，不冒充论文原算法。

1. **展示分组是分区。** 复用阅读模型中的显式执行迭代 / Plan 阶段索引。节点只归入一个展示组；多阶段共有的节点单列“共享节点”，无法归属的单列“未归入阶段”。局部查看允许显示有标记的关联上下文，不把它当成本阶段产物。
2. **聚合边必须有见证。** 只按 `(源组, 目标组, 原关系类型)` 合并已有跨组边，保存 `source_edge_ids`。组内边保存在 `internal_edge_ids`。原始边的方向、类型、状态、来源均不改写。
3. **位置不增加事实。** 全部阶段的排列及角色列只是阅读索引；局部图的分层只决定坐标。回边不删除。`precedes` 仍是顺序，不升级为因果；共用节点不会自动产生新边。
4. **压缩展示，不压缩证据。** 默认收起详情与原始记录；结构边和总览证据边可筛选，计数明确显示当前未展示的关系。源标题完整换行，未从 PASS 等词推断成功。
5. **证据限制一直可见。** 保留 `live / reconstructed / synthetic` 和已知缺失数量。`reported`、`hypothesis`、`refuted` 等保留原状态。来源链接只在用户点击时导航，页面不自动获取外部资料。

实现：`agent_case_graph/workbench.py`、`agent_case_graph/web/workbench.*`、`agent_case_graph/web/workbench-layout.js`。单文件离线输出可重建；原工作台保留在 `workbench-legacy.html`，用于对照和回归，不是新版入口。

## 可复查的验证

| 检查层 | 可运行入口 | 验证的内容 / 不覆盖的内容 |
| --- | --- | --- |
| 数据结构 | `python -m unittest discover -s tests -v` | 节点分区、边见证、共享节点、反证作用域、原状态不变、安全嵌入；不证明总结语义正确 |
| 纯布局几何 | `node --test tests/workbench-layout.test.cjs` | 可变尺寸、同层并行、回边、自环、确定性、避让；不是浏览器字体测量 |
| 指定案例结构与几何 | `node scripts/check_workbench_geometry.cjs path/to/workbench-model.json` | 原始节点/边无遗漏，见证方向与类型一致；使用合成卡片尺寸，不能充当截图验收 |
| 浏览器交互 | `python -m scripts.check_browser --out-dir .artifacts/browser` | 公共 synthetic 数据：展开、来源、聚焦、缩放、定位、双语、窄屏；需实际运行并查看结果，不以脚本存在冒充通过 |
| 人类可读性 | 尚无研究结果 | 需要真人完成下述任务；当前没有对照实验、任务耗时或正确率结论 |

这一轮已运行的本地结构/几何检查通过；浏览器检查脚本已更新，但受当前会话访问限制，**没有完成新版的真实浏览器视觉验收**。没有发布或获取远程 CI 结果。

建议的人类验收任务：找出一个仍未闭合的问题；从一条结论定位支持与反证的原始记录；指出哪条线仅表示顺序、哪个方框只是展示分组。先检查答案是否准确，再记录定位耗时和误读；不得事后挑选有利样本来宣称提升。

历史重建案例的源材料覆盖率与原实验是否成立是另一个验证层。界面优化不会补齐缺失的对话正文，也不会替代设备侧日志、数值对照或人工审核。
