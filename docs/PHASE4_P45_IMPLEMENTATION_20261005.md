# P4.5 Parallel Multi / M3：实现与独立验收记录

日期：2026-10-05（Asia/Shanghai）。**工程与安全机制回归通过；完整P4.5功能验收未通过，不进入Phase 5。** 新冻结600500真实任务0/1：两领域真实模型派发重叠，Market完成，Financial重复已完成读取并触发no_progress，Parent保留partial。以下合成测试不作为金融真值或真实闭环替代品。

## Implementation

先完整核对PLAN、ARCHITECTURE、CONSTRAINTS、STATUS、P4.3/P4.4实施及Context Remediation记录，再检查实际DynamicRuntime、AgentSpec、Registry/Executor、root-budget/v1/v2、Checkpoint、Claim/Evidence、权限/PIT、Context Builder和恢复路径。当前实现优先于历史范围描述；本轮用户请求覆盖先前AGENTS及约束中的“仅串行/不启动P4.5”，原文件的历史结果不改写。

| 实际组件 | 审查结果与最小改动 |
|---|---|
| Parent / Child Spec | 旧Dynamic v1/v2、Financial Parent、Domain Parent v1/v2、Financial/Market Child v1原身份与限制保留；新增显式ParallelParentSpec |
| Single Runtime / Registry / Executor | 原核心及授权工具入口复用；parallel.py仅提供调度函数，无第二套Runtime、Router或新Agent |
| root-budget/v2 | 原串行折叠/恢复保留；新Parent显式使用v3组预留，Parent保持唯一根写者 |
| Parent / Child checkpoint | 原Run锁、SQLite事务、append-only哈希链复用；Parent新增parallel_groups，每Child仍独立RunState |
| Evidence / Claim / Observation | 原DataRecord、工具读取、确定性计算和独立Fraction核验复用；Child返回原结构化结果，Parent重核后导入 |
| Context Compaction | P4.4目录编解码、去重、引用、Observation外置、Lazy Disclosure及控制文本压缩原样复用 |
| cancel / deadline / resume | 原绝对deadline及调用前后检查复用；增加组Event传播，reserve时固定Child deadline，按分支恢复 |
| direct / delegated / completion | 新Parent支持直接、串行一/二Child及并行两Child；原必需检查决定completed/insufficient/partial |

新版本`dynamic-parent-parallel-v1`通过`--parallel-domains`显式启用，与`--financial-child`/`--domain-agents`互斥；只允许dynamic/v2，不接收旧domain-version。Parent局部8决策/12工具/48000记账Token/240秒，根16/18/96000；两个旧Child均3/1/18000/120秒，最大深度1。只扩展既有Financial/Market，不增加Provider、金融Dataset、递归Child、交易、Critic、任意代码执行、消息队列或分布式框架。

Parent `parallel_groups`保存可信固定DAG：

```text
financial_branch ─┐
                 ├─ calculation → hypotheses → verification
market_branch ───┘
```

模型只能提出两既有AgentTool的parallel动作，不能提交依赖、scope、grant、事实或新窗口。两源未开始且无相互依赖才可并行；下游工具显式gate依赖。状态有pending/reserved/running/completed/insufficient/failed/cancelled/late_discarded，分支持久保存run/request/调用/额度/deadline/结果hash/提交标记。每域唯一Child，Parent同一轮不能在活动Child期间执行依赖阶段。

Worker分别使用同一DynamicRuntime类的独立实例，独立RunState/messages/plan/Executor/局部预算/turn/deadline；不持有可变Parent message list、研究状态或根字典。共享原模型适配器、授权数据服务、Artifact/Checkpoint基础设施与不可变请求约束。Parent唯一协调器接受结果并更新状态。

P4.4兼容要求包括旧Spec和恢复binding、原模型wire、冻结问题、全部Fact/Claim/Evidence、数值/单位/报告期、来源/PIT/cutoff/snapshot/权限及血缘。旧报告六份逐对象完全相同恢复，旧首轮预览亦相同；全部原Artifact文件SHA与SQLite行数不变。当前代码不等于旧演示源码freeze，不冒称旧源码门禁匹配。

## Regression

最终`PYTHONPATH=src; python -m unittest discover -s tests -v`：**680项，666通过、14项专用数据库测试跳过**。既有临时隔离PostgreSQL脚本使用本地镜像、随机127.0.0.1端口和独立数据库：**680/680通过**，结束清理容器。相对P4.4上下文修复的606项新增74项机制/契约/QA测试，原606项及历史金融分母保留。

最终日志为`.runtime/phase4-p45-offline-delivery.log`、`phase4-p45-postgres-delivery.log`。compileall、pip check、CLI帮助通过。新模块与发行扫描见独立delivery-integrity.json；真实运行后的首次final-integrity.json保留。

最终核对3334份源码/文档/旧输入、85份本轮Artifact/日志及63份sdist文件，真实密钥精确匹配均0；包内禁入文件0、新parallel/context telemetry模块齐全。原冻结源码可恢复，六旧报告及新失败报告只读回放文件/行数保持，模型/Provider/Checkpoint追加0。wheel未验证、未发布；首次发行包与交付版发行包分别保留。隔离数据库交付回归首次请求遇审批服务容量错误而未执行，随后同一审批流程重试成功，未绕过审批。

原P4.3两份、旧P4.4两份及定点一份、P4.4 Context Remediation一份，共**6/6报告相同**，模型/Provider/Checkpoint追加0，原文件/行数不变；证据`.runtime/phase4-p45-legacy-replay-v2.json`。首个兼容QA因旧preview没有run_id而失败，修正QA使用可选run_id后通过，原失败日志不删除。实现开发期的负压缩值断言、旧Observation顺序重构及大型夹具Evidence计数错误也已修正，原日志保留，不涉及改旧金融失败或缩小分母。

## Parallel correctness

真实barrier证明两个Child同时处于running且占用不同线程；Parent下一模型/依赖工具只在两个源结果接受后运行。反向控制financial→market与market→financial得到相同Fact/假设及按对应run/调用ID规范化的Evidence graph，调用身份和时间作为各运行真实血缘保留。源输出键及Child摘要固定域排序，计算输入/Fact/Evidence排序确定性，不以先返回者决定业务优先级。

重复parallel、既有域已读取、同域第二Child及未ready依赖均拒绝；新Parent直接、单Child及两串行Child路径完成。没有任意DAG或强行并行依赖步骤。当前可信契约把两个源读取均列为必需，失败分支导致partial；未增加可忽略失败的任意节点分类。

## Root-budget correctness

v3 `reserve_children`将两Child最大额度作为一个all-or-none事件持久提交，成功才submit。两Child各3决策/1读工具/18000Token，两个Parent AgentTool包装亦计工具。预留保留Parent全部剩余局部决策/工具/Token envelope；根不足时Child派发0。5余额、两份各3需求的组拒绝，账本无负余额。

并发安全复用原Parent OS Run锁和单写者；Worker只能消费已持有局部额度。两个协调器同时resume同一run的竞争测试中第二个在派发前被Run锁拒绝，根只有一个组事件。未新增共享字典CAS或独立预算系统。未收完整可信Child回执则全分支预留保持；完整停止回执中未知付费intent的Token预留仍保持，只释放可证明未使用额度。已知结算一次，resume不再次预留/付费。

本轮真实组预留**6决策/4工具/36000Token**（含2包装工具），实际Child部分5决策/4工具/2596Token；Parent初始1决策/1446Token，根合计**6决策/4工具/4042Token**。根累计额度预留42960、实际模型派发累计预留23002分列；它们都不是实测Token。unknown0、未结分配0，默认根上限不变。

## Permission/PIT

继承有效委派范围∩可信应用授权∩service policy∩ChildSpec∩Provider/SourceGrant。Child工具和binding均按域收窄；Parent模型不能提供grant。旧Market跨域/禁止spawn测试与新并行Financial跨域测试继续通过；两个私有上下文的binding、工具和观察隔离。

首次读、cache/dedup、恢复、结果回父、Artifact/Evidence再读继续经过原授权/PIT服务。并行读后撤销Financial SourceGrant时cached result不能进入Parent；完成回放撤权与Artifact篡改都被拒绝。Parent接受结果前核验Child身份/domain/实际run/request/checkpoint hash、源集合/provider/grant、Evidence ID、Artifact内容及snapshot/cutoff/PIT，再执行原Child completed replay与独立源读一致性检查；导入前后再次检查截止/取消。

真实输入为600500.SH，public PIT，cutoff `2026-10-04T00:00:00+08:00`；行情窗口2026-09-16–09-24，财务2024-06-30–2025-06-30。同一冻结snapshot `2fd28cf7588ae798a8b4014b353d5dee14ab671eab31e8e6bde5b7db29bda22a`，原tushare来源/源scope/grant保留，未调用新金融Provider或倒填历史可用时间。

## Cancellation/late result

两个活动Child收到Root/Parent共享取消信号后不再派发模型/工具；在途同步I/O按照原bounded timeout返回，随后检查并记录late_discarded，不能进入Parent Evidence/Claim/Observation/context。取消引起的late同时计cancel和late，两计数可重叠，不虚标成功。

已合法提交Financial A后Root取消Market B，A保留在checkpoint，B不导入，任务不completed。单Child绝对deadline小于Parent时成功Sibling保留，超时分支丢弃，必需任务partial。Root deadline、cancel/completion竞争、一个未知失败一个成功等均有合成验证。未支付真实故障模型调用；没有线程强杀或远端请求撤回承诺。权限异常及reserve后未start的取消亦收口parallel telemetry和终态；未核完整Child回执的额度继续保留。BaseException crash injection不伪装为有序终止。

## Recovery

实际crash injection覆盖两Child均reserved未启动、一个已知完整Child回执而Sibling仍活动、Child model_started intent持久化后unknown、两个完整回执Parent尚未join，以及group-ready后telemetry尚未写入。

恢复保持原root事件和绝对deadline、Child run/request/binding及局部账本；完整Child不重新运行，已settled结果只重授权/导入，不再结算。unknown付费intent按原Runtime停止，不自动重发。submitted标记、工具import事件及Child result_ref交叉核验，Fact/Evidence及父子链接无重复。若Sibling因真实取消/未知停止则保留partial，不为了恢复测试补造成功。

真实失败报告恢复**完全相同**，模型/金融Provider调用0；子回执、消息SHA、用量、ScopeGrant/Artifact/PIT及Context/Parallel测量均再核对。失败可回放并不表示功能通过。

## Context telemetry

所有新Dynamic运行记录`context-telemetry/v1`的准备与回执事件；旧checkpoint无该字段时保留原报告。核心字段包含run/parent/child/role/domain/turn/route/parallel group/width、12000 cap、before/after/total/saved/ratio、各字节桶、visible/total Fact/Claim/Evidence、input/output/total tokens、派发/超限/status/stop reason及真实wire SHA。

当前Fact就是Claim，数量相同，claims_bytes为0以免重复计数。before为相同system/control下完整typed catalog payload的versioned反事实基线，非旧P4.4wire；负节省值原样记录。桶按canonical value字节计，不含key/separator，另列framing余量；可靠dedup/Lazy贡献可计算，无法可靠拆分的reference/externalization/control贡献为null。未知token为null，不能填0。Telemetry不进入模型prompt，不影响路由、权限、预算阈值或结果判定；恢复可重建paid wire并校验Token回执，篡改拒绝。

真实Parent初轮before5482/after5680字节，saved=-198；Financial三轮1572/2127/2175，Market两轮1645/2123，Child旧wire before=after。真实全体最高5680/12000，没有发生上下文阻塞。6个真实turn都采集Token与状态。

另合成300日合法bounded快照在两Child合并、calculation后触发20891>12000；Parent未派发该超限wire，以partial/dynamic_context_budget_exceeded停止，canonical **7 Fact/Claim及305 Evidence**和300条源记录均保留，零模型回放相同。公开600500输入配合成Transport的机制诊断完成7/12闭环、最大10877字节，明确标为synthetic，不计真实分数或Token。12000没有被修改；测量重构大视图只供计数，无法返回派发入口。

## Parallel telemetry

`parallel-telemetry/v1`真实写入Parent Trace与group：组/分支时间、queue/execution/join wait、wall与sum、预留/实际决策/工具/Token、cancel/failed/late/unknown、实际result_order及固定canonical_merge_order均存在。持久group、root_usage_after及Trace可确定性复算；篡改回放拒绝。group-ready崩溃恢复保持原finished_at，不把恢复耗时覆盖已完成区间。

| 真实分支 | 状态 | Queue ms | Execution ms | Join wait ms |
|---|---|---:|---:|---:|
| Financial | failed / no_progress | 79 | 7529 | 217 |
| Market | completed | 295 | 3998 | 3532 |

组wall7825ms、sum11527ms；实际顺序Market→Financial、canonical域顺序Financial→Market。已知模型派发interval分别保存并核对paid intent，真实网络派发重叠成立。只提供后续speedup candidate的原始可计算数据，不能以本项失败任务宣布Multi优于Single。

Trace支持Dynamic Single、Parent direct、一/二串行Child、parallel_2_child和Child各domain，并保留completed/insufficient/partial及cancel停止原因。后续可按status/stop_reason分层计算context分位数、超限率、压缩率、Token/延迟/等待/根使用率及Task Success；本轮没有Phase 5 Dashboard或Phase 6 tuner。

## Real end-to-end validation

新任务`p45-600500-independent-required-domains`，已知公开源上的新联合问题，不重复P4.4旧002363/601009任务充当新独立样本，不宣称盲测。真实派发前冻结question/security/window/cutoff/PIT/snapshot/sources、必需检查与四项必需指标、root/model/deadline/源码/成功条件和授权envelope。原始source文件SHA继承并复核，输入contract valid后封存。

计划SHA：`33e71c95464bd61723b1b95d78e07ca351858a3f46e0d77cc717d716a31a2c13`。模型仅配置的`deepseek-v4-flash-0731`端点，无替换。独立新campaign上限16决策/96000记账Token/480秒，Parent240秒、Child120秒及12000字节上限不变。

| 角色 | 决策 | 实际读/包装工具 | Input Token | Output Token | Total Token |
|---|---:|---:|---:|---:|---:|
| Parent | 1 | 2 | 1415 | 31 | 1446 |
| Financial Child | 3 | 1 | 1530 | 69 | 1599 |
| Market Child | 2 | 1 | 953 | 44 | 997 |
| 父子合计 | 6 | 4 | 3898 | 144 | 4042 |

功能**0/1**。Market读取后正常finish；Financial读取后再次两次请求相同financial动作，原dedup与每次重授权继续生效，工具实际一次，但paid模型三次计账，原两次无进展规则停止。Parent `partial / parallel_required_branch_incomplete`，calculation/hypotheses/verification未运行，Parent **0 Fact/Claim/0 Evidence**，不导入失败Child数据，不以另一路成功声称完成。实际总wall10313ms，组7825ms；unknown0、新金融Provider0。它是模型动作失败，不冒称不可控外部条件豁免。

派发后未改问题/预算/Child旧Spec、未重试或覆盖失败。回放1/1相同且0模型/Provider调用，functional_passed仍false。计划、完整逐轮消息/回执/独立账本、report/summary、checkpoint和真实metrics均保留在`.artifacts/phase4/p45-20261005/`；旧失败及分母不改。

```powershell
$env:PYTHONPATH='src;scripts'
.venv/Scripts/python.exe scripts/phase4_p45_demo.py --replay --plan-sha256 33e71c95464bd61723b1b95d78e07ca351858a3f46e0d77cc717d716a31a2c13
```

## Remaining gaps

**完整成功的冻结真实并行闭环仍缺失，P4.5状态保持未通过。** Financial旧Child的重复读取/no_progress行为需要独立诊断；本轮没有改变其冻结协议或追加付费任务以消除原失败。真实运行后仅补修parallel.py的权限异常/启动前取消Telemetry收口，不改变prompt、Spec、预算或该次结果；原parallel.py字节副本保存在frozen-source，全部原code_files SHA可恢复。当前源码因此不宣称仍等于真实运行当时源码freeze，旧计划再次live会按门禁拒绝；当前Runtime对该失败的只读回放仍相同。首次完整679/679回归与当时final-integrity另保留，补修后最终680/680回归另列。后续若版本化修复或新增真实任务，必须另行保留这次0/1及原问题/预算/回执，而非改名completed或覆盖文件。

机制目前仅可信两必需源DAG，不支持任意分支/动态跨分支依赖/更宽并行、独立Router、递归Child或分布式恢复；同步在途请求是bounded cooperative取消。Telemetry细分压缩贡献部分null及versioned基线语义明确，正式统计需未来代表性数据。没有性能优势、广泛金融准确率、盲测泛化或12000最优阈值结论。Phase 5及Phase 6未启动，未外部发布。
