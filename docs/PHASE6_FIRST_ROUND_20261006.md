# Phase 6 首轮瓶颈诊断、无损表示优化与有界验收

日期：2026-10-06，Asia/Shanghai。用户明确授权本轮实施与必要外部模型请求，覆盖此前不自动进入Phase6的阶段边界。本轮限定验收已完成：两已有案例四真实运行4/4、零追加只读回放4/4及独立实际审查通过。实际父子Token少4.59%，同状态无损wire净省3414字节；Runtime总耗时约持平，未证实延迟/P95改善。接受显式表示版本，原默认、12000字节与并行启用范围保持。

本轮保留Phase5原8/9、Parent v2同案例复验另列1/1、P45原失败0/1及v2失败0/1/v3复验1/1、全部paid wire、Checkpoint、冻结源码及原分母。不将历史失败用作等质量性能baseline。Phase5三个任务九路线仍是三任务；本轮复用已有案例，独立新任务0，盲样0。

## 事前范围与评分

只优化视图内重复的精确元数据表示，新增显式Parent `dynamic-parent-parallel-v3` 与 `dynamic-context-view/v2`。baseline为Parent v2，两版Child都显式v3。v3保留v2可信revision执行进度，仅对完整重复元数据使用可逆引用；必须回解为旧v1视图全字段完全相同，再按原catalog核验。全部Fact/Claim/Evidence数值、缺口、PIT/cutoff/snapshot/grants/lineage保持；每次读取、披露、复用和恢复继续重授权。

首轮为原Phase5的603207及688184 parallel请求：每题baseline/candidate各一次，共4运行；两题顺序baseline→candidate与candidate→baseline。证券、question、源、oracle、评分、所需执行检查逐字不变。已知归档预检/预热条件、非随机顺序和端点时段变化明确列为混杂；920110仅参与历史诊断，不宣称候选已真实验证。

独立campaign上限96父子决策、576000记账Token、1800秒绝对时限、最多6运行。剩余至多2运行仅在失败后另冻结有证据的同案例最小修复配对，继承原campaign账本/deadline，不盲重试、不提高额度。Parent局部8决策/12工具/48000Token/240秒，Child3/1/18000/120秒，根16/18/96000、depth1、根原子预留与Parent headroom保持。固定12000 UTF-8字节，不开展阈值调参、LLM摘要、有损裁剪、新Provider/Dataset/领域Agent/Router/Runtime/交易/分布式调度。

付费intent先在Runtime及独立campaign落盘；未知结果停止新增外发、不重发、不释放，已在途回执可以收取并保留。不复用旧campaign额度。所有失败保留在原轮分母，修复复验不增加独立任务。

验收必须核对完整事实/Evidence、全部必需执行检查、合法非正基数不足、来源权限/PIT/快照/血缘与预算、实际双Child I/O重叠，并完成零模型/Provider/Checkpoint追加的只读回放。表示收益主要核对每份candidate paid状态在同一scope/run/request/Observation/control下回编baseline的净UTF-8字节差（包括解码说明），要求全批有可证实正收益；不是Token估计。实际配对Token和延迟另报正负，不强制20%Token或15%P95历史候选目标、不由小样本宣称P95或统计优势。默认配置及并行启用范围保持。

## 外发前已执行

- 基线完整离线unittest：794项，780通过、14数据库跳过、0失败；日志`.runtime/phase6-baseline-offline.log`。
- 历史只读兼容审计：19/19报告完全相同，5003历史文件SHA前后保持；模型/Provider/Checkpoint追加0。脚本`scripts/phase6_historical_replay.py`，结果`.runtime/phase6-historical-replay.json`。旧live code-freeze门不冒称与新源码相同；原输入、源授权和Spec恢复逐次核验。

## 真实历史诊断

`.runtime/phase6-diagnosis.json`核验原Phase5与Parent v2复验的86笔真实paid intent/receipt/wire/Context Telemetry、10份SQLite完整性/hashchain及导出报告与持久状态一致。690份该诊断范围内原文件SHA前后相同，诊断模型/Provider/Checkpoint追加0；数据读取权限仍由上述独立Runtime只读回放重查，诊断导出统计本身不授予源权限。

| 历史批次 | 决策 | 已知Token | 记账Token | 派发累计预留 | 根累计含组预留 |
|---|---:|---:|---:|---:|---:|
| Phase5原九路线（3独立case） | 77 | 157821 | 157821 | 610803 | 725019 |
| Parent v2同案例修复复验（独立新任务0） | 9 | 16937 | 16937 | 68893 | 87929 |

两批未知用量和未结算Child均0；累计预留不是实际成本，不能与记账Token混合。模型总耗时包含供应商处理、网络及其服务端排队，客户端不能进一步分解这些成本。原77笔receipt latency合计202188ms、median1390ms、max93922ms；实际I/O区间union196892ms，避免双Child重叠双计。首603207 direct wall107703ms，receipt合计100719ms，其中单次93922ms长响应；不能归因于上下文、缓存，也不能据这一点计算总体加速。v2复验receipt合计10657ms、I/O union9595.567ms、wall19422ms。

普通工具Trace跨度合计约5047ms：financial833.888、market917.877、calculation1175.749、hypotheses1078.469、verification1040.986ms；包括当次授权、读取及验证，verification只有8次（原parallel失败未完成）。AgentTool跨度Financial29832ms/Market31966ms包括Child模型I/O，不与模型时间再加。并行queue/branch/join独立报告，source读取、验权、缓存lookup、Checkpoint写入缺少独立历史span，记未知而非0。工具dedup命中0；Provider缓存命中/冷缓存没有测量，当前归档已预热且金融Provider网络为0，不能据此启用跨主体缓存或削减重授权。

现有Lazy Disclosure在原53份Parent视图累计已省19231字节；现有完整目录反事实压缩已省207420字节，v2复验已有Lazy2374/压缩21062字节，不能算作本轮增益。剩余重复metadata可用新确定性整数symbol与盈利list_table引用精确消除；不新增事实缓存、读复用或新披露策略，不改变授权次数。选择这个局部瓶颈因为可以证明精确无损且不修改端点/模型或安全流程，不声称解决主要网络等待。

v3新编码在原v2五份paid状态上保留request/run/control/事实/证据逐字段完全一致；含全部v3 system说明的净字节差（baseline减candidate）依次为-94、18、300、797、472，总1493/45529=3.28%。首轮增加94字节保留，不声称每轮都减少；这是历史真实状态的零模型反事实，不是新模型Token或实际延迟收益。完整58 Parent/28 Child兼容预检及最终哈希在外发前另封存。

## 执行与交付

外发前最终完整验证：828项离线814通过/14数据库跳过、0失败；专用隔离PostgreSQL828/828、0跳过，临时容器回收；最终历史19/19零模型/Provider/Checkpoint追加回放相同、5003旧文件SHA保持。日志`.runtime/phase6-verified-{offline,postgres}.log`，审计`.runtime/phase6-historical-replay-verified.json`。compileall/pip check/CLI帮助与密钥精确扫描通过；新增34项均合成机制，不能算金融真值或真实Provider。

事前计划SHA `2b80c8622949757194d298155f315bdac23fd2d25da1edd228bd23630edab5e1`；源码封存73文件，source-manifest SHA `e53c9a0ecf90f23e66bc40a5b26f3f02fe480dad2ccc8f77df316a2a95262eb6`，密钥文件0。已冻结两case四run、同请求/源/oracle/评分/顺序、Parent v2/v3/Child v3、独立96/576000/1800预算与最多6运行；prepare没有模型/Provider调用。实际仅执行四运行，未消费余两修复槽位。

首轮完整回归失败原样保留：`.runtime/phase6-final-offline.log`为821项/806通过/1合成闭环失败/14数据库跳过；`.runtime/phase6-final-postgres.log`为821项/817通过/4错误/0跳过。四数据库回归中的错误实际发生在旧Phase5证据SHA审计，原因是同时运行的历史回放持有Windows Run文件锁；后续验证串行执行，未修改锁或历史哈希规则。合成模型Barrier后仅增加20ms有界fixture停留，以确保粗时钟下有可测非零I/O重叠，真实严格重叠判据不放宽；该fixture不代表真实模型或金融真值。最终重跑结果待实际完成后另列，不覆盖失败日志。

随后`.runtime/phase6-accepted-offline.log`完整828项/813通过/1旧P45 v3合成overlap失败/14跳过，PostgreSQL未派发；旧EnvelopeTransport同样仅在首轮Barrier后增加20ms有界fixture停留，未改变任何断言/动作/预算/真实wire。旧夹具单项稳定3/3（`.runtime/phase6-legacy-overlap-stability.log`），新harness四路径稳定3/3、计时完整8/8与独立计时1/1通过。现最终全套离线→隔离PostgreSQL→历史审计串行执行，避免所有进程间旧.lock文件审计冲突；上述历史结果、失败日志、原冻结62/63源码副本均保持。

独立审查发现的付费known响应持久结算失败保护缺口已在外发前修复：任何intent/receipt/interval/settled写失败均停止新外发、保留unknown预留、不重发；已保存回执不覆盖。故障注入证明相同行为。首次诊断及独立审查helper的KeyError、初次codec权限fixture构造错误均记录为开发验证失败，零外部调用/旧证据变化。

新批次观测明确分离Runtime.run边界、harness准备/返回后验证与overall wall；模型transport回执与I/O union分开，工具Trace跨度仍包括内嵌读取/授权，verification工具单列。所有时间定义冻结，不将harness新验证开销冒充Runtime延迟变化。

## 冻结计划的实际四运行

本次使用配置文件原端点与指定`deepseek-v4-flash-0731`，没有重试/模型替换/新金融Provider采集。全部四Parent实际执行parallel→calculation→hypotheses→verification→finish，每Parent5决策，每Financial/Market Child各2决策，各根9决策/7工具。四次真实双Child模型I/O重叠均通过。模型finish(completed)不能改变688184的证据不足；Runtime仍报告insufficient/evidence_insufficient。

| 案例/版本（实际顺序） | 状态/通过 | Fact/Evidence | 已知暨记账Token | Runtime ms | harness验证 ms | overall ms | 最高上下文bytes |
|---|---|---:|---:|---:|---:|---:|---:|
| 603207 baseline v2 | completed/是 | 7/12 | 17397 | 18766 | 219 | 19110 | 11574 |
| 603207 candidate v3 | completed/是 | 7/12 | 16545 | 18219 | 875 | 19219 | 10617 |
| 688184 candidate v3 | insufficient/是 | 6/12 | 16185 | 19110 | 875 | 20125 | 10521 |
| 688184 baseline v2 | insufficient/是 | 6/12 | 16908 | 18547 | 234 | 18890 | 11329 |

603207完整两项同比、价格变化/回撤、原缺口及financial_deterioration unsupported保持；688184合法revenue_yoy、原负净利润金额、nonpositive_base缺口及hypothesis insufficient保持，无net_income_parent_yoy。完整Fact/Claim/Evidence/来源时间/单位/窗口/引用按原source oracle逐字段匹配；四报告20项必需执行检查全部passed，hypothesis检查分别按原规则passed/insufficient。没有用自动报告验数代替verification工具执行。PIT、source grants、不可变snapshot、附件、血缘、局部/根额度均通过。

| 计账口径 | baseline两运行 | candidate两运行 | 全campaign |
|---|---:|---:|---:|
| 父子决策/工具 | 18/14 | 18/14 | 36/28 |
| 已知Token | 34305 | 32730 | 67035 |
| 记账Token | 34305 | 32730 | 67035 |
| 派发累计Token预留 | 138713 | 135203 | 273916 |
| 根累计Token预留（含组分配） | 176785 | 173275 | 350060 |
| 未知用量/未结算Child | 0/0 | 0/0 | 0/0 |

每笔Root及campaign intent先落盘，36笔回执逐wire/局部/root/Telemetry核账；实际36<96、67035<576000、四运行<六运行，均在原绝对deadline及局部限制内。剩余60决策/508965记账Token和两运行未用，不延长deadline、不自动继续、不把旧预算或未用预留当新额度。

## 实际收益与延迟边界

603207已知Token少852（4.90%），688184少723（4.28%），两配对合计少1575/34305=4.59%。这是本批真实父子回执差，非20%历史目标或广泛成本认证；两题已知非盲、模型输出/plan/服务时段与顺序变化没有隔离，不能将它估计为未来平均收益。

两candidate十份paid状态分别在相同request/run/scope/Observation/control/权威checks下回编v2，完整context严格精确回解，含新增148bytes system解释的净节省分别1921与1493，总3414/91889=3.72%。首轮两题都增加94bytes，明确保留。actual paired Parent wire少3510bytes，额外96bytes来自模型control字符串差，不归功codec。回编baseline没有外发模型，不能把它的字节差作为新Token实测；现有Lazy/旧压缩节省不重复计入本轮收益。

| 实测延迟口径 ms（含并行嵌套，不能相加） | 603207 v2/v3 | 688184 v2/v3 |
|---|---:|---:|
| 网络/端点transport receipt之和 | 10453/10766 | 10390/11173 |
| 客户端paid I/O区间并集 | 8515/9811 | 8847/9546 |
| verification实际工具跨度 | 126/121 | 148/148 |
| Financial/Market排队 | 125,219 / 109,211 | 145,243 / 96,204 |
| Runtime准备（来源context/runner） | 125/125 | 109/140 |

Runtime合计37313→37329ms（增加16ms），第一题少547ms、第二题多563ms，没有可证实延迟改善。harness验证合计453→1750ms，candidate多1297ms，包含额外同状态重编/严格回解及审计成本；overall合计38000→39344ms，多1344ms。overall只到postvalidation结束，不含随后summary/hash/manifest写入，不能冒充完整campaign/SLA。各source工具与计算/假设工具跨度保存在各row.latency.tool_spans；Source读/验权/缓存lookup/Checkpoint写入仍没有独立准确span，保持未知，不以残差推测。模型服务端排队与网络不能拆分，双Child并发时间不重复加总。不计算或声称P95改善、统计优势、冷缓存或长期SLA。

## 冻结与只读验收结论

决定为`limited_explicit_lossless_representation_accepted`：只接受已验证的显式metadata表示，不改默认或扩大并行启用范围。原Phase5 8/9与`bounded_opt_in_not_supported`、Parent v2同案例1/1及历史P45 0/1、v2 0/1、v3 1/1和所有分母保持。920110候选尚未实测；本轮两个既有case四run独立新任务0、盲样0，金融真值/Provider实时联调未认证。

新报告4/4逐字段一致只读恢复，模型/Provider/Checkpoint追加0，权限/SourceGrant/PIT/附件继续重查。根实际只读审计核四数据库12run哈希链、36持久model_pending与wire/intent/receipt/Telemetry、四个实际verification、完整源oracle和5003历史SHA，`.runtime/phase6-root-actual-audit.json`通过。独立实际审查另核同一完整证据、只读恢复4/4、73源码副本及当前源码全SHA保持；证据`.runtime/phase6-independent-real-review.json`。根审计首次helper误用不存在的Child字段及独立QA包装假设失败日志保留，仅修QA，无付费/Provider/原证据变化。独立代码审查与持久失败注入见`phase6-code-review-final.json`，不将机器验证称为专家金融真值。

冻结目录`.artifacts/phase6/first-round-20261006`保留plan、source-manifest/73源码、四report/Trace/SQLite、36paid message/intent/receipt及逐次ledger、evaluation/Trace manifest。Dataset SHA `b8ed9e61c6d1f2695df974e80efce7de6af14368ab4b9e17675a642285b30c84`；Trace manifest SHA `34ed3ca9e228e43056e0b6ee9f81e2bc041660b489ad1d57b047f2ea0fa1a4a2`。真实评分不覆写冻结文件，验收决定位于`.runtime/phase6-replay.json`；最终密钥/历史/源码/交付完整性扫描另存，不打包或发布。

## 可复现命令

在仓库根目录PowerShell执行；下列诊断/审计输出用新文件名，以保留原冻结结果。

```powershell
$env:PYTHONPATH = 'src'
& .venv\Scripts\python.exe -m unittest discover -s tests -v
& scripts/test-postgres.ps1 -Image 57c72fd2a128
& .venv\Scripts\python.exe scripts/phase6_evaluate.py --replay --plan-sha256 2b80c8622949757194d298155f315bdac23fd2d25da1edd228bd23630edab5e1
& .venv\Scripts\python.exe scripts/phase6_actual_audit.py --plan-sha256 2b80c8622949757194d298155f315bdac23fd2d25da1edd228bd23630edab5e1 --output .runtime/phase6-root-actual-audit-recheck.json
& .venv\Scripts\python.exe scripts/phase6_diagnose.py --candidate-preflight --output .runtime/phase6-preflight-recheck.json
& .venv\Scripts\python.exe scripts/phase6_historical_replay.py --output .runtime/phase6-historical-replay-recheck.json
& .venv\Scripts\python.exe scripts/phase6_integrity.py --output .runtime/phase6-integrity-recheck.json
```

上述完整回归/历史回放/审计需要串行执行，Windows运行锁文件不能边锁定边跨进程hash审计。已实际执行的一次`--prepare --diagnosis ... --historical-audit ... --wire-preflight ...`与一次带同plan SHA的`--live`命令保存在`phase6-prepare.log`、`phase6-live.log`；冻结目录拒绝重复prepare/live，不重发已付费intent。可复验入口为上面只读命令；任何新付费campaign需另明确冻结并遵守新授权边界。
