# Phase 2 固定 Single 首版实施记录

实施日期：2026-10-01；补充联调：2026-10-02（Asia/Shanghai）。用户要求读取 PLAN/STATUS 并执行 Phase 2；按照已确认的“先交付固定计划单股概览”推进。Phase 1 首版验收及原质量缺口保持不变。

## 已交付

`src/stock_research/research/` 包含 AgentSpec/请求契约、ToolRegistry/Executor、确定性计算、固定 Fast Runtime、SQLite Checkpoint 和报告渲染/CLI。六类聚合工具覆盖 Market、Financial、Benchmark、Announcement、News、Calculation；实际请求只运行所需域，最低为行情、利润表和计算三个工具。

执行路径为：严格 manifest → 来源/工具权限 → 固定快照 PIT 读取 → Decimal 计算 → 可选一次 DeepSeek 重点选择 → 数值血缘校验 → Markdown/JSON 报告。没有新框架、自动金融采集、动态代码、交易、Multi 或 Phase 3 因果研究。

模型只能从既有事实中选择最多三个 ID；所有显示数值由确定性事实生成。来源文档及标题不发给模型，文档索引以转义文本展示。失败/超时/错误模型/额外数字/未知 ID/异常用量不能变成 verified；原确定性结果保留为 partial。模型调用前持久化 intent，进程崩溃后不重发结果未知的调用。

每次恢复和完成报告回放均重新校验当前来源/工具授权、快照及全部附件。Checkpoint 为本地追加哈希链和 OS 进程锁，不保存密钥；权限来自可信应用上下文。模型 Token 使用保守 UTF-8 字节预留与实际响应用量两份账本。默认工具尝试上限 8、时间预算 45 秒、Token 预留上限 8000、最多一个模型回合。时间为协作式检查，不保证能立即中断阻塞的本地数据库 I/O；迟到结果拒绝。

## 本次实际测试

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 离线 unittest | 157 项：145 通过、12 PostgreSQL 跳过 | `.runtime/phase2-offline-final.log` |
| 隔离 PostgreSQL unittest | **157/157 通过，0 跳过** | `.runtime/phase2-postgres-final.log` |
| 冻结合成 L1/L2 机制评测 | **20/20 任务、70/70 数值检查、130/130 数值 Claim 血缘** | `.artifacts/phase2/synthetic-evaluation-final.json` |
| 真实既有快照报告 | 601009、5 个数值 Claim、11 个 Evidence、3 次工具调用 | `.artifacts/phase2/real-final/report.json`、`report.md` |
| 独立 Fraction 运算和授权源重读 | 5/5 Claim 与 11 个 Evidence 通过 | `.artifacts/phase2/real-final-check.json` |
| 新进程 Checkpoint 回放 | 请求/报告内容完全相同、模型及金融 Provider 网络调用均为 0 | `.artifacts/phase2/real-replay/report.json` |
| 发行源包检查 | sdist 构建成功，包含 8 个新模块；未包含本地密钥文件、运行数据或模型密钥字节 | `.artifacts/phase2/distribution-check.json` |

运行命令：`PYTHONPATH=src python -m unittest discover -s tests -v`；Windows 等价命令见 README。隔离测试使用 `scripts/test-postgres.ps1 -Image 57c72fd2a128`，只创建/清理临时容器，未删除或重启持久 `stock-research-p17` 数据卷。

新增测试覆盖：固定公式、缺数不填零、同日期基准、缺因子拒算、负同比基数、三表聚合、文档注入隔离、public/system PIT、跨 scope/来源撤销、工具权限、同 wave 重用验哈希、附件篡改、Checkpoint 篡改/锁、预算/取消/迟到、工具中断计费、模型意图后崩溃不重发、非法模型输出、错误模型、截断、Token 未知/不一致/超预算、PostgreSQL 快照与恢复。

合成案例文件为 `evaluation/phase2_cases.json`，SHA-256 `6a4884a359cb0eff6e8f01a8fdea1f215ba2dd9b9d5a30f90ace689cd93eff21`。期望值为预先写入的算术例子，未使用生产计算函数生成答案；模型为 fixture，没有真实模型调用。该结果不能解释成真实金融准确率、正式独立持出集或整体 Agent Success 已达门槛。

构建检查最初尝试 wheel，因本地 `.venv` 缺少 `bdist_wheel` 失败；未为此联网安装依赖，随后 sdist 成功并完成内容检查。wheel 未验证，不宣称已通过。

## 可查看的真实首版效果

- 请求：[`evaluation/phase2_real_601009.json`](../evaluation/phase2_real_601009.json)，固定 system cutoff `2026-10-01T15:25:05.838123+00:00`。
- 报告：[601009 单股研究概览](../.artifacts/phase2/real-final/report.md)。对应 run `2d3e304fdb604f8bad80e177691578a0`。
- 行情请求窗口为 2026-09-15 至 09-25，实际已观察收盘数据截至 **09-24**；报告明确提示请求边界未观察，不把缺行当成零或完整覆盖。
- 财务请求为 2024-12-31 至 2025-06-30；最新可见报告期为 **2025-06-30**。缺同报告期上年基数，未生成同比；不称为当前最新财报。
- 本次只重用已保存的 Tushare 冻结快照，不新增金融 API 采集；`coverage=not_verified`、普通观察数据不具任意历史版本证明、未提供日历等缺口保留。
- 本次真实报告 `model.status=disabled`，不能当作 DeepSeek 已经完成研究的证据。

最终报告规范 JSON 内容 SHA-256 为 `ef29f85eb5fe4255445dbaa8f15cc5d4bd8747d323a7aa2c7da5ecd8f5a7cc31`（canonical JSON 哈希，非文件字节哈希）。独立验证器只验证算术与授权源血缘，沿用 Phase 1 已有数据及其质量边界，不构成新的供应商准确率认证。

## 真实模型联调的原审批阻塞（2026-10-01 历史）

准备执行一次 `--with-model`，仅通过 `test_api.txt` 指定 HTTPS 端点请求 `deepseek-v4-flash-0731`，没有备用模型。自动审批在进程启动前拒绝，理由是：已有 Phase 2/模型接入授权不足以确认将这些具体潜在敏感财务研究事实外发至该端点。该拒绝未被绕过，本次没有实际模型请求、Token 消耗或模型回答。

待发送的完整 messages 已存为 [拟发送内容](../.artifacts/phase2/proposed-model-messages.json)，使用实际 Runtime 的 `model_messages` 生成，并与最终报告核对一致。内容为 5 个既有事实的名称、值、单位、实际窗口，以及只选择已有事实 ID 的系统约束；不含原始公告正文、数据库连接、scope、快照 ID 或凭据。获用户具体外发授权后才继续一次真实调用，并将实际结果追加到此记录和 STATUS。

## 用户批准后的真实联调（2026-10-02）

用户明确回复“批准”，授权上述 5 条事实发送至 `test_api.txt` 配置端点并调用一次指定模型。实际执行在 Transport 发送前逐字比较批准的 messages、检查模型名并限制单次派发；没有修改业务代码或扩大输入。请求保持原冻结快照和 `2026-10-01T15:25:05.838123+00:00` cutoff。

- 一次真实调用成功，请求与返回模型均为 `deepseek-v4-flash-0731`，状态 `verified`，报告状态 `completed`。
- 输入 291 Token，输出 21 Token，合计 312 Token；Token 预留 1504；模型适配器计时 1265 ms。无重试、无备用模型、无新金融 Provider 网络调用。
- 模型选择 `observed_price_change`、`financial_income.net_income_parent`、`financial_income.revenue`，所有显示数值仍来自既有确定性事实。
- 报告：[真实 DeepSeek 联调结果](../.artifacts/phase2/real-deepseek-approved-20261002/report.md)；run `dbc091ed4ca641b2a7178c8c25771572`。
- 本地独立 Fraction 与来源核对：5/5 Claim、11 个 Evidence 通过；与旧报告数值完全一致。发送内容与已批准 JSON 相同。
- 新进程恢复时将 Transport 设置为禁止网络，实际 0 次派发，报告内容完全相同。验证结果 `.artifacts/phase2/real-deepseek-check-20261002.json`，回放 `.artifacts/phase2/real-deepseek-replay-20261002/report.json`。
- 新报告 canonical JSON SHA-256 为 `cbc4181de5a0ecc04f820fb513c2974b8b879b1d1e06eda9b18fb850f3f5761f`。检查 JSON 的 model_network_calls=0 是核对过程的计数，不是这次已实际发生的模型调用计数。

本轮仅执行已授权联调/本地核对并同步文档，未重跑完整 unittest；前述 157/157、20/20 均仍为 2026-10-01 证据。一次成功调用不证明持续延迟、服务可用性或整体 Agent 质量门槛。

## 未完成的整体验收

2026-10-02 后续验收已修复三类模型校验/恢复缺陷，新增五项回归；隔离 162/162、合成 20/20、真实固定任务 50/50、独立算术/Claim 血缘 248/248 通过。固定 Single 首版验收通过；广泛真实模型质量与全局成功率边界继续保留。当前证据见 [验收与修复](PHASE2_ACCEPTANCE_20261002.md)，本文件此前数值保持为历史执行。

固定 Single 首版代码、本地真实报告、机制评测及一次真实 DeepSeek 联调已完成。Phase 2 整体目标仍需更广泛的独立真实 L1/L2 任务集；不能把 20 个合成任务或一次真实调用成功写成整体 ≥95% Success 或真实 ≥99% 计算/数据准确率。

自然语言请求解析、动态 Tool Calling、并行 wave 合并和广泛指标按后续需求扩展；Phase 3 Hypothesis/Research、Phase 4 Multi、交易不在本次范围。
