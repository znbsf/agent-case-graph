# agent_graph 阶段计划：检查回执恢复

基线：2026-10-01，远端与干净本地 main 均为 a3ab69b674705760a9b62e9cd00c130f53c5b686。原目录 78 文件、index、分支和 HEAD 保留，本轮在独立 worktree/branch 进行。初始可用内存 20.95 GiB，使用轻量 Python/CLI/MCP 验证，不运行 Android、GPU、浏览器或设备负载。

## 已有证据与目标

规划、查询分页、CJS/MJS 时效、显式检查、修订、MCP 只读审阅及 step-status 审批/来源/写入时效均已合入 main，不重写。tests/test_project_session.py 的 test_concurrent_edit_after_command_keeps_receipt_without_replaying 已证明：命令执行后若 ledger 并发追加，回执文件保留，CLI 拒绝落账，审阅仍为 missing_evidence。当前没有回执恢复命令。

本轮只闭合这一里程碑：已授权、已经执行的检查可通过显式 CLI 对账恢复，并由现有 MCP 审阅看见证据。恢复不执行命令、不签发审批、不自动标记语义验收或任务完成；MCP 保持现有六个只读工具。

## 实施顺序与验收

1. 新回执保存稳定检查 ID、Case/Run/Plan/ledger 绑定、提案摘要及检查前 ledger 字节锚点；冲突提示返回回执路径及原 SHA-256。旧回执仍可审阅，缺少绑定的旧孤立回执拒绝自动导入。
2. 新 CLI recover-plan-check 接收明确路径与操作者保留的原回执 SHA-256，校验有界 JSON、输出摘要、身份、路径、原 ledger 前缀和完整关联；复用现有原子批写与时效保护。重复恢复不重复落账。
3. 证明实际检查只执行一次：并发追加导致孤立回执 → 恢复 → CLI/MCP 审阅；重复恢复字节不变；最新失败、过期/损坏证据不得被旧成功覆盖；跨 Case/Run/Plan/ledger、非法路径、格式/字节超限、并发重写和重复 ID 全部安全拒绝。
4. 定向回归及当前 main 完整套件、可选 SDK/真实 stdio、公开示例及 wheel 按影响验证；保存失败和最终记录。PR 精确源 SHA 检查通过后普通 merge 到 main，再核对远端 SHA、合并后 CI 及原 78 文件/index。

## 人工边界与后续

本轮实现、隔离测试与已授权发布可无人值守。实际业务标准是否被命令覆盖仍需明确验收主体；提案到获批执行任务的转换、MCP 写入口或自动执行器属于后续产品决策，不阻塞本轮恢复工程。授权拒绝、真实需登录/设备操作或额度不足时立即报告精确阻塞；重置卡由父任务协调，不并行重复消耗。最终测试通过与已发布分别记录，只有远端 SHA/CI 确认后才记录发布完成。
