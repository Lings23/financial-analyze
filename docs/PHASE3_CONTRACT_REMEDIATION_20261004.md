# Phase 3 输入契约与归因修复（2026-10-04）

用户修改独立评审的 `REMEDIATION_RECOMMENDATIONS.md` 后明确授权执行修复。本轮开发与上一轮 Judge 冻结结果分开；原 68 任务、952 单元、JSON/Markdown、Evidence、snapshot、cutoff 和评分均保留。

## 实现

`research/benchmark_contracts.py` 提供 `benchmark-contract/v1`。正式 Benchmark 冻结前逐绑定执行普通授权/PIT查询、当前 SourceGrant 解析和原 Artifact 哈希校验，再核对完整 snapshot 成员哈希、Provider/Dataset、证券、原时间窗、事件记录及公开时间精度。事件日期精度排除披露日事前收盘、从次日开始事后收盘；15:00 +08:00 晚于 cutoff 的收盘不可用。同比基数和严格日期对齐规则不改变。

缺可信元数据为 not_assessable，不算合法；非法或未知 Case 拦截整批冻结，不过滤困难样本。`scripts/phase3_benchmark_gate.py` 的 `freeze_benchmark` 必须接受可信 `source_context`，写入前重新授权预检，不能凭调用方传入的 `valid=True` 或旧预检结果冻结。followup/v3、baseline quality、archive projection 和 enriched 的正式 manifest builder 均接入门禁；历史 audit/replay 仍能读取旧非法请求用于回归，不能把它们冻结为新的能力评测题。

合法来源实际缺可见数据，以及可检查的非正基数、同合法窗口内实际日期不齐，属于数据或前置条件限制，不据此删除能力分母。若必要报告期根本在请求窗口外、两个必需窗口不相交、事件未定义或 Dataset 来源不兼容，则属于输入契约问题。原窗口/cutoff 在逻辑上不可能完成事件前后观察，单列 intrinsic temporal impossibility，并阻止正式冻结。

空行快照不能仅靠 Provider 名称宣称包含 Dataset。唯一受控例外是可信应用提供原来已授权的零行捕获证明：独立重算完整 requested-response Artifact 哈希，严格核对 Provider 能力、Dataset/API/证券/窗口、业务码、实际空响应、时刻和原 scope/snapshot。无证明仍拒绝。原 000016 的 Tushare 日线空响应证明合法空查询，不能推断停牌原因；四个 CNINFO 行情绑定没有这样的合法证明，仍不兼容。

`single-research-v4` 增加本地 `insufficiency_diagnostics` 与 `study-insufficiency-v1`，记录 Dataset、报告期、事件、来源绑定、非正基数、日期对齐、价格窗口和时间不可行的具体原因及原证据引用。状态、reason、公式、Claim、Evidence 不变；不新增外部读数。Markdown 只在存在新诊断字段时增加展示。v4 恢复核对诊断版本、schema 和重新计算的诊断，停止报告也不得发布伪造诊断。CLI 新运行默认 v4；旧运行须显式选择 v1/v2/v3。StudySpec 的程序默认 v3 保留原脚本兼容，程序调用新诊断需显式 v4。v4 模型 messages、候选与 v3 相同，仍默认模型关闭。

## 实际审计与双口径

先依据完整原始来源冻结契约判定，再连接上一轮独立 Judge 的原任务成功结果；不把 Agent 结论用作输入合法性依据。

| 组别 | Benchmark 合法 | 合法输入下任务成功 | 原冻结端到端成功 |
|---|---:|---:|---:|
| L3，真实模型组 | 12/37 | 12/12 | 12/37 |
| L3，新 cutoff、模型关闭补充组 | 0/25 | 0/0，not_assessable | 0/25 |
| L3，描述性合并 | 12/62 | 12/12 | 12/62 |
| L5 | 2/6 | 2/2 | 2/6 |

总合法 14/68，非法 54/68，合法性未知 0。四类任务级归因允许重叠：原 Research Agent 实现缺陷 0、Benchmark/请求契约问题 54、已绑定来源数据不足 3、前置条件/时间不可行 16。原评审的数据不足 31 等历史分类仍保留；新的四类是在请求层重新区分“根本未绑定 Dataset”和“合法已绑定查询无数据”，不修改旧完成率。

门禁检出 50 次缺事件、75 次缺必需 Dataset 绑定、4 次 CNINFO 行情来源不兼容、12 次非正基数、3 次时间不可能、1 次实际日期不齐；另 000016 两次有原始零行证明、1 个时间可行的旧事件仍缺前后行情。原因次数和任务数不同；不可相加作为任务分母。

必需检验完成率单列为 128/272，全部必需检验完成任务 14/68；不是复制端到端指标。原冻结来源 ESR 952/952、幻觉 0/952、关键锚点 2/56 保持。合法子集来自开发/回归材料，数量小且非盲样，100% 不能宣布广泛能力认证。Phase 3 原完整验收仍未达到。

## 官方版本对应

688184 与 920489 的四项 2024H1 差异在已冻结 2025H1 官方全文中有明确调整前后表和版本说明。原 Provider 值对应调整前：前者为差错更正，后者为同一控制合并的比较期重述。此前独立 oracle 漏抽取版本桥，本次保存独立新 annotation。原 254/674 可评估与 420 未知保持；新对应版本覆盖为 260/674，414 未知。未认证双方最新重述口径的可比性，未倒填 Provider 历史可用时刻。

公共官方 PDF 网络补取尝试两次均连接拒绝，新增 PDF 0；补证依据为已有冻结原文，不能称为网络补采成功。没有新增金融 Provider 或生成模型调用。

## 验证和重算

- 最终全套离线单测 282 项：269 通过、13 PostgreSQL 测试因未启用隔离数据库跳过。55 项新增单测是机制 fixture，不是金融真值；包含正式Builder在任何新Agent执行前保存整批预检并拒绝非法请求。
- 原 68 请求分别用显式 v3/v4 离线重建，facts/hypotheses/event_anchor 全部等于原冻结 payload；136 次完成回放和 68 次撤权拒绝通过。另进程重新载入同一持久运行，136 次原报告 digest 精确回放、68 次撤权拒绝通过。非法请求仅作实现回归，不作新的能力试验或重评分。
- 契约审计 JSON、双口径指标、逐案归因在另进程重算逐字节相同。整套 68 个非法/合法混合请求尝试新冻结被拒，未生成部分 manifest。
- 原 3,886 Artifact 文件与独立 Judge 60 个未授权变更文件哈希未变；用户已编辑的建议文件作为本轮授权输入单独固定 SHA。原 68/952 分母保持。
- 官方版本 oracle 的四个最终 JSON 另进程复算逐字节相同，原 87 个审计输入哈希未变。
- compileall、pip check 和 research CLI help 通过；帮助明确显示v4与旧版本恢复选项。未重跑隔离PostgreSQL，不把跳过记为通过。

复算均使用新输出目录，不覆盖历史结果：

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/phase3_contract_audit.py --output .artifacts/phase3/contract-audit-new
.\.venv\Scripts\python.exe scripts/verify_phase3_contract_remediation.py --output .artifacts/phase3/contract-remediation-20261004/verification-new
.\.venv\Scripts\python.exe scripts/replay_phase3_contract_diagnostics.py --resume-from .artifacts/phase3/contract-remediation-20261004/diagnostic-replays-final --output .artifacts/phase3/contract-remediation-20261004/replay-new
```

完整产物在 `.artifacts/phase3/contract-remediation-20261004/`。`audit-verified`、`diagnostic-replays-final`、`diagnostic-replays-fresh-process` 和官方 `final-*` 为最终结果；`audit-first/audit-final` 是早期归因诊断，`diagnostic-replays` 是一次新验证脚本相对路径错误留下的单份输出，均保留但不作为最终结论。

## 剩余条件

当前 14 个合法原请求没有未完成必需检验，不需要为其追加当前数据。另 54 个原题不能靠修改 Agent 来完成，原失败永久保留。下一版需由研究任务明确事件与版本，绑定具备 Dataset/空响应证明的来源，固定可行的前后窗口、cutoff、PIT 及评价分母，然后通过门禁再冻结。不得任意代选事件。

非正基数、缺价、严格日期不齐若业务仍需研究，应另定版本化问题（例如利润绝对变化/亏损变化、无价格结果、预先约定对齐规则），不能改旧规则。本文只登记这些后续设计条件，没有擅自实施新金融算子或建立更容易通过的替代测试集。414 项外部官方对应仍需取得可追溯原文/版本桥，未取得前继续 not_assessable。
