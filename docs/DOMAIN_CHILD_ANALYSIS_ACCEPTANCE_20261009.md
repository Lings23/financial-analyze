# 领域分析 Child 实施、职责调整与限定验收

2026-10-09 最终交付：工程①–④及限定真实Child闭环完成；原603207正常和688184合法不足的A/B/C最终canonical结果均与原完整oracle等价，6格覆盖6/6。原新窗口评分保留初始4/6、复验1/2；用户另授权688184/B独立一次v4补验，6决策/20074 Token、真实Final后insufficient通过；共9次运行6/9通过，失败未删除。C每例实际域计算2次/4算子、局部Fraction2次、Join重复生产/Fraction0、原完整Final1、独立完整性审计19保留。全部当前58 API请求用量已知139565 Token；A24841/B55656/C59068含失败修正，C较B高6.13%、较更强A高137.78%，无实用收益或有意义自主检查增量证明，保持显式实验及原默认。core1159门禁哈希一致、隔离PG16通过，旧39与新8＋补验1＋前轮3只读回放一致。全历史旧API未知22338＋局部Root4095预留保留，实际总费用未知。详见[最终报告](DOMAIN_CHILD_ANALYSIS_FINAL_REPORT_20261009.md)；没有发布、部署、来源扩张或下一阶段。

2026-10-09 新独立窗口已获明确授权：原2案例/6初始＋最多2有据复验/128父子决策/768000记账Token/首次freeze起2400秒。上轮16:27:09–17:07:09（+08:00）实际外发11次全部已知17900 Token；正常A实际Final完成，B两次非法parallel按no_progress停止，C入口将Financial在途预留误判为terminal unknown，Market未HTTP外发即拒绝，原Root4095预留不释放。修复已离线通过，待启动续验因自动审批usage limit未执行；原窗口已过期。新入口对全部A/B/C统一legal-action-selection/v2，修复在途/terminal区分；传输12＋新入口11离线通过，core保持原1159门禁。保留旧API未知22338＋旧局部Root4095合计26433预留、全部deadline和失败。当前准备新正式freeze，尚无本窗口新paid。详见[验收报告](DOMAIN_CHILD_ANALYSIS_ACCEPTANCE_20261009.md)。

2026-10-09 verification数据续验实际结果：15:49:29冻结、16:29:29绝对截止（+08:00），原两案例、六A/B/C槽及质量标准不变。前三次DeepSeek请求成功，财务/行情/计算已执行并生成7 Fact/12 Evidence；第4次于15:50:13–15:50:34连接失败、用量未知，立即停止新增paid（3/4=75%，无重试）。实际hypotheses/Final未执行，B/C等五槽未启动、复验0，第二轮和goal仍未完成。新known3659/accounted12203/未知8544保留；全历史加独立探针known10090/accounted32428/unknown3，未知预留22338不释放。工程本地门禁保持1159＋隔离PG16、传输8、driver9；只读partial1/1回放无模型/Provider/Checkpoint追加。无真实Child/强基线收益结论，继续保留显式实验模式；详见[验收报告](DOMAIN_CHILD_ANALYSIS_ACCEPTANCE_20261009.md)。

2026-10-09 最新用户授权“直接使用verification中的数据发给deepseek，完成原来第二轮实验”，覆盖此前本实验的停止重试指令。沿用已完成工作包和原两案例A/B/C同题标准；只复用verification绑定的合法不可变源与完整计算输入，通过原授权Tool Observation披露，不把verified元数据当最终执行。旧campaign/续验已过期，旧两个未知请求及13794 Token预留、失败和截止时间保持；同范围续验另冻结新身份、账本与2400秒起点，仍2案例/6初始＋最多2有据修复/128决策/768000记账Token。只显式使用同端点同模型direct-ipv4/v1传输实例，默认和源码身份不变。当前在离线门禁及续验准备，尚未产生新的真实闭环证据。

## 最新停止条件：不再网络重试

用户追加“如果问题仅是网络原因，超过60%的请求通过，就不要再重试了”。本次5次模型派发中4次已知成功（80%）；两业务campaign共6次派发、4次成功（66.7%），均超过60%。当前实际失败为ModelConnectionError，代理无凭据TLS样本亦出现间歇性EOF，未见已执行域算子的业务数值失败。因此已停止进一步paid重试和新campaign，第三重试目录未创建、paid0；此前“重试”授权草案被此最新条件覆盖，原授权字节仍保留。

此门槛只决定是否继续网络重试，不能替代完整业务质量/实际Final/Child/强基线验收。原0/6与续验0/6按各自计划保留，B/C五槽未启动不能当真实质量失败样本。两未知实际用量未核清，13794 Token预留保留；known6431/accounted20225与actual unknown并列。目标未完成、默认不变，不降低任何质量/安全标准。[停止证据](../.artifacts/domain-analysis/bounded-core-v1-renewal-20261009/user-stop-network-retries-20261009.json)。

日期：2026-10-09（Asia/Shanghai）。当前 goal **未完成**：工程通过本地验证；两次独立真实campaign均因模型连接失败/用量未知而停止。续验已正式执行，A仅完成四个Tool，实际Final及B/C未完成，不能判业务闭环或实用收益。默认保持，显式实验模式保留；全部旧账本、失败和期限不改写。

## 新独立续验实际结果（2026-10-09）

正式plan SHA `dd4540ef5d8ef5651550d378b1cdb43d14484804143b226547e4bd1620446e4f`；冻结14:24:43.993369，绝对截止15:04:43.993369（均+08:00）。新身份/账本按明确授权建立，原两案例、A/B/C版本/顺序/业务请求/源/授权/cutoff/oracle/评分、root和局部上限保持。薄驱动只调用原控制器，10项隔离stub检查通过；入口保留原完整预检，每paid护栏只核冻结哈希/授权/账本/时钟，不重复领域oracle。核心源/脚本/测试与1159完整gate一致，fresh39历史回放0追加；没有把旧测试伪称重新执行。

实际只启动603207/A：前4次真实模型返回严格合法的financial、market、calculation、hypotheses动作并成功执行，产生7 Fact/12 Evidence。第5次14:25:56.977053至14:26:01.997253出现`ModelConnectionError`、约5020ms、无响应ID/用量；停止新增paid，余5槽未启动，修复0，重发0，新增金融Provider0。

| 资源项 | 本次续验 |
|---|---:|
| 模型派发/已知/未知 | 5 / 4 / 1 |
| 已知 input/output/total Token | 6303 / 114 / 6417 |
| 未知预留保持 | 8970 Token |
| Root保守记账 | 15387 Token |
| 累计派发预留（非实际费用） | 33328 Token |
| Runtime /整体measured wall | 17547 /17797 ms |
| 整体prep /后验 | 125 /125 ms |
| 完整模型I/O区间并集 | 11100 ms |
| 四个已知transport合计 | 6079 ms |
| Source financial/market Tool spans | 108 /123 ms |
| Calculation/Hypotheses Tool spans | 313 /256 ms |
| 纯Parent composition/remaining checks | 16 /0 ms（毫秒舍入） |
| 完整integrity审计 | 9次/31ms |
| 实际Final verification /Child /Join | 0 /0 /0 |

Report中`verification.status=verified`来自完整integrity审计；`required_checks.verification=not_completed`、`root_full_execution.calls=0`、status=`partial`、stop=`model_call_failed_no_replay`。这证明实际Final门槛未被自动审计替代，**不能把已核对数值当成真实闭环通过**。Root5决策/4工具/15387记账仍在数值上限内，质量rubric的root_budget_passed=false来自unknown未结算，不是额度超限。

新的partial只读回放1/1一致，Model/Provider/Checkpoint追加均0。六个事前固定的无凭据代理CONNECT/TLS样本有一个5016ms后`SSLEOFError`，另五成功（31/47/1062/3047/31ms），支持代理路径间歇性中断；不能确定模型第5次的具体内部阶段或证明未收费。未重放unknown或发送金融数据。

两业务campaign加独立14 Token探测合计：**已知6431 Token、保守记账20225 Token、2次unknown、未知预留共13794 Token**；actual总Token及货币费用仍unknown。旧0/6与新0/6按各自计划槽保留，分别只有1个实际启动Root，五个未启动不是五个真实模型失败。没有有效B/C或同质量配对，10%效率结论不可评估，Child自主检查/增量价值仍无真实证据。因子/日历/现金流/金额profile继续未验证。嵌套span不重复加wall；wall减模型I/O的差额不能全部称协调，纯协调细分unavailable。

新证据：[冻结plan](../.artifacts/domain-analysis/bounded-core-v1-renewal-20261009/plan.json)、[immutable summary](../.artifacts/domain-analysis/bounded-core-v1-renewal-20261009/live/initial-summary.json)、[完整outcome](../.artifacts/domain-analysis/bounded-core-v1-renewal-20261009/outcome-20261009.json)、[partial零追加回放](../.runtime/domain-analysis-renewal-readonly-replay-20261009.json)、[代理样本](../.runtime/domain-analysis-renewal-nonpaid-proxy-samples-20261009.json)、[driver10项](../.runtime/domain-analysis-renewal-driver-checks-final2-20261009.json)。一次驱动测试脚本缩进错误在任何测试/paid前修正，原8项、9项及错误日志保留，不改断言。正式paid控制器及核心代码在freeze后未修改。

当前解除条件：取得两次unknown请求的权威结果/用量并确认稳定的受控连接；未知Root/预留不重发、不释放、不延长。当前campaign任一unknown停止新增paid的原规则持续生效，不能用复验槽绕过。超过本轮deadline后的进一步paid必须另有明确独立授权和freeze；不自动第三轮、不改默认或推广。

## 连通性更新与同范围续验授权（此前阶段记录）

原campaign截止为2026-10-09 11:19:12.657586（+08:00），现已超过2400秒绝对期限。随后用户确认“暂无权威回执”；原1unknown/4824保守记账Token与预留、5未启动槽继续保留。

独立[DeepSeek检查回执](../.artifacts/connectivity/deepseek-20261009T050215477074Z/receipt.json)于13:02:17完成：请求/返回`deepseek-v4-flash-0731`一致，`OK`，2296ms，输入13/输出1/合计14已知Token，1dispatch/0retry/0fallback。它属于单独授权的连通性检查，不能结算原业务unknown。13:06的[分阶段检查](../.runtime/domain-analysis-connection-stages-20261009T050627.json)确认IPv4 TLS31ms、原代理CONNECT+TLS32ms；13:07的[逐地址检查](../.runtime/domain-analysis-address-diagnostic-20261009T050738.json)显示两个IPv6地址TCP超时、两个IPv4 TLS31/16ms成功。检查不带凭据、不调用模型或金融Provider。旧诊断`direct_tls=TimeoutError`没有拆分TCP/TLS，不足以确定当时是TLS握手超时；当前证据支持IPv6建连等待及串行地址回退，具体路由/防火墙根因尚不确定。

用户已明确回答“授权同范围新campaign”。[授权记录](../.artifacts/domain-analysis/bounded-core-v1-20261009/renewal-authorization-20261009.json)绑定[续验草案](../.artifacts/domain-analysis/bounded-core-v1-20261009/renewal-proposal-20261009.json)、原plan/live哈希及配置endpoint/model；新输出为`bounded-core-v1-renewal-20261009`。仍只有原2案例/6初始＋最多2有据复验、128父子决策/768000记账Token/从新正式freeze计算2400秒，原Root/局部限额、请求/源/grants/cutoff/oracle/profile/版本/顺序/评分均保持。薄驱动调用原验收控制器；新run/账本/绝对deadline不恢复或重发旧unknown，不释放预留，不复用旧额度。新未知也立即停止新增付费。

续验只判新campaign内部同质量配对结果，纳入其中全部失败/修复；整个goal的累计资源同时列旧4824未知记账、新campaign实测及独立14已知Token。旧实际用量仍unknown，不能把它当0或忽略它宣称整个goal累计成本下降。此前文档字节已[独立保留](../.artifacts/domain-analysis/bounded-core-v1-20261009/document-history-before-connectivity-update-20261009/manifest.json)，旧索引对应收口时版本；后续新增记录不会改旧冻结plan/live或测试日志。

## 原campaign分别判定（历史结果保留）

| 判定 | 结果 | 证据边界 |
|---|---|---|
| 工程功能 | 本轮本地验收通过 | Financial/Market 计算、局部检验、可信结果消费、确定性 Tool、串行/并行、预算及恢复 |
| 真实业务闭环 | 未验证、阻塞 | 首个 Parent 请求连接失败且用量未知；Child/Join/Final 未获真实模型闭环 |
| 自主检查选择 | 无本轮真实证据 | 有受限算子组合/顺序选择机制；合成模型动作不能证明 Agent 增量 |
| 相对强基线实用收益 | 不可评估，未证明 | 真实 campaign 中 B/C 未启动，没有同质量 A/B/C Token 或 wall 配对结果 |

## 实装与职责边界

- `domain_operators.py` 复用原 Decimal 算子，分拆 Financial 最新核心值/正基数同比及独立金额 profile、Market 价格/回撤/因子计算；保留旧完整包装、原公式/ID/顺序/缺口。
- `domain_analysis_contracts.py` 提供新 Task/Result/Spec、冻结 operator/check ownership 和明确局部额度；旧 Child v1–v3、Parent v1–v6 及工作区既有改动保留。
- `domain_analysis_protocol.py` 严格 JSON 引用协议与确定性精确模型视图。值、目标、必需检查、缺口和反证保留；完整源及执行审计在程序侧，引用不等于授权或完成。12000 UTF-8 字节超限类型化停止。
- `domain_analysis_execution.py` 是既有 DynamicRuntime/Registry/Executor 的适配器，不是第二个 Runtime。Child 真正执行 read/calculation/domain_review，由独立 Fraction 路径完成局部验证，再从实际工具意图/完成回执生成不可变凭据。
- Parent Validated Join 重授权并核 task/Spec/请求/cutoff/PIT/snapshot/输入 revision、实际 Checkpoint 历史、源/结果哈希、read/calculation/review 回执、ownership 和完整 coverage，**不再调用领域生产或局部 Fraction**。缺失/伪造/失效/不可重建凭据拒绝。
- Parent 通过仅 Runtime 可签发的进程内不可变句柄直接消费结果，生产跨域或未委派项；新 Parent revision 绑定源和域结果 digest。完整原 verifier 保留，模型必须实际选择并成功执行 verification。原完整源重授权与恢复/完整审计仍保留并另计，不宣称全根只有一次算术核验。
- 同一 Root Budget/v3 和固定 DAG 支持两域并行；包装尝试计账，先原子预留并保留 Parent headroom。未知/取消/迟到不导入；恢复不重预留、不重发未知、不重复生成已委派 Claim。

## 资源与入口

| 路线 | Parent 局部上限（决策/工具/Token/秒） | Child | 根上限 |
|---|---|---|---|
| A 普通 Tool | 8/12/48000/240 | 无 | 16/18/96000；原绝对 deadline |
| B 确定性领域 Tool | 8/12/48000/240 | 无模型循环；每域 wrapper+read+calculation+review=4 工具尝试 | 同上 |
| C 分析 Child | 6/8/48000/240 | 每域 5/4/18000/120，depth=1，每域最多一个 | 同上 |

CLI：`research --workflow dynamic --domain-analysis-mode direct|tool|child`；Child 配合 `--domain-analysis-execution serial|parallel`。双域 parallel profile 要求一组原子并行委派；串行入口单独保留。`--preview-model` 零模型/Provider/Checkpoint；真实运行显式 `--with-model --config test_api.txt`，恢复绑定同请求、模式、版本、profile 与原运行。金额 profile 仅事前显式 `profit-amount/v1` 和既有 `profit-change/v1`/`absolute_profit_change` 请求，不能替代同比不足。完整示例见 [README](../README.md)。

## 实际验证

- 完整项目环境命令 `PYTHONPATH=src python -m unittest discover -s tests -v`：**1159 项，1143 通过、16 专用数据库项跳过、0 失败/错误**；unittest 日志时长1398.402秒，进程wall1398.922秒；代码和测试在运行期间 SHA 不变。
- 专用隔离 PostgreSQL **14+2=16 项全部通过**，含新分析 Child/确定性领域 Tool 持久读取、恢复、撤权；仅 localhost 随机端口和临时容器，已回收。合成数据不算供应商联调或金融真值。
- 定向：纯算子18、独立契约/协议/codec21、Runtime9、安全14、CLI4；四份旧全量输出冻结 SHA 一致。实际覆盖完整结果消费、来源/计算调用归因、权限/PIT、遗漏/篡改/协调重哈希、重复无进展、提前 finish、未知、取消、迟到、原子预留和三类 crash/resume。
- 历史 **39/39** 报告一致，模型/Provider/Checkpoint 追加均0，历史成功/失败/评分/分母/原件哈希保持。新唯一已启动 partial 报告 **1/1** 零追加回放一致，5个未启动槽保留。
- 初次 Runtime9项失败、正常 C 视图超限、完整1159项6错误与所有修复日志保留。6错误为同一旧 verifier 回调兼容问题；只对新分析路径传统计参数，未放宽旧断言。工作区既有 v6.2 两个测试 driver 问题仅修版本枚举和合法目录发现游标，16项原分页判据通过。
- 首次 freeze 被 manifest 格式拒绝，未建立 plan 或派发：完整回归的源码/测试 SHA 原先分列；用独立证据文件无损合并为验收所需 manifest，原日志与通过结果不变。

## 离线职责与开销实测（不是实用收益）

现有合法源配合**合成模型动作/用量**实际执行六路径；数值/Claim/Evidence/缺口/反证和原完整 verifier 等价，正常7 Fact/12 Evidence、不足6 Fact/12 Evidence。以下时间含实际本地计算、授权、IO与审计；模型是 stub，不能作为真实 Token、延迟或 Agent 收益。0ms 为毫秒采样舍入，不是零成本。计数表示算子/Verifier 调用次数，不是每个基本加减/分数表达式。

| 案例 | 路线 | 完整本地 wall ms | 最大 wire bytes | 局部 Fraction 次 | Join Fraction 次 | 实际 Final 次 |
|---|---|---:|---:|---:|---:|---:|
| p5-603207 | direct | 656 | 8016 | 0 | 不适用 | 1 |
| p5-603207 | tool | 953 | 11385 | 2 | 不适用 | 1 |
| p5-603207 | child | 5906 | 11737 | 2 | 0 | 1 |
| p5-688184 | tool | 937 | 11146 | 2 | 不适用 | 1 |
| p5-688184 | child | 5735 | 11495 | 2 | 0 | 1 |
| p5-688184 | direct | 656 | 7936 | 0 | 不适用 | 1 |

C 每案例两次领域 calculation 组合调用，合计4个必需算子；Parent 同域生产为0，局部 Fraction 每 Child 1次，Join 0次。603207局部review合计15ms、Join126ms；688184局部review31ms、Join94ms。每例 Root 实际 Final1次，另保留19次完整 integrity audit（C分别156/125ms）。这些审计与重授权/恢复开销不隐藏、不加到已有 wall 后重复求和。A/B 的 source/生产与组合内部工具记录在原 stage JSON，未观测细分项如实为 unavailable。

## 独立真实 campaign、未知结果与阻塞

冻结 plan SHA：`f76c02a3f19325f20727ed4f0593c607388197935c2a6dfeb72fc9b93e83f0bd`；起点 `2026-10-09T02:39:12.657586+00:00`，绝对截止 `2026-10-09T03:19:12.657586+00:00`（UTC，Asia/Shanghai 加8小时）。
事前固定：2个已有非盲案例、6初始槽+最多2有依据复验、128父子决策/768000记账Token/2400秒；同请求、源、grants、cutoff、完整oracle、版本、顺序与评分。主效率指标是整组完整Root Token（含失败/复验）对有效B至少降低10%，并核对有效A/B更强结果；wall为次指标，不事后改目标。

- 实际仅启动603207/A，首个 Parent POST 模型请求约5617ms后返回 `ModelConnectionError`，无可核验响应/request id/用量。**1次未知意图，4824 Token保守记账暨预留保留；已知Token小计0不代表实际成本0。**
- 全局终止新增付费派发，余下5槽未启动；复验槽0使用、重发0、新金融Provider请求0、Child模型0、Join0、实际Final0。6槽原分母和5份阻塞记录保存；不能把5个未启动槽当5次真实模型失败或质量样本。
- 不收费诊断：DNS成功；配置HTTP/HTTPS代理127.0.0.1:17897的TCP可连接；直连TLS超时，原代理路径的无凭据HEAD出现`SSLEOFError`。未发送模型请求、凭据或金融数据。这定位为连接/TLS路径阻塞，不证明首次请求未收费或可退款。
- 当前没有有效同质量A/B/C结果，不能计算收益、P95、统计优势或金额；固定流程/合成动作不是Agent增量证据。因子/日历/现金流与金额profile没有本轮真实案例验证，明确保留未验证。
- **解除条件**：配置端点的网络/TLS路径恢复，并获得首次未知请求的权威回执/用量结论；原未知请求不重发、不释放预留。若仍无法取得回执、或原campaign期限结束，需要用户明确新的独立验收授权/预算与冻结计划，旧失败和未知账本全部保留。本 goal 不能因本地工程完成或外部验收停止而标完成。

## 证据与复现

- [完整回归 gate](../.runtime/domain-analysis-full-final-offline-gate-20261009.json)、[原执行日志](../.runtime/domain-analysis-full-final-offline-20261009.log)、[隔离PG14项](../.runtime/domain-analysis-isolated-postgres-20261009.log)、[隔离PG其余2项](../.runtime/domain-analysis-isolated-postgres-regressions-20261009.log)。
- [39历史回放](../.runtime/domain-analysis-preflight-20261009.json)、[离线阶段原始计数](../.runtime/domain-analysis-stage-mechanisms-20261009.json)、[新partial只读回放](../.runtime/domain-analysis-new-readonly-replay-20261009.json)。
- [冻结plan](../.artifacts/domain-analysis/bounded-core-v1-20261009/plan.json)、[immutable initial summary](../.artifacts/domain-analysis/bounded-core-v1-20261009/live/initial-summary.json)、[实际ledger/paid意图目录](../.artifacts/domain-analysis/bounded-core-v1-20261009/live/dispatch)。
- [DNS/TLS](../.runtime/domain-analysis-readonly-connection-diagnostic-20261009.json)、[本地代理](../.runtime/domain-analysis-local-proxy-diagnostic-20261009.json)、[无凭据HEAD](../.runtime/domain-analysis-head-diagnostic-20261009.json)、[密钥/发行包检查](../.runtime/domain-analysis-secret-distribution-20261009.json)。
- [收口核对](../.runtime/domain-analysis-closeout-precheck-20261009.json)：冻结源码/测试、历史及实际live原件哈希不变，403个文件和80个发行包成员无实际模型密钥匹配，7份文档本地链接有效。另有[本地交付证据索引](../.artifacts/domain-analysis/bounded-core-v1-20261009/local-closeout-20261009.json)，不修改冻结plan或真实账本。

只读复现（不追加模型/Provider/Checkpoint；本campaign未知结果禁止继续live）：

```powershell
$env:PYTHONPATH='src'
& .venv\Scripts\python.exe scripts/domain_analysis_acceptance.py replay --plan-sha256 f76c02a3f19325f20727ed4f0593c607388197935c2a6dfeb72fc9b93e83f0bd
```

本轮不发布、部署、改变默认或进入其他阶段。

## 最新续验：直接发送 verification 绑定数据（2026-10-09）

用户“直接使用verification中的数据发给deepseek，完成原来第二轮实验”授权本次同范围续验，覆盖此前网络停止指令。验证数据索引包括两个原案例的真实源、源版本、PIT/cutoff、授权、完整计算结果、缺口、反证与假设，使用原完整Fraction verifier核对；旧正常A的自动verified仅是完整性审计，其最终动作未完成。没有将oracle注入模型、减少必需输出或用旧verified状态替代新真实执行。源通过原Runtime/Tool Observation披露，不新增金融采集。

新独立记录目录为[verification-continuation](../.artifacts/domain-analysis/verification-continuation-20261009/plan.json)，plan SHA `66921cd176332b86ffa5c31bd8b0daf3332a870f0dffeeb0981dc04a59a2e3fd`。冻结15:49:29.880854、截止16:29:29.880854（+08:00），旧两轮截止与未知paid身份不改。相同2案例/6初始＋至多2有据修复/128决策/768000记账Token/2400秒；Root16/18/96000、各局部额度、12000字节、评分和顺序完全沿用。新模型端点/标识不变，仅本实例显式使用direct-ipv4/v1；无代理、redirect、fallback或自动retry，默认不变。两次transport/driver离线开发失败均保留，最终门禁8/8、9/9通过，原源码1159 gate及39历史回放仍有效，未声称重跑完整测试。

| 实测项 | 本次续验 |
| --- | --- |
| 开始的Root / 冻结槽 / 有据复验 | 1 / 6 / 0；五槽未启动，不能算五次真实模型失败 |
| DeepSeek请求 | 3已知成功 / 4尝试 =75%；第4结果未知，之后付费0 |
| 已完成工具 | financial、market、calculation；7 Fact、12 Evidence |
| hypotheses / Child / Join / 实际Final | 未完成 / 0 / 0 / 0 |
| 已知输入/输出/总Token | 3578 / 81 / 3659 |
| 未知预留 / 保守记账 / 累计派发预留 | 8544 / 12203 / 24358；不是实际总费用 |
| 整体测量 / Runtime / 准备 / 后验核对 | 33297 / 33062 / 141 / 94 ms |
| 模型I/O区间并集 / 已知transport合计 / 未知区间 | 28709 / 7640 / 21048 ms |
| financial / market / calculation Tool | 116 / 104 / 244 ms；内含授权、IO和持久化，不能另加到wall |
| Parent纯生产/组合 / 完整性独立审计 | 1次16ms / 5次46ms |
| 实际完整Final独立验证 | 0次；审计verified不能代替 |
| 纯协调、持久化、授权独立拆分 | 尚不可用，保留null，不把wall减I/O全称协调 |
| 新partial零网络回放 | 1/1相同，模型0/Provider0/Checkpoint追加0 |

第4调用时间15:50:13.228659–15:50:34.276482（+08:00），receipt仅`ModelConnectionError`、没有权威response ID/usage。现有日志不能区分该次DNS/TCP/TLS/HTTP哪一步失败，也不能证明服务未收到或未计费。成功3次不能解除第4未知结果，因此本campaign未知规则已触发；不重发、不释放、不追加付费补跑，也未改低完成标准。字段root_budget_passed=false来自未知未结清，已用4决策/3工具/12203记账并未超过原数值上限。

四项判定分别为：工程功能已实现并有本地回归/隔离数据库证据，但工程完整真实验收未收口；真实业务闭环未通过，原因是本次连接未知及实际Final/hypotheses未完成；Child自主选择没有本次真实证据；对有效B和更强A/B的10%收益未验证。原两轮失败与本次失败均保留，跨全部业务尝试已知7/10=70%，不是业务成功率；加独立14 Token探针，共known10090、accounted32428、unknown3，未知预留22338，实际总Token/货币费用未知。不能排除这些失败来宣称第二轮效率。

[输入与版本索引](../.runtime/domain-analysis-verification-inputs-20261009.json)、[续验授权](../.runtime/domain-analysis-verification-continuation-authorization-20261009.json)、[独立传输8项测试](../.runtime/domain-analysis-direct-ipv4-checks-20261009.final.json)、[续验控制9项测试](../.runtime/domain-analysis-verification-continuation-stub-gate-final3-20261009.json)、[新只读回放](../.runtime/domain-analysis-verification-continuation-replay-20261009.json)、[完整结果/预算](../.artifacts/domain-analysis/verification-continuation-20261009/outcome-20261009.json)均可核对。解除阻塞需要第4未知paid请求的端点侧权威状态/用量结论，并在不重置旧身份/截止/预留的前提下具备合法继续外发授权与额度；现有partial不能计作成功。

显式只读复现（项目环境，PYTHONPATH=src）：

```powershell
$env:PYTHONPATH = 'src'
& .venv/Scripts/python.exe .runtime/domain-analysis-verification-continuation-20261009.py replay --plan-sha256 66921cd176332b86ffa5c31bd8b0daf3332a870f0dffeeb0981dc04a59a2e3fd
```

本次数据外发已实际执行；“完成原来第二轮实验”仍是未达到的目标。保留原Child→可信Join→Composition→Cross-domain checks→完整Final→Finish责任边界；未因连接失败放宽最终verification、额外计算/审核或历史恢复契约。


2026-10-09 16:05（+08:00）新增原因分析：无代理、无密钥探测复现47.94.20.201:443在TCP connect阶段21031ms后Windows10060，TLS未开始；另5次建连后TLS15–46ms、HEAD立即401。与原21048ms失败相符，支持TCP路径间歇性故障，但历史付费具体阶段仍属推断，未知预留不释放。详见[网络故障分析](DOMAIN_CHILD_NETWORK_DIAGNOSIS_20261009.md)。本次0模型/0金融Provider请求，无网络配置和冻结代码修改。


## 最终交付索引

后续明确授权的主窗口及单案例补验现已完成所需六格业务覆盖；原评分、失败、预算及unknown全部保留。完整四项判定、阶段开销、历史费用、版本修订和复现入口见[最终交付报告](DOMAIN_CHILD_ANALYSIS_FINAL_REPORT_20261009.md)。
