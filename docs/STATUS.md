# 执行状态

更新日期：2026-10-06（Asia/Shanghai）。本文只记录实际实现和执行结果。实现前的审查及历史运行证据保留在对应报告中，不以新结论改写旧失败。

## GitHub 仓库上传准备（2026-10-06）

用户明确授权将本项目上传至 `Lings23/financial-analyze`。本地已初始化 Git 并配置该仓库为 origin；通过 GitHub 连接器确认写权限，保留远端初始提交及 MIT LICENSE。待提交源码、文档、测试与 evaluation 已完成本地真实密钥精确匹配扫描，匹配0、禁入文件0；`.env`、`test_api.txt`、`tushare.txt`、`cninfo_key.txt`、`.venv`、`.artifacts`、`.runtime` 继续忽略，历史本地产物保留。此轮只处理版本管理与上传，业务实现、阶段结论、默认与预算均保持，未重跑业务测试或发起金融 Provider/模型调用。上传完成与远端提交核对结果以 GitHub 提交和本轮交付回执为准。

## 当前结论

**Phase6首轮限定验收完成：两已有案例×Parent v2 baseline/v3 candidate真实4/4通过，4/4零追加只读回放一致。** 仅新增显式`dynamic-parent-parallel-v3` / `dynamic-context-view/v2`精确metadata表示，Child显式v3；旧协议、默认、身份/恢复与12000字节保持。603207两版均completed且7Facts/12Evidence，688184两版均合法insufficient且6Facts/12Evidence/非正基数缺口保持。20项必需执行检查全passed，四次verification均模型实际选择并执行，两Child实际I/O重叠4/4，PIT/授权/不可变快照/血缘及根/局部预算核对通过。

真实36父子决策/28工具/67035已知暨记账Token/unknown0/未结算Child0/金融Provider网络0；派发累计预留273916、根累计含组预留350060分列。baseline合计34305Token，candidate32730，实际少1575（4.59%）；候选十份paid状态精确回编同状态v2，含system净省3414/91889字节（3.72%），两首轮各增加94字节诚实保留。Runtime合计baseline37313ms、candidate37329ms，未证实延迟改善；不声明P95/统计优势或达到20%历史Token目标。样本为2个已知非盲案例/4运行，独立新任务0，不能改写Phase5原8/9与Parent v2另列1/1或扩大并行启用。剩余2修复槽位未用、预算不复用、不进入下一阶段；决定`limited_explicit_lossless_representation_accepted`，默认仍保持。

最终纯离线828项814通过/14数据库跳过、0失败；专用隔离PostgreSQL828/828、0跳过并回收容器；历史19/19只读回放与5003旧文件SHA保持。新回放4/4模型/Provider/Checkpoint追加0，根只读实测审计另核12run哈希链/36持久paid状态和回执及实际verification，旧证据/新manifest保持。原中间失败完整保留：821离线1合成时序失败/14跳过、821隔离4 Windows锁审计错误、828离线1旧P45合成时序失败/14跳过；仅夹具增加20ms有界I/O停留，真实判据/动作/预算/断言不改，新旧稳定各3/3通过。详细设计、诊断、实际表及可复现命令见[Phase6首轮记录](PHASE6_FIRST_ROUND_20261006.md)。

冻结计划SHA `2b80c8622949757194d298155f315bdac23fd2d25da1edd228bd23630edab5e1`，source-manifest SHA `e53c9a0ecf90f23e66bc40a5b26f3f02fe480dad2ccc8f77df316a2a95262eb6`，73份源码副本含密钥0；新Dataset SHA `b8ed9e61c6d1f2695df974e80efce7de6af14368ab4b9e17675a642285b30c84`，Trace manifest SHA `34ed3ca9e228e43056e0b6ee9f81e2bc041660b489ad1d57b047f2ea0fa1a4a2`。真实证据`.artifacts/phase6/first-round-20261006`，日志`.runtime/phase6-verified-{offline,postgres}.log`、回放`phase6-replay.json`、根审计`phase6-root-actual-audit.json`；独立代码审查通过。下文Phase5/P4未启动Phase6均为各轮历史事实。

独立实际只读审查亦通过：4/4报告、36paid逐wire从model_pending/原checks/sourceoracle精确重构、12run只读SQLite哈希链及73冻结源码一致，5003历史与本轮冻结文件SHA前后保持、模型/Provider/Checkpoint追加0。完整记录`.runtime/phase6-independent-real-review.json`与成功日志`phase6-independent-real-review-complete.log`；最初QA包装假设与根QA字段KeyError失败日志保留，仅修QA，无冻结生产/协议/账本改动，不冒称金融专家真值。最终交付索引与密钥/源码/历史扫描另存于Phase6目录及`.runtime/phase6-final-integrity.json`。

最终交付完整性扫描通过：692份源码/文档/本轮证据/日志精确密钥匹配0、禁入文件0，65冻结实施代码与当前源码相同、73源码副本及全部历史保持，没有构建发行包或发布。独立验收索引`.artifacts/phase6/first-round-20261006/acceptance.json` SHA `c609d792d6460e34aeb6942f86235a0a608d84b85b793f32747ad345ef831f7a`绑定plan/Dataset/manifest/各只读审计及报告，不改原冻结live材料；本文最后同步后的交付再扫描另存`.runtime/phase6-delivery-integrity.json`。

**Phase 5 原有界评估8/9保持；Parent v2单项同案例修复复验1/1通过。扩大并行启用的原9/9门槛仍未达到。** 用户追加授权后，仅新增显式`dynamic-parent-parallel-v2`可信执行pending/can_finish与精确合法动作反馈，默认v1、历史身份/paid输入、finish/no_progress、预算/DAG及12000 cap保持。修复688184真实两Child并行，Parent实际calculation→hypotheses→verification→finish完整闭环；五项执行检查passed，非正基数的hypothesis insufficient及6Facts/12Evidence/原oracle保持。模型末轮请求finish(completed)，Runtime依原证据规则如实报告insufficient/evidence_insufficient，执行完成与结论不足分离；本轮没有提前finish拒绝，拒绝后纠正机制另由合成测试覆盖。

复验独立预算16决策/96000记账Token/480秒，原局部限制与源/请求/授权/端点/模型不变；实际Parent5/13846Token、Financial2/1580、Market2/1511，根**9决策/7工具/16937已知暨记账Token/unknown0/未结算0/金融Provider网络0**。派发累计预留68893、含组额度的根累计预留87929另列；wall19422ms、parallel section6273ms，实际Child模型I/O重叠；最高11318/12000，未溢出。全部源/数值/PIT/权限/快照/血缘/根账本/付费遥测核对通过。新报告零模型/Provider/Checkpoint追加回放1/1相同；原九报告9/9和旧六报告6/6相同，618原campaign文件SHA/原62源码副本保持，旧P45失败及所有分母不改。独立新任务0，不能补写原9/9或宣称其余case已验证v2；Phase6未启动。

修复代码完整纯离线790项776通过/14数据库跳过（`.runtime/phase5-parent-repair-offline.log`），随后新增harness机制4/4定向通过；最终专用隔离PostgreSQL **794/794通过、0跳过**，容器回收（`.runtime/phase5-parent-repair-postgres.log`）。新增19项Parent协议/CLI/harness均机制测试，不作金融真值。compileall/pip check/CLI帮助通过；五源码独立只读审查无可操作缺陷。新计划SHA `695fb5f6633e9989b015314d8bfe526486daa250ad848034204e00435e238731`，证据`.artifacts/phase5/parent-progress-v2-20261006`与`.runtime/phase5-parent-repair-{wire-preflight,code-review,replay}.json`。预检最高11614字节只作原paid状态重构，真实复验结果另列；下面原8/9当轮结论保留。

修复交付首次完整审计318份源码/文档、778份Phase5产物/日志和64份sdist文件，真实密钥精确匹配均0、禁入文件0、新Runtime模块齐备；新源码仍匹配修复freeze、旧62文件副本逐SHA匹配，479历史审计文件保持。证据`.runtime/phase5-parent-repair-final-integrity.json`，源码包SHA `42d8332becdba1730b8a4a0f5b4d5ddce4cf35816a000738ae8225ca7f8e7518`；wheel未验证、未发布。新旧Trace分别索引于`.artifacts/phase5/trace-index-20261006.json`，不覆盖任何原材料。

独立真实只读审查通过：新九paid wire从三run的只读SQLite逐字节重构，intent/receipt/Context Telemetry/Root事件账本及实际verification、原source oracle一致；618原文件/62旧源码/63新源码SHA前后相同，模型/Provider/Checkpoint追加0。证据`.runtime/phase5-parent-repair-independent-real-review.json`，SHA `89a74d56fb5ae62c21d430edf57d34aeb296b36c2c8fd78e4461cc89b0704fbc`。最终文档和新增审查另由`.runtime/phase5-parent-repair-delivery-integrity.json`完整复核，不覆盖首次审计。

**Phase 5 有界路线评估与启用决定已完成；扩大并行启用范围未通过。** 2026-10-06明确授权的三个已知源新Dynamic validation任务×三路线真实 **8/9**：direct3/3、serial3/3、parallel2/3。688184并行两Child已完成且实际模型I/O重叠，6Facts/12Evidence及负基数不足判断与oracle一致；Parent却在verification前连续两次finish(insufficient)，原typed required_checks_pending拒绝后partial/no_progress。保留该失败，不能计作合法不足成功；没有改题、提高预算或重跑覆盖。事前9/9门槛未达，决定 `bounded_opt_in_not_supported`，原显式入口保持、不扩大启用、不改默认。Phase6未启动，12000字节固定。

新增确定性Trace评估器、冻结真实campaign脚本及29项机制测试；同一DynamicRuntime/Registry/Executor/Evidence/Checkpoint与Child v3复用，运行核心及历史paid身份保持。真实共 **77父子决策/157821已知暨记账Token/unknown0/未结算0/新金融Provider0**；派发累计预留610803，含组额度的根累计预留725019另列，不冒充记账成本。PIT/授权/不可变输入/血缘/数值核对均通过；45执行检查44passed，唯一未完成是上述verification。三并行运行实际Child模型I/O重叠3/3，context最高11341/12000字节，overflow/超限派发0；无阈值调优。

最新项目.venv纯离线 **775项761通过/14数据库跳过**；专用隔离PostgreSQL **775/775通过、0跳过**且容器回收。基线系统Python746项731通过/15跳过另存，不将跳过写通过。九份新报告 **9/9零模型回放一致**，模型/Provider/Checkpoint追加0；旧九报告10/10回放及479原文件/SQLite内容/SHA保持，原P45 0/1、v2复验0/1、v3复验1/1均不改。真实Trace Dataset含九新运行及P45三历史完整行、绑定九历史诊断索引；独立新Dynamic任务按case为三、独立盲test0、合成/复验新分母贡献0。

计划SHA `bae9f7aea9c4fb8764df60e4f4e106d21cc6ecd1da266ae0b418693828be5869`，Dataset SHA `7d251dcb29cf9fecf0cf93d3ffdbd58cb3e98cb70a322aaa9a649aff330f1c6e`。独立只读审查通过，保留全部失败配对；first direct107.703秒及顺序/端点/缓存影响未隔离，不宣称统计优势、金融真值或广泛性能认证。完整实现、九运行表、成本/延迟/失败原因和启用决定见[Phase 5记录](PHASE5_EVALUATION_20261006.md)。最新日志 `.runtime/phase5-final-{offline,postgres}.log`，真实证据 `.artifacts/phase5/targeted-20261006`，只读决定/独立审查/最终交付审计在 `.runtime/phase5-{replay,independent-review,delivery-integrity}.json`。以下P4记录保留其当轮事实。

**P4.5 Child推进修复及限定真实完整并行闭环验收通过；不自动进入Phase 5。** 最新显式Financial/Market Child v3与CLI `--child-protocol-version v3`将读取执行/数据缺口/合法下一步分开，并给精确动作键与可信格式反馈；Runtime/完成/重复/权限/预算/并行规则不改，默认v1及全部v1/v2 paid输入/恢复身份保留。原独立任务0/1、v2修复复验0/1保留；v3同案例同输入/授权/模型/预算复验 **1/1 completed**，独立新样本0。两Child各读取一次、第二轮合法finish，Parent随后calculation→hypotheses→verification→finish，全部六项必需检查passed，7 Fact/7 Claim/12 Evidence及原源oracle/权限/PIT/血缘相符，覆盖率/历史发布缺口保留。

最终纯离线 **746项732通过/14数据库跳过**；隔离PostgreSQL **746/746通过**并回收容器，日志 `.runtime/p45-child-repair-v3-{offline,postgres}-final.log`。首次v3隔离回归745通过/1个旧并发夹具竞态失败保留，随后仅把Market保持running到组取消，原断言/测试数不变，稳定性10/10及完整回归通过；生产调度/权限未改。v2此前720/720隔离通过亦保留。

真实Parent5决策/13508Token、Financial2/1583、Market2/1506，根 **9决策/7工具/16597实测暨记账Token/unknown0/未结算0/新金融Provider0**；组预留6决策/4工具/36000Token，组实际4/4/3089，Parent后续仍有预算。根累计额度预留85432与实际派发累计预留66396分别记录。wall20390ms、并行section6696ms，Financial/Market实际模型I/O重叠；result_order市场→财务，canonical merge财务→市场。九行Context Telemetry逐字节/回执一致，压缩前最高19174、实际发送最高 **10916/12000**，无overflow、不改cap、不调阈值。

原失败、v2失败、v3成功全部无模型/Provider/Checkpoint追加回放相同；六份P4.3/P4.4历史报告6/6相同。最终审计187份三阶段文件保持；原五份Child paid wire逐字节一致、v2完整59文件源码快照原SHA匹配。原及v2并非外部条件豁免，失败未覆盖。v3计划SHA `b9d53e7d281321244763a47686d8bf19769a9025e60f72be40944bd264051b7a`。细节、完整验收分项与剩余边界见[独立修复记录](PHASE4_P45_CHILD_PROGRESS_REPAIR_20261005.md)，证据 `.runtime/p45-child-repair-final-audit.json`。本例非盲、非独立新样本，不认证广泛任务质量、金融真值、历史发布准确性或Multi性能优势。

## 首次P4.5实现与验收记录（修复前历史，保留）

2026-10-05 后续用户授权的 **P4.5 Parallel Multi/M3工程与安全机制已实现；完整功能验收未通过，不进入Phase 5**。显式`--parallel-domains`使用新ParallelParentSpec/`dynamic-parent-parallel-v1`，复用同一DynamicRuntime；仅既有Financial/Market Child，深度1。可信DAG等待两源后执行calculation→hypotheses→verification；root-budget/v3在Parent原Run锁下一次持久预留两Child最大额度、保留Parent剩余局部预算，Worker不写Parent状态。独立分支状态/绝对deadline、取消/迟到丢弃、源授权/PIT回父重核及幂等crash/resume已覆盖。P4.4无损上下文及12000 UTF-8 bytes保持冻结；Context/Parallel Telemetry真实写入Trace，只观测、不调阈值。

最终专用隔离PostgreSQL完整**680/680通过**；纯离线680项666通过/14数据库跳过。相对原606新增74项合成机制/契约/QA，不充当金融真值或真实闭环。原Dynamic Single/P4.3/P4.4回归通过；六份旧真实报告（包括原无损Context复测）当前Runtime回放**6/6相同**，模型/Provider/Checkpoint追加0、旧全部文件SHA及SQLite行数保持。compileall/pip check/CLI帮助通过。日志`.runtime/phase4-p45-{offline,postgres}-delivery.log`，历史兼容证据`.runtime/phase4-p45-legacy-replay-v2.json`。

一项事前冻结的新600500联合必要域任务**真实功能0/1**：Financial与Market实际Child模型派发重叠，Market正常完成；Financial合法读取后连续重复financial动作，原dedup/重授权及无进展规则生效，`no_progress`停止。Parent诚实返回**partial / parallel_required_branch_incomplete**，依赖计算/假设/验证未提前运行，Parent Fact/Claim/Evidence均0。未伪造另一分支或把失败改名completed；该失败是模型动作问题，不冒称合法外部条件豁免。计划/问题/预算/Child旧Spec及6笔回执原样保留，未追加真实重试。

实测Parent1决策/1446Token、Financial3/1599、Market2/997，根**6决策/4工具/4042实测暨记账Token/unknown0/新金融Provider0**；并行组预留6决策/4工具/36000Token，根累计额度预留42960与实际派发累计预留23002另列。总wall10313ms、并行section7825ms，最高**5680/12000字节**。失败报告无模型回放**1/1相同**且功能仍false。新计划SHA `33e71c95464bd61723b1b95d78e07ca351858a3f46e0d77cc717d716a31a2c13`，原P4.4的1/2、定点0/1及无损复测1/1不改写。完整成功的真实并行闭环仍待后续独立诊断及新冻结验收，不能以合成7/12闭环替代。实现、十一类验收明细、Trace契约和剩余边界见[P4.5记录](PHASE4_P45_IMPLEMENTATION_20261005.md)。

真实运行后发现权限异常/启动前取消路径缺少组Telemetry收口，已仅补修parallel.py并增加机制测试；不改原模型动作、Spec、预算、失败报告或评分。原冻结源码副本保留于新目录frozen-source，原code_files全部SHA可恢复；当前源码不冒称仍匹配当时freeze，故旧计划再live会拒绝。补修后失败结果仍零模型/Provider/Checkpoint追加回放相同，发行与最终核对见delivery-integrity.json。

交付核对3334份源码/文档/旧输入、85份本轮Artifact/日志和63份sdist文件，真实密钥精确匹配均0，禁入文件0、新模块齐全；wheel未验证、未外部发布。首次真实运行的冻结证据和首次final-integrity保留，补修后的delivery-integrity另列，旧报告/回执/分数不改。

### 历史轮次：P4.4及之前

2026-10-05 追加 **P4.4 Context Remediation 阻塞修复及原002363定点真实复测1/1通过**。独立`dynamic-parent-domains-v2`采用可逆目录、scope/metadata/缺口去重、Claim/Evidence引用、历史Observation外置、按检查披露及原预算内`disclose`，旧v1消息和恢复身份保持。原744字节问题、7 Facts/12 Evidence及其值/来源/PIT/cutoff/snapshot/权限/血缘逐项一致；未提高12000字节、删事实或使用LLM摘要。financial_child→market直接→calculation→hypotheses→verification→finish完整真实闭环，全部必需执行检查passed，最高**10247/12000 UTF-8字节**，原财务方向冲突保留。父6/14618Token、Child2/990，根**8决策/15608实测暨记账Token/59787累计派发预留/unknown0/新金融Provider0**；独立新campaign上限16/96000/480秒，Parent原局部240秒保持。原功能1/2、定点0/1及25决策/38188Token旧账本和所有失败/分母不改写；未启动P4.5或完整Phase 6。

最终专用隔离PostgreSQL完整**606/606通过**；纯离线606项593通过/13数据库跳过，较旧542增加64项合成机制/QA，不当作金融真值。新真实报告无网络回放**1/1相同**，原P4.3两报告及旧P4.4三报告当前Runtime回放**5/5相同**，模型/Provider/Checkpoint追加0、原所有文件SHA保持；旧源码freeze gate不宣称匹配新代码。compileall/pip check/CLI帮助通过。原公开输入+合成动作另验最大10238字节，但不计真实分数/Token。新计划SHA `7abf18c9935fb07676f4bce250de0e3fe30ba7e20d10c2e85030b4c5d0b85871`，实际工程、逐轮外发与预算、发行和边界见[本轮修复记录](PHASE4_P44_CONTEXT_REMEDIATION_20261005.md)。一项原调试题通过不构成广泛质量/成本统计或官方金融真值认证。下述旧记录保持其原轮次事实。

本轮最终源码/文档/AGENTS3323文件、新Artifact/日志98文件与sdist61文件的精确密钥匹配均0、禁入文件0、新模块齐备；代码freeze、旧P4.4 SHA、8笔完整回执及原7/12语义再核对通过，证据`.artifacts/phase4/p44-context-20261005/final-integrity.json`。wheel未验证、未外部发布。

2026-10-05 后续请求的 **P4.4 Financial/Market串行领域委派已实现，工程/安全检查通过；完整真实功能验收未全部通过**。`--domain-agents`使用新DomainParentSpec，Parent同一模型选择直接工具或AgentTool，每域最多一个Child、合计两个；权限交集、root-budget/v2完整预留、deadline/cancel、禁止Child spawn及结构化回传均已覆盖。审查修复本地Evidence跨域tool_call归因漏洞。最终**542/542隔离PostgreSQL全回归通过**；纯离线542项529通过/13跳过，较P4.3新增70项均合成机制/QA，不作金融真值。日志`.runtime/phase4-p44-{offline,postgres}-complete.log`。CLI和实现边界见[本轮记录](PHASE4_P44_IMPLEMENTATION_20261005.md)。

新冻结两项已有合法公开输入：**原功能1/2、路由2/2、预算2/2**。601009的Financial+Market Child严格串行、完整必需执行检查通过，缺2024Q1保留insufficient；002363混合路径遇模型连续非法action字段，partial/no_progress。定点只明确原JSON动作格式、输入/目标/源码/评分不变，沿原28决策/168000记账Token/720秒总账本与deadline做新run；完成hypotheses后触及12000字节typed上下文，在verification前停止，**定点0/1**。所有原失败和分数保留。合计**25决策/38188实测暨记账Token/169502累计派发预留/unknown0/新金融Provider0**；累计预留与预算记账分列。没有扩大额度、延长deadline或删证据以获得通过。P4.4完整财务混合闭环仍须新版本/冻结复测，**P4.5不启动**。

两份原报告及一份定点报告无网络回放**3/3完全一致**；另旧P4.3两份实际报告在当前Runtime回放**2/2一致**、模型/Provider/Checkpoint追加0，原文件SHA未变。额外同一真实公开输入配短控制文本/合成动作完成混合机制闭环，全部7事实/12Evidence保留、最高11963字节；该脚本结果不计真实LLM分数或Token。旧frozen QA源码哈希按设计已不匹配当前新增代码，不宣称其原冻结门当前通过。独立实际回执与Evidence审查、正式计划SHA、明细和剩余验收项见[本轮记录](PHASE4_P44_IMPLEMENTATION_20261005.md)。发行检查源码/旧证据3314文件、sdist60文件的密钥精确匹配均0，禁入文件0、新Phase4模块齐全；本轮Artifact/日志另扫描匹配0，见`.artifacts/phase4/p44-20261005-v2/final-integrity.json`。wheel未验证、未外部发布。

前轮2026-10-05 已实现用户明确授权的 **M1 typed premature finish rejection + P4.3单个串行Financial Child**。CLI dynamic默认v2，旧v1显式可恢复；`--financial-child`使用独立ParentSpec和同一DynamicRuntime。父子权限交集、根完整预留、deadline/cancel传播、禁止Child再spawn、结构化来源回传与父Evidence关联均已覆盖。**472/472隔离PostgreSQL最终全回归通过**（纯离线459通过、13跳过）。新增60项合成机制及QA边界测试不当作金融真值/真实Provider验证；当轮Router、多领域及并行未实现。最终日志`.runtime/phase4-p43-offline-complete.log`/`phase4-p43-postgres-complete.log`。

新预登记两任务真实验证**2/2功能通过**，独立上限20决策/120000记账Token/720秒，不复用原M1过期额度。002363 Parent6决策/13398Token、Child2决策/990Token；父子合计14388Token，根预算及Evidence关联通过。601009 v2六决策/11674Token，全部必需执行检查通过，缺2024Q1证据保留为insufficient。总计**14决策/26062实测暨记账Token/104549累计派发预留/0未知用量/0新金融采集**。两份报告无网络回放完全一致。模型本批未提前finish，typed rejection动态修正路径由合成运行测试证明，不能声称实测触发过拒绝。

首项后QA脚本使用错误汇总字段`passed`（实际为`functional_passed`）停止，原日志/计划/Agent与评分代码/8次回执/报告保留。独立`phase4_p43_complete.py`先核对已知回执，继承原账本及deadline，只执行尚未启动的第二项；未重新付费首项或未知调用，补全评分/summary。冻结计划SHA `dd3f7e6ff97d751a147eabfb30aaf3257f1d3d51764a4101903cbf5737561955`，详见[本轮交付记录](PHASE4_P43_IMPLEMENTATION_20261005.md)。新结果不回写10-04的1/3分数或原Phase3分母。

本轮最终发行核查：源码/旧证据3307文件、sdist60文件的真实密钥精确匹配均0，发行包禁入文件0，新Dynamic/根预算模块齐全；另扫描本轮81个Artifact/日志（含SQLite）密钥匹配0。wheel未验证。结果`.artifacts/phase4/p43-20261005/distribution/check.json`/`final-integrity.json`，无外部发布。

2026-10-04 用户追加“推进Phase4”，并明确本会话向远端LLM发送数据默认批准。**P4.1–P4.2 M1 动态 Single 有界首版已交付，412/412隔离回归及必要真实功能样例验证完成。** 原3演示1/3通过，两个提前结束失败保留；000531明确原必需步骤的定点新运行通过，覆盖Observation后调整计划/行情取证及不足停止，601009未复测。不宣称原3题全部通过或广泛质量认证。合计22决策/37832实测Token/0新金融采集。新策略从首轮模型开始选择工具，固定Spec/Checkpoint保持。详见[实施与实际结果](PHASE4_M1_IMPLEMENTATION_20261004.md)。

2026-10-04新合法输入Benchmark已实际完成并独立评分：**38/38输入契约合法，L3 34/34、L5 4/4、ESR 588/588、幻觉0/588、关键锚点5/5，达到本批预登记门槛。Phase 3完整广泛认证仍未通过。** 本批全为validation、无独立test，L5只有一个证券/两个事件；536数值Claim只有142个全部输入官方可评且支持，394个部分/全部not_assessable。旧68/952任务/单元及旧分数不回写。指定模型38单次外发、137753 Token、零重试/替换；模型生成后没有修改Agent、问题或评分契约。详见[新Benchmark报告](../.artifacts/phase3/benchmark-v2-20261004/PHASE3_BENCHMARK_V2_REPORT.md)。下述同日路线规划记录保留，其“只规划”指该独立规划轮次，本批按另一项明确请求完成Phase3执行。

2026-10-04此前独立路线规划轮次要求尽快得到动态规划 Agent，随后研究 Multi；当时仅规划完成，Dynamic Loop/Child等均未实现。取消 Fixed/Dynamic、Agent/workflow 对比及旧广泛质量补证阻塞的路线继续有效；同日追加实施请求已开始M1，当前实现见首段。下列旧验收事实和历史结果不变。

2026-10-04完成独立验收及用户修改建议后的契约修复：**Phase 3 原冻结完整验收未达标。** 原端到端 L3 12/62、真实模型 L3 12/37、L5 2/6、新cutoff组0/25；冻结来源支持952/952、幻觉0/952、所需关键锚点2/56。新增输入契约审计为合法14/68、非法54/68；合法子集L3 12/12、L5 2/2，补充组合法分母0、成功率not_assessable。合法子集小且来自原回归材料，不能据此宣布广泛能力认证。没有发现原 Research Agent 可证实的计算/假设/PIT实现缺陷；请求问题、数据不足及前置条件分开归因。详见[契约修复与双口径](PHASE3_CONTRACT_REMEDIATION_20261004.md)。

本轮已实现正式 Benchmark Freeze Gate、双口径指标及 `single-research-v4` 结构化不足原因，原冻结结果/分母保持。已有官方全文的四字段版本桥增加独立对应版本覆盖至260/674，414仍not_assessable；旧254/420不改。后续完整验收需要版本化的明确研究请求、合法来源/事件/时间窗口及独立官方参考，不能由任意指定事件、当前信息倒填或删除失败得到通过。下列2026-10-03及更早记录保留当时pending和未完成事实，不代表目前仍未开展评审。

| 阶段 | 状态 | 依据与边界 |
| --- | --- | --- |
| Phase 0 | 最小契约已建立，未完成 | 4 个合成 PIT Case；六层至少 60 个种子及独立财务真值未齐。 |
| Phase 1 | **按调整后的日频研究首版范围验收通过** | 用户 2026-10-01 授权将 P1.7 剩余真实验证及 P1.9 三项实时行情移入后续。P1.1–P1.6 机制、真实三源采集/持久回放、P1.8 首版及限定历史日期案例已有通过证据；不是原全范围质量认证通过。 |
| Phase 2 | **固定 Single 首版及限定任务质量验收通过；广泛质量仍未认证** | 2026-10-02 用户批准25次真实模型批次，原始质量24/25=96%达到该批95%门槛；1项重复重点透明展示修复后25/25，原评分不改。123/123数值、263 Evidence、25/25无网络回放；最新隔离回归172/172。既有50/50离线与机制证据保留，不泛化为专家盲评/全局成功率。 |
| Phase 3 | **原端到端完整验收未通过；新合法输入v2限定验证通过，广泛认证未通过** | 原68/952分母、14合法/54非法及历史分数保持。新38合法题L3 34/34、L5 4/4，来源支持588/588、关键锚点5/5；非盲validation、官方完整输入只覆盖142/536，不能替代完整认证。v5显式金额变化不改旧YoY。 |
| Phase 4 | **M1/P4.3/P4.4限定功能已交付；P4.5 Child v3限定真实完整并行闭环通过** | 最新746/746隔离回归，原600500失败0/1、v2修复0/1保留，v3同案例复验1/1、独立新任务0；全部7Facts/12Evidence与真实Child模型并发及零模型回放通过。无独立Router，不泛化质量/性能；旧M1/P4.3/P4.4分母保持。 |
| Phase 5 | **有界定向评估已完成；Parent v2同案例修复通过，原扩大并行启用门槛未通过** | 原三非盲validation任务×三路线8/9及77决策/157821Token保持。后续688184 Parent v2同案例复验1/1、9决策/16937Token，独立新任务0；全部执行/源/安全/并发/零模型回放通过，最终794/794隔离回归。不能补写原9/9或泛化其他case的v2验证；默认/12000保持，Phase6未开始。 |
| Phase 6 | 完整优化未开始 | P4.4实际字节阻塞的最小确定性无损修复单列，不作Phase 6全面缓存/成本/P95优化验收；交易、下单、组合调整持续排除。 |

## 本轮 Phase 4 M1 实施（2026-10-04）

- 新增`dynamic_contracts.py`、`dynamic_protocol.py`、`dynamic.py`及动态CLI/中文Markdown/精确JSON，独立`single-dynamic-v1`身份。source/calculation/hypotheses/verification为受限引用工具；模型JSON不允许数值、公式、授权、改cutoff/快照或删除必需检查。计划文本仅控制信息。
- 复用ResearchRuntime、ToolRegistry/Executor、模型回执核验、SQLite追加Checkpoint、确定性研究计算及独立Fraction验证。首轮模型先于取数，后续步骤由模型依据Observation选择；没有先完成固定全套流程再选重点。无新Provider、数据库schema、Child/Multi或交易功能。
- 默认8模型决策/12工具尝试/48000记账Token/1024输出/240秒绝对deadline/12000上下文字节。已知合法用量替换当前预留；失败未知不释放，累计预留/实测/未知分别报告。重复已完成动作不派发，连续2轮无进展停；恢复遇未知付费结果不重发。
- 独立安全审查发现并修复恢复时账本清零、延长deadline、伪造Observation与替换待执行动作的缺口；校验历史状态/Trace intent和receipt、固定必需检查、重新授权源附件并重建Observation。未完成重授权/取消/超时不发布缓存事实；completed回放也重授权/验数，不再调用模型。
- 实际完整离线初轮400项387通过/13跳过、隔离初轮401/401日志保留；最终完整离线**412项：399通过/13专用PostgreSQL项跳过**，隔离PostgreSQL**412/412，0跳过**。日志`.runtime/phase4-m1-{offline,postgres}-final.log`；临时容器仅127.0.0.1并已回收。新Runtime36/协议20/CLI12/demo9共77项均机制fixture，不作金融真值。compileall/pip check/CLI帮助通过，追加定点脚本py_compile及真实回放另执行。
- 事前冻结3个新任务，仅复用原合法快照；原与新3/3输入合法，首轮及全部可外发值envelope/源哈希固定，proposal SHA `c688d90f01571b10407eed7e983ab47e9d1b7cfe1e5fc81aa9d6920ce42fab45`。本会话明确数据发送授权不复用旧38/29次额度。首次自动审批拒绝未启动；只读核验具体既有端点/仅公开金融数值并引用用户明确授权后，同一请求获准执行。
- 初轮16决策/26464实测Token，002363多步任务完成；000531漏verification、601009漏hypotheses/verification，原始**1/3功能通过**、失败和非法动作回执保留，Runtime未伪称completed。定点只在000531 question明确原必需步骤，研究目标/输入/成功规则/Runtime源码不变，不改旧回答；新运行6决策/11368 Token，所有执行检查passed、假设insufficient，双同比缺2024Q1保留，功能通过。601009未追加调用，不将它计为修复通过。
- 合计**22次指定模型决策、37832实测/预算记账Token、151177累计派发预留、未知0、自动网络重试0、模型替换0、金融Provider新调用0**。实施前冻结的是144000预算记账上限，已知合法用量替换本次预留；累计派发预留151177另列，不伪称小于144000。定点沿原24决策/144000根账本和原绝对deadline。3原报告+1定点报告无网络另进程回放**4/4完全一致**，复核模型/Provider0。
- question由可信应用事先确认与manifest证券/窗口/必需检验相符。completed只表示这些绑定检查完成，不认证任意自然语言语义覆盖、原文提取或开放式研究。
- sdist59文件，动态3模块与既有研究模块齐备；3299源码/证据文件及124新增Phase4/日志文件和包内精确模型Key/TushareToken/验收库密码匹配0。本地凭据/运行目录排除，wheel未验证；证据`.artifacts/phase4/m1-20261004/distribution/phase4-check.json`。新结果与原失败详见[交付记录](PHASE4_M1_IMPLEMENTATION_20261004.md)。

## 前轮独立规划调整（2026-10-04，无代码执行）

- 用户本轮要求设计实施计划，已将动态 Single M1 设为下一交付目标；本轮未实现 Phase 4，不进行新的金融 Provider 或模型调用。
- M1 采用已有指定模型文本接口上的严格 JSON 动作循环，独立动态 Spec，保留固定运行兼容/回放。只做功能、安全/恢复回归和少量真实端到端演示的计划；未安排或执行 Fixed/Dynamic 对照。
- 后续 M2 通过同一 Runtime 的 AgentTool 建立受限串行 Child/领域委派；M3 再扩展并行。根预算、权限收窄与取消从第一个 Child 起强制，不能等并行阶段才补。
- 原 68/952 分母、原 L3/L5/关键锚点、官方对照、历史模型质量分数及历史测试记录全部保留。原完整验收未通过；后续不再以补齐该认证阻塞 M1，不声称历史问题已经解决。
- 本轮只检查规划文档一致性和历史记录保留；未重跑 unittest、数据库集成、模型联调或质量评测，下文测试数均为各原轮次实际结果。

## 本轮 Phase 3 合法输入 Benchmark v2（2026-10-04）

- 用户新请求要求设计、冻结并实际执行新Benchmark；另明确批准精确38次模型消息外发。新目录`.artifacts/phase3/benchmark-v2-20261004/`；manifest SHA `2080aaff734db11a0b8a027be99a5bd6e36b4b3f36f82c9b283b97a7c369ab7a`。旧68任务、952单元、原manifest/Review Pack/报告/Evidence/snapshot/cutoff/评分均保留。
- 原Gate上增加v2形式验证原Artifact SHA/full snapshot成员、可信所有者/SourceGrant、事件版本/原文/precision及实际before/after子窗口。38候选全部合法后才冻结，非法/未知整批拒绝；后续未删题。114错误主体/快照/撤权负控拒绝。模型messages、Spec、Prompt、预算、独立oracle与语义协议在第一笔外发前固定。
- 新`single-research-v5`/`profit-change/v1`显式增加`absolute_profit_change`：同报告期累计合并归母净利润CNY差额，允许非正基数，大于零才supported；原positive-base同比和v1–v4不改。v5恢复沿用v4诊断/schema/授权验证；CLI默认v4、程序默认v3保持，旧请求没有新增版本字段。金额验证分别用Decimal与Fraction，冻结评审oracle不导入生产计算。
- 34 L3涵盖25股固定主题轮转、六非正基数金额变化、两缺上年Q1和一明确事件；4 L5为300122原版/更正版×public/system。事件排除披露日，保守次日可见；cutoff在实际capture后1微秒、收盘已产生且合法可见，不声称准确日内首发。无任意替代事件。000016合法零行保留；exact-date only、不插值。本批未用600301日期不齐作为必需market_direction拒答测试，不夸大覆盖。
- 实际38次指定`deepseek-v4-flash-0731`调用、38原始response/JSON/Markdown/intent/receipt、137753实测Token、398132预留、0未知用量、0重试/替换、0新金融Provider调用。两项前置执行适配失败均模型0且日志保留；首次外发自动审批拒绝未启动，收到具体38次授权后才执行。Agent运行后不改Agent、Case或期望规则。
- 完成独立Fraction来源/PIT/公式/版本核查588单元及1047处Evidence，独立Judge完整读38份/5617行Markdown，新事实Claim0；最终L3 34/34、L5 4/4、ESR588/588、H0/588、关键锚点5/5。Required-check 47/47，实质可判定42/42；五项源证明不足按预登记正确解释，不把所有拒答计成功。假设supported19/unsupported21/conflicted2/insufficient5。
- 四层输入问题数A0/B0/C4/D2，本批失败任务均0；C为两空行情/两缺同期任务，D为两非正YoY前提。官方准确性另列：536数值Claim源支持，142全部输入对应官方支持，394部分/全部未知；去重108/160字段支持、52未知、0矛盾。source-support可评未知0不代表金融真值未知0。
- 全38标记validation、独立test0，底层已知材料不能称blind；300269两Case编译messages相同，仅37不同消息身份但38预登记分母保留。L5一证券/两事件不足以广泛泛化。完整Phase3认证仍未通过，最小剩余为独立test/多事件覆盖/对应版本官方真值；不作为当前动态M1工程阻塞，不在本批边修边评分。
- 初次严格oracle保留548/588来源支持、43/47检验、29/38确定性候选。独立source-only预检发现25处Evidence/9Case为全字段同一raw row的物理重复，被原QA唯一行条件误判；另存透明补充协议，完整行SHA/所有字段/原检查通过且期望公式/规则不变才接受。四旧期官方桥用外发前冻结的独立定位代码处理换行/期间parser不足，支持104→108/160，其他52未知保持；旧QA原输出不覆盖，非Agent修复或失败任务重跑。
- 最新完整离线335项：322通过、13数据库跳过；新增53项均机制fixture，不当金融真值。compileall/pip check/CLI检查通过；本轮未新跑真实PostgreSQL。严格oracle另进程两输出逐字节一致；补充仅baseline路径lineage不同，38Task/588单元全部判断一致；最终聚合三文件逐字节重算一致。原4502文件、38单次输出与47冻结实现文件哈希最终复查，文件名单独封存；v5实现源码另保存字节相同副本。

## 本轮 Phase 3 输入契约修复（2026-10-04）

- 用户修改独立评审 `REMEDIATION_RECOMMENDATIONS.md` 后明确授权执行。新产物目录 `.artifacts/phase3/contract-remediation-20261004/`，上一轮Judge/manifest/报告/Evidence/snapshot/cutoff/评分不回写。
- `benchmark-contract/v1` 独立预检Provider/Dataset、完整成员hash、证券、源版本、scope授权、PIT、明确事件及15:00前后价格时间可行性。缺可信元数据不算pass；非法/未知整批拒绝，正式Builder已接入。可信原始零行捕获可证明合法空Dataset，000016计数据不足，不猜停牌；CNINFO四个错误行情绑定仍非法。
- 68个任务在读原成功分数之前先完成契约判定：14合法/54非法/0未知。真实L3合同合法12/37、合同合法成功12/12；L5合法2/6、成功2/2；新cutoff组0/25合法，条件成功率null。原端到端12/37、2/6、0/25及合并12/62不改；必需检验完成另列128/272。
- 新归因四类任务数（可重叠）：原Agent实现缺陷0、Benchmark/请求契约54、已绑定数据不足3、前置条件/时间不可行16。旧评审的31数据不足分类保持，新维度把缺绑定和已绑定空数据区分，不把正确insufficient归责Agent实现失败。
- v4只新增结构化诊断和展示；v1-v3原数值、假设、reason、模型messages保持。CLI默认v4，旧回放显式选旧Spec；v4新身份隔离，完成和停止回放均验证诊断/schema并重授权。
- 官方版本新oracle明确688184差错更正与920489同一控制合并重述的四字段对应原版本，新增6个Claim occurrence可评估，260/674对应版本支持、414未知；原254/420不改。网络两次补取失败、新PDF0；根据已有冻结原文完成版本桥，不声称网络补采或最新重述可比性认证。
- 最终全套离线282项：269通过、13数据库跳过；55新增仅机制fixture。正式Builder在新Agent运行之前完成整批预检。原68请求v3/v4 factual payload均等于冻结原值；136完成回放、68撤权拒绝。另进程持久回放136/136原report digest一致、68撤权拒绝；模型/金融Provider网络0。compileall/pip check/CLI help通过。数据库结构未改，本轮未重跑隔离PostgreSQL。
- 契约审计/指标/逐案归因另进程逐字节复算一致；整批68新冻结负控拒绝、无部分manifest。原3886 Artifact/60未授权改变Judge文件hash保持、68/952分母不变；用户改动建议单独绑定hash。
- 开发QA发现并修复新门禁伪预检、指标复制、v4未知schema及停止诊断篡改等问题；这些是本轮新功能验证缺陷，不改写原Agent审计。新回归脚本一次相对路径错误修正，初始输出保留。具体日志、正式最终路径与剩余条件见[修复记录](PHASE3_CONTRACT_REMEDIATION_20261004.md)。

## 历史 Phase 3 原样本补证（2026-10-03）

- 独立评审准备：固定68份报告（43真实模型+25新cutoff离线补充）、952个Claim/假设/锚点单元，评分全部null；文件与正文哈希复查通过。空白评分、删除任务/Claim、改manifest及全打通过覆盖已知不足的反例检查通过，不生成专家评分、不认证新盲样。入口见[独立评审材料](PHASE3_INDEPENDENT_REVIEW_20261003.md)。
- 评审工具py_compile通过；再建源码包54文件、2179文件及包内密钥匹配0，秘密/运行目录排除，wheel未验证。已询问是否能安排独立评审人，目前没有完成的评审；不重复申请已批准且已执行的模型额度。
- 25股复权/半年报现金流及共享沪深300指数：51次官方请求全部非空、0重试。实际捕获时间建立独立scope/快照，仅用于新cutoff；旧库、旧请求、旧分数不改。本轮模型外发0，原37/43批准额度未复用。
- 原25股保留五类检验：复权24/25、基准23/25、财务同比19/25、现金流25/25、事件0/25；合计91可判定/34不足，完整任务0/25。不能将其改记为原历史批次通过。
- 独立Fraction/源值核对387/387、847 Evidence；新进程25/25精确回放；逐绑定125次撤权拒绝；三域300项原cutoff/采集前public/system不可见。证据`.artifacts/phase3/fullscope-20261003/enriched-audit/result.json`。
- 25个2025半年报合并经营现金流先独立抽取冻结，再与新增Provider值比较，25/25精度内一致且另进程重算保持；实际目视8页。机器辅助原文核对不是专家盲评，不扩大成其他字段或广泛语义认证。
- 剩余六项同比均为负基数；000016没有窗口内价格，600301股票/指数日期不齐；25个原请求未指定事件。四个旧事件还存在错误行情来源绑定、cutoff早于事后收盘或窗口早于事件等条件。逐项证据在`remaining-gaps-rechecked.json`，不能靠追加API调用或放宽规则消除。
- 用户已回复无独立研究报告/答案集/评审规范。完整L3/L5、ESR、幻觉和关键锚点门槛仍未验收；本轮只改QA/证据/文档，生产模块及前轮227项机制基线保持。
- 五个本轮QA脚本py_compile通过；重建源码包54文件、Phase3八模块齐备、本地秘密/运行目录排除；2168个源码/证据文件及包内精确密钥匹配0，wheel未验证。证据`fullscope-20261003/distribution/check.json`；官方现金流另进程回放日志`phase3-cashflow-reference-replay.log`。

## 本轮 Phase 3 续修执行明细（2026-10-02）

- 实现版本化v1/v2/v3指令及恢复隔离；默认v3提前生成完整证据候选，模型只能从中选择，仍需严格身份、格式、ID、Token及候选归属验证。没有改变财务公式/假设规则或原质量评分。
- ScopedReadService每次查询、附件及恢复重新解析可信应用SourceGrant；原scope/snapshot/provider/精确窗口与PIT不放宽。跨scope不复制数据、不改生产库；新事件行情保存在独立参考快照。
- 用户分别批准37次v2和43次v3，合计80次指定模型、184902 Token、0重试/替换、未知用量0；两个原审批拒绝均未启动。v3为98640 Token，预留307876；两批账本、批准记录、messages SHA及43条v3返回receipt收口一致。证据 `.artifacts/phase3/followup-20261002/final-acceptance.json`。
- Tushare仅新增2次，300122两个窗口17条价格记录；当前观察时间不反填，日期锚点仍使用原资格，事前排除披露日。五类目录均有真实可判定案例；广泛来源准确率未在本轮认证。
- v3共47候选，40任务仅1个候选；程序承担覆盖保证，100%不代表开放式模型研究能力。旧29任务仍缺证据；147假设共37可判定/110不足，14个聚焦任务全部完成，其余不计实质成功。
- 最终离线227项214通过/13数据库跳过；专用隔离PostgreSQL227/227。合成22/22仅为机制验证；compileall/pip check通过。日志 `.runtime/phase3-v3-final-offline.log`、`phase3-v3-final-postgres.log`、`phase3-v3-live.log`、`phase3-v3-live-replay.log`。
- v3一次开发测试因旧合成回答只选F1被新契约拒绝，更新合成协议stub后通过；数值期望未改。3条v2格式失败没有原文，仅存失败类别/用量；v3新增有界回执并验证反射凭据不会落盘，未以额外调用回收旧失败回答。

## 历史首轮 Phase 3 已批准真实质量验收（2026-10-02）

用户明确回复“批准真实外发，继续验收”，批准具体29次清单；已执行完该批次，详细评分、修复与后续方案见 [质量验收报告](PHASE3_QUALITY_ACCEPTANCE_20261002.md)。

- 实际 **29次指定deepseek-v4-flash-0731调用、0重试/替换/新金融Provider调用**；原messages SHA保持，29/29严格身份/格式verified。输入60382、输出945、合计 **61327 Token**，未知用量0；根预留191685、29个唯一付费intent保持在已批准边界。
- 原始质量 **23/29=79.3%，低于85%，未通过**：601528/688320/688315/000997/300269/920175均只选价格，漏已有财务数值；其中3个可判定假设还缺重点依据。没有重评分、删除失败或追加模型尝试。
- 新进程禁止Transport网络的回放 **29/29完全一致、175/175 Claim、325 Evidence、29/29撤权拒绝**；证据 `live-approved-replay/result.json`。事实/假设/锚点与冻结hash全部一致，原129假设仍19可判定、110不足。
- 已修复报告重点遗漏：独立标注“系统核对重点”，补已有可判定检验的支持/反证、缺行情/财务的已有值。缺同比仍不足，不造数、不改模型。真实保存回答重渲染 **29/29展示通过、12份系统补充、29份原JSON/分数保持**，额外模型0；证据 `presentation-repair/result.json`。
- 根因定位：原指令“最多3个”没有明确跨域覆盖及检验引用要求。保存下一轮明确指令方案 `selection-instructions-v2-proposal.json`，未应用到本轮Runtime、未实测，不冒充模型修复通过；本批29次额度已用完。
- 最新离线 **214项：201通过、13数据库跳过**，隔离PostgreSQL **214/214、0跳过**；前轮210/210保留。日志 `phase3-quality-approved-offline.log` 与 `phase3-quality-approved-postgres.log`。本轮新增4项补充/反证/缺同比/不可变/非研究保护回归。
- 最终compileall/pip check/展示复测CLI帮助通过；源码包52文件、6新增Phase3模块齐备、秘密/运行目录排除，819源码/真实证据及包内精确秘密匹配0。证据 `distribution-approved/check.json`，wheel未验证。原始messages清单与分数未改。
- 最后文档更新后另扫820文件，精确秘密匹配0，冻结清单SHA不变，根账本最终29次/预留191685；证据 `.runtime/phase3-quality-approved-final-secret-scan.json`。

## 前轮 Phase 3 离线质量验收（2026-10-02）

用户要求质量验收并授权DeepSeek API；详细结论、已执行修复和后续方案见 [质量验收报告](PHASE3_QUALITY_ACCEPTANCE_20261002.md)。

- 原财报窗口漏掉去年同期。25/25原始Tushare v2归档含同期记录；新增显式授权投影解码，保持原观察时刻/Artifact/Provider调用，新入库时间与新快照，不改生产数据库或旧快照。默认CLI尚未自动补齐；验收使用明确的同scope参考仓库，每次重建重新授权并核对原字节。
- 真实投影独立Fraction复核 **25任务、167 Claim、313 Evidence**；新进程回放25/25、撤权拒绝25/25、SYSTEM投影前不可见25/25通过。财务假设：支持5、不支持8、冲突6、不足6；原数值保持，非正基数不强算同比。
- 全部拟测假设 **19/129可判定、110不足**，缺指数/因子/现金流和事件对应行情；**整体质量未通过**，不能把拒答算实质成功。金融Provider新请求0。
- 原29次外发自动审批拒绝，进程未启动、模型调用0、根付费账本未初始化；理由是API使用授权未明确涵盖该真实事实导出。修复后29次具体messages及SHA已冻结，已向用户请求批准，仍未收到回复；没有绕过拒绝。清单 `.artifacts/phase3/quality-20261002/proposed-model-manifest.json`。
- 新增14回归；最新离线 **210项：197通过、13数据库跳过**，隔离PostgreSQL **210/210、0跳过**；日志 `phase3-quality-offline-210.log` 和 `phase3-quality-postgres-210.log`。早先本轮隔离206/206记录保留。compileall/pip check/新验收CLI帮助通过。
- 源码发行包52文件、6个Phase3新增模块齐备；秘密/运行目录排除，662源码/证据文件及包内精确秘密匹配0。证据 `.artifacts/phase3/quality-20261002/distribution/check.json`；wheel未验证。
- 最终文档更新后另扫663文件，精确秘密匹配0，拟外发清单SHA保持，根付费账本仍未初始化；证据 `.runtime/phase3-quality-final-secret-scan.json`。
- 投影QA两次错误假设和比例单测初次失败保留，修正测试契约而非放宽生产检验；原失败文件/日志不覆盖。Phase4–6、Multi与交易未开始。

## 前轮 Phase 3 执行（2026-10-02）

用户明确要求“阅读plan和status，执行phase3”，解除旧的Phase3禁止自动启动限制；Phase4–6与交易仍未授权。详细实现、证据与边界见 [Phase 3 实施与验证](PHASE3_IMPLEMENTATION_20261002.md)。

- 新增5个研究模块及`research --workflow research`：读取前固定计划、五类描述性假设/支持/反证/冲突/缺口、合格事件时间锚点、独立Fraction数值/血缘/PIT验证、无损引用上下文、完整恢复核对和Markdown/JSON。`--preview-model`仅保存本地精确messages，与真实模型执行互斥；默认模型关闭，付费未知结果不重发。
- 冻结合成L3/L5 **22/22**（L3 16、L5 6）、44预写数值、197 Evidence、22状态及精确回放通过；证据`.artifacts/phase3/synthetic-final/result.json`。不是金融真值、真实Provider或模型联调。
- 既有25股两窗口真实离线 **50/50**，248 Claim/563 Evidence/250假设状态，完成回放、撤权和采集前不可见通过；证据`.artifacts/phase3/real-initial/result.json`。全部250假设缺必需扩展输入，保持insufficient；不能由保守拒答宣布实质研究成功、真实模型或因果质量通过。
- 既有CNINFO两版本历史日期锚点 **6/6边界**、4次合格锚点、8 Claim/12 Evidence；public/system/原版/更正/撤权/回放通过。证据`.artifacts/phase3/event-initial/result.json`；缺对应行情，未计算事件影响。
- 最新完整离线 **196项：183通过、13数据库跳过**，隔离PostgreSQL **196/196、0跳过**；日志`.runtime/phase3-offline-final3.log`和`phase3-postgres-final.log`。新增24测试含实际专用PostgreSQL研究持久回放；初期两项测试因SQLite连接未关闭导致清理失败已修复，原日志保留。
- 实际CLI生成[当前单股研究报告](../.artifacts/phase3/cli-example/report.md)及精确本地model-messages；partial/退出2、3本地工具/0模型/0Provider网络。compileall/pip check/CLI帮助通过。sdist51文件、5新模块齐备、秘密/运行目录排除；468源码/证据与包内精确秘密匹配0，证据`.artifacts/phase3/distribution-final/check.json`；wheel未验证。
- 最终文档与CLI输出后再扫描472文件，模型Key/Tushare Token/验收库密码精确匹配0；`.runtime/phase3-final-secret-scan.json`。全程不输出或复制秘密。
- 本轮新模型/金融Provider网络调用 **0/0**，原资格、快照、秘密、历史评分及金融准确率分母不改。首版已经可运行；广泛Phase3 L3/L5≥85%/ESR≥98%/Hallucination≤1%/专家质量仍未认证，正文事实抽取、更多假设和独立真实模型质量待扩展。

## 本轮任务质量进一步验收（2026-10-02）

- 用户随后明确回复“批准”，授权原冻结25次限定批次。清单SHA保持；实际 **25次模型派发/0重试/0替换/0新金融Provider调用**，25/25指定模型返回严格verified，输入7075+输出525=**7600 Token**，全批预留37155，无未知用量。证据 `.artifacts/phase2/task-quality-20261002/live-approved/result.json`，日志 `phase2-task-quality-live-approved.log`。
- 冻结原始模型任务质量 **24/25=96%**，达到本批≥95%；唯一失败000016选择同值/同期间/同单位的收入与总收入，保留失败。报告展示透明合并重复重点，原JSON及模型评分不改；保存真实回答的展示复测 **25/25**，没有追加模型调用。
- 新进程Transport禁网络恢复 **25/25报告完全相同**；独立Fraction **123/123 Claim、263 Evidence** 通过；复核派发0。证据 `live-approved-replay/result.json` 与 `.runtime/phase2-task-quality-live-replay.log`。
- 新增2项重复重点展示回归；最终 `.venv` 离线 **172项：160通过、12数据库跳过**，隔离 **172/172、0跳过**。日志 `phase2-task-quality-approved-offline.log`、`phase2-task-quality-approved-postgres.log`。本批是固定market/income的透明代理规则，不是专家盲评/其他域/自然语言或全局统计认证。
- 本轮最后编译/依赖/sdist通过，46包内文件、8个research模块齐备，秘密/运行目录排除，源码/真实批次证据与包内精确秘密匹配0；`.artifacts/phase2/task-quality-20261002/approved-distribution-secret-check.json`，wheel未验证。此次只增加展示合并及验收复核脚本，没有改变模型prompt、快照、cutoff或追加真实调用。

- 用户要求进一步验收任务质量。检查真实冻结报告的表达与缺口说明，修复前 0/50，新增中文概览、百分比/人民币量级、实际窗口/报告期及中文缺口解释后 **50/50**；原精确 JSON/Claim/Checkpoint 不变。不是专家盲评或真实模型 Task Success。
- 新增 8 项显示/缺失/重点评分校准测试；项目 `.venv` 离线 **170 项：158 通过、12 数据库跳过**；隔离 PostgreSQL **170/170，零跳过**。日志 `.runtime/phase2-task-quality-offline.log`、`phase2-task-quality-postgres.log`。
- 冻结原 25 股近期窗口的真实模型质量 campaign，完整 messages 在 `.artifacts/phase2/task-quality-20261002/proposed-model-campaign.json`；最多25次、Token预留总上限60000、指定模型/配置端点，无重试或备用模型。评分关注有效既有 ID、市场/财务覆盖及同值收入非冗余，失败不剔除分母。
- 首次批次外发曾被自动审批在进程启动前拒绝：需要用户授权具体事实。当时新增模型调用0；后来用户批准原清单才执行首节25次结果，没有绕过拒绝。详见 [任务质量验收](PHASE2_TASK_QUALITY_20261002.md)。
- 最终四舍五入/显示单位调整后真实报告表达复测 **50/50**，`after-final/result.json`；离线 **158通过/12跳过**、隔离 **170/170**，日志 `phase2-task-quality-offline-final.log`、`phase2-task-quality-postgres-final.log`。compileall/pip check/sdist通过，8模块齐备、秘密/运行目录排除，源码/证据及包内精确秘密匹配0；证据 `.artifacts/phase2/task-quality-20261002/distribution-secret-check.json`，wheel未验证。

## 前轮 Phase 2 验收、修复与复测（2026-10-02）

- 结果详见 [Phase 2 验收](PHASE2_ACCEPTANCE_20261002.md)。修复模型重复 JSON 键、Runtime 异常 Token/输出预算校验、未完成恢复 deadline 绕过；新增五项回归，修复前三项新测试实际失败，修复后全部通过。
- 项目 `.venv` 最终离线 **162 项：150 通过、12 PostgreSQL 跳过**；隔离 PostgreSQL **162/162 全通过、零跳过**。日志 `.runtime/phase2-acceptance-offline-final.log`、`phase2-acceptance-postgres-final.log`。初始系统 Python 157 项另跳过一个可选 AKShare SDK，不覆盖历史结果。
- 合成评测复跑 **20/20、70/70 数值、130/130 血缘**；真实已有 25 股两窗口新冻结评测 **50/50 主任务、248/248 数值与 Claim 血缘、563 Evidence**，每任务新存储实例回放、撤权拒绝、采集前不可见通过。模型及金融 Provider 新调用 **0**；持久库只读，原数据准确率缺口保留。
- 真实固定 Runtime 测试达到该限定集 95% / 99% / 100% 门槛；不是盲样、供应商真值认证、全部域真实任务认证或广泛真实模型质量认证。`evaluation/phase2_real_acceptance_20261002.json` 冻结后才执行 Runtime；独立 Fraction oracle 不调用生产计算。证据 `.artifacts/phase2/acceptance-20261002/real-final/result.json`。
- 此节为最新 Phase 2 实际回归；下文较早 157/157、123/123 及模型联调记录保留历史日期。未扩大此前一次五条事实模型外发授权，未启动 Phase 3–6。
- 独立真实集二次执行保持 50/50、248/248、563 Evidence，证据 `real-retest/result.json`。compileall/pip check 通过；sdist 46 文件、8 模块齐备、凭据/运行目录排除；484 文件与包内精确凭据匹配 0。证据 `.artifacts/phase2/acceptance-20261002/distribution-secret-check.json`，wheel 未验证。

## 前轮已批准的真实模型联调（2026-10-02）

用户对上一轮列明的 5 条事实、`test_api.txt` 配置端点和一次 `deepseek-v4-flash-0731` 请求明确回复“批准”。本次发送前逐字核对 messages 与 `.artifacts/phase2/proposed-model-messages.json` 相同，并限制 Transport 最多派发一次；未变更模型、端点、快照或 cutoff。

- 实际完成 **1 次模型请求**，请求/返回模型均为 `deepseek-v4-flash-0731`，状态 `verified`，报告状态 `completed`；输入 291、输出 21、合计 **312 Token**，适配器计时 **1265 ms**。无自动重试、无新增金融 Provider 网络调用。
- 模型从既有事实选择价格变化、归母净利润、营业收入三个重点；5 条确定性数值与原报告完全一致。原实际观察窗口、缺同比基数和 `coverage=not_verified` 等边界保留。
- 新报告 run `dbc091ed4ca641b2a7178c8c25771572`：[已联调研究报告](../.artifacts/phase2/real-deepseek-approved-20261002/report.md)。独立 Fraction 复核 5/5 Claim、11 个 Evidence 通过；新进程回放与报告完全一致，回放 Transport 禁止网络且实际 0 次派发。
- 证据：`.artifacts/phase2/real-deepseek-check-20261002.json` 与 `.artifacts/phase2/real-deepseek-replay-20261002/report.json`。报告 canonical JSON SHA-256：`cbc4181de5a0ecc04f820fb513c2974b8b879b1d1e06eda9b18fb850f3f5761f`。检查文件中的 model_network_calls=0 指本地核对过程，本次真实联调调用总数为 1。
- 本轮未修改业务代码，也未重跑完整 unittest；157/157 回归和 20/20 合成案例仍是 2026-10-01 的既有执行证据。一次模型联调不替代整体真实任务 Success ≥95% / 计算 ≥99% 评测，不代表广泛数据准确率或持续 SLA。

## 上一轮 Phase 2 执行（2026-10-01）

用户新请求“阅读 plan 和 status 文件，执行 phase2”已经授权本次代码建设；前一会话只改文档后停止的要求不再阻止本次执行。Phase 1 已验收首版范围及尚未认证的质量边界保持。

- 已交付 `research/` 8 个模块和 `research` CLI：固定证券/窗口/cutoff/快照/唯一来源，聚合读数、确定性指标、严格模型 Claim 选择、数值来源链和 Markdown/JSON 报告。默认模型关闭；显式模型模式最多一次调用，不自动重试或替换模型。
- Checkpoint 使用本地 SQLite 追加哈希链与进程锁，模型 intent 先落盘。恢复不重置预算；已完成报告读取也重新授权、重查快照及附件。原 PostgreSQL 数据 schema 和真实来源快照未改写。
- 本次最终回归：**157/157 隔离 PostgreSQL 全通过，0 跳过**；离线 **145 通过、12 数据库跳过**。新增 Phase 2 测试 34 项。日志 `.runtime/phase2-postgres-final.log`、`.runtime/phase2-offline-final.log`。
- 冻结合成 L1/L2：**20/20 任务、70/70 数值检查、130/130 数值血缘**，使用预写期望值和 fixture 模型；不是金融真值或真实模型联调。证据 `.artifacts/phase2/synthetic-evaluation-final.json`。
- 真实本地示例：601009 既有 Tushare 日频/利润快照，5 条数值 Claim、11 条 Evidence、3 次工具调用；独立 Fraction 检查全部通过，新进程恢复报告完全一致；没有新增金融 Provider 网络调用。报告 [单股概览](../.artifacts/phase2/real-final/report.md)，记录 [Phase 2 实施](PHASE2_IMPLEMENTATION_20261001.md)。实际行情截至 09-24、请求截至 09-25，财务最新可见期为 2025-06-30，缺同比基数/日历及覆盖未认证均明确保留。
- 本次真实 DeepSeek 调用被自动审批在启动前拒绝，原因是需要确认将这份具体财务事实发往 `test_api.txt` 指定外部端点；**没有实际模型请求**，未绕过拒绝。拟发送内容 `.artifacts/phase2/proposed-model-messages.json` 已准备并与报告一致，待用户具体授权。
- sdist 构建及内容检查通过：包含新 8 模块，无本地密钥文件/运行数据/模型密钥字节。wheel 尝试因本地缺 `bdist_wheel` 失败，未宣称通过。
- 当前可用的是有界固定流程首版；Phase 2 整体 Success ≥95% / 计算 ≥99% 尚未按独立真实任务集验收。自然语言/动态工具循环未实现，未进入 Phase 3–6。

## 上一轮范围验收决定（历史记录）

用户希望尽快取得初版效果，授权跳过两项剩余工作并推进 Phase 2；随后要求本会话只整理 PLAN/STATUS，后续实现留给其他会话。按 [PLAN 的首版调整](PLAN.md)，Phase 1 作为“日频研究首版数据层”验收通过，不再等待剩余 P1.7 广泛质量/历史版本/三表跨日验证和 P1.9 三项实时完整表。

- 首版可用：三源已接入的日频观察数据、财务核心字段、日历/复权/指数、公告及采集后可见的近期新闻；限定两版日期精度历史案例保留。
- 继续强制：timezone-aware cutoff、每次读取授权、不可变快照/附件哈希、缺失不填零、普通采集不倒填历史可见时间、显式同口径 fallback 及有界调用。运行使用已验证的保守速率，不声称支持账号最高 80 次/分钟。
- 不承诺：≥99.5% 广泛真实质量认证、完整窗口/全市场覆盖、任意历史 PIT、每日历史成员、总收益、完整实时行情或跨日 SLA。coverage 继续为 not_verified，量额差异与未核对字段仍须在后续产品中明确展示。
- 本轮验收依据为既有实际证据：隔离 PostgreSQL 123/123、0 跳过；离线 112 通过/11 数据库跳过；持久命名卷真实重启回放；P1.8 的 16/16 请求、375 可见事实及原文抽检；一组真实日期精度修订边界。此轮仅文档调整，没有新回归、金融采集或模型调用；不将以前测试的时间写成本轮执行。
- 后续两项保留未完成状态及原分母，范围调整没有修复差异或网络失败。历史报告中“Phase 1 未通过”是调整前全范围结论，以本节为当前首版结论。

以下各轮证据与数值保留历史顺序，不因范围调整覆盖或重新计分。

前轮变化：取得北交所官方渲染DOM中的四行代码对照及三则切换通知，生产CNINFO Provider增加固定SHA/scope/orgId/窗口的显式旧码资格；默认身份校验保持严格。11个原缺失财务期全部取得18PDF，33项独立对照一致，累计218/225财务字段一致、7项缺独立口径。所有75期已有参考，共134PDF，原失败/空响应和各阶段保留。最新隔离PostgreSQL123/123通过、离线112通过/11跳过；命名卷实际重启后全部75组、11组新公告、218项及旧财务阶段、P1.8和日期案例回放通过。25股489记录/488事实、1536行情一致/942缺参考、72预期停牌缺行保持。当时三表跨日和P1.9三实时完整表未通过，Phase 1原全范围未通过。

此前最新数据变化：北交所官方日K可见提示取得丰光精密原登记近期窗口8日，原85日/510字段参考计划冻结后、读取Tushare比较值前封存限定DOM投影；48项全部精度内一致，32完全相等，授权旧快照/源附件及无网络重算保持。25股行情当前1944一致/72差异/462缺参考/72预期停牌缺行；财务218/225、原六股531一致/27差异/108未验证、深市540字段441一致/99差异保持。公开脚本默认请求非200及另一次兼容请求302均保留，不跟随重定向；不是原HTTP响应或全市场表。该轮三QA脚本py_compile通过，生产模块未变，123项机制回归仍为此前执行。见[北交所日K参考](P17_BSE_DOM_MARKET_20261001.md)及[深市差异](P17_SZSE_ARCHIVE_20261001.md)。

范围调整前另有脚本可达性诊断：13:28 UTC 单次 HEAD 返回200，独立后续 GET 返回302，均0重试/不跟随重定向，没有取得脚本字节或新增金融参考。证据在`.artifacts/p17_20261001/bse_quote_discovery/redirect-diagnosis.json`及`script-post-head-manifest.json`；HEAD成功不能代表GET或行情采集成功，诊断不计质量分数。该追加诊断未单独完成新编译/重算/发行包检查，原997文件扫描和发行包证明仍仅适用于此前轮次。用户调整范围后停止此路径。

## 工作包

| 工作包 | 当前状态 | 实现与实际验证 |
| --- | --- | --- |
| P1.1 数据契约 | 已扩展 | 日线/利润表旧契约兼容；新增类型化股票/指数/交易所主题与 8 个 DomainDataset，Decimal、单位、缺失、来源及元数据验证。 |
| P1.2 PIT/快照 | 机制及一组真实日期案例通过 | 普通三源实测 observed_at；新增显式合格 CNINFO 两版 `verified_release_date`，发布时间未知、次日零点边界、附件授权及不可变回放通过。无精确日内 verified_release，历史全覆盖未知。 |
| P1.3 Provider | 三源首版接入 | Tushare 日线、利润表及6扩展Dataset；CNINFO 公共索引/PDF、限定四家公司11请求的显式旧码身份资格及 SHA 固定资格的两文件离线历史利润导入器；AKShare 当前名称/近期新闻/HTML。无已验证同口径三源 fallback。 |
| P1.4 执行可靠性 | 回归通过 | 有界时间/分页、授权隔离缓存/合并、共享限流；三表24次/分钟54次持续132.515秒通过，最高80及跨日未知。原三实时函数改单页一次尝试、最多100页/10000行/120秒；完整源分页校验不代表网络成功。 |
| P1.5 存储 | v2 及持久回放通过 | 版本迁移追加 record_kind、不重写旧 payload；JSON/PDF/HTML 内容寻址。持久卷实际重启后三源378记录、旧P1.7快照及新增25股75组/149源Artifact、11组18PDF、218财务比较回放保持。 |
| P1.6 测试/CLI | 扩展回归通过 | 最新隔离PostgreSQL123/123、0跳过，含11数据库集成；AKShare捕获/读取CLI增加完成依据及源Artifact ID。原真实PDF导出/权限/禁止覆盖保持。 |
| P1.7 真实联调 | 扩大样本有实证，整项未通过 | 原450/666证据保持，归档及单日补充后531一致/27差异/108未验证；新增25股注册2550行情/225财务单元，行情1944一致/72差异/462缺参考，财务218一致/7缺独立口径，72预期停牌缺行单列；489持久记录/488事实回放通过。通用历史映射/版本范围及三表跨日仍缺。 |
| P1.8 扩展数据域 | **首版冻结样本验收通过** | 16/16 请求、378 持久记录/375 可见事实，16/16 财务原文值、24 日历开市标记、13 PDF/6 HTML、重启授权/PIT/哈希回放通过。新闻限已采集的近期范围，覆盖未验证。 |
| P1.9 AKShare 七接口 | 部分完成 | 四项有真实表；原三实时函数新有界分页及源证据机制通过合成回归，三接口23列映射核对。15:48真实复测均ProxyError，各1尝试0重试，无完整表；旧小页不计通过。 |

上述 P1.7/P1.9 的整项状态按原验收范围记载。剩余项已转入后续补充，不阻塞当前日频首版验收，仍不计为已通过测试。

P1.7 见 [原执行记录](P17_ACCEPTANCE_RUN_20260930.md)、[官方参考扩展](P17_REFERENCE_EXTENSION_20261001.md)及[行情/持续调用验证](P17_MARKET_AND_QUOTA_20261001.md)，P1.8 见 [实施与验收](P18_IMPLEMENTATION_AND_ACCEPTANCE_20261001.md)。[2026-09-30 P1.8 失败审查](P18_ACCEPTANCE_RUN_20260930.md)仍保留。

## P1.7 本轮扩大分层样本

- [分层采集与核对](P17_FORMAL_SAMPLE_20261001.md)：5572当前股票、108停牌元数据及5557条9月24日成交量作为选样依据；9月25日休市空响应及Decimal检查器失败保留，不充当历史证券池/独立真值。
- 25股排除原六股，五板块各3股及10只特殊层。冻结plan SHA e98a23c65a1f073ebcda264ad138076ff53b711400709ed46bdc894388b2e0f5。当地17:00:33–17:03:38共50daily/25income，一次HTTP尝试/调用、零重试/缓存，最小2.5秒、任意60秒最多24次。
- 504为返回候选数；最终快照489条不同记录（日线413、利润76），PIT选择488条事实，75组回放、149源Artifact和来源/scope/采集前不可见通过。所有普通来源observed_at，没有用交易/报告日期倒填历史可见性。
- 20只沪深官方参考取得，1536/1536在预登记来源精度内一致（1461完全相等），SSE1200/SZSE336；深市旧窗口432、BSE510，共942参考缺失，原2550行情分母不缩。原六股450/666另列，不混为全市场99.5%认证。
- 原停复牌PDF核实600301四日/000016八日缺行，共72字段位置；初始缺失报告保持，补充资格只判预期无行情，不计数值匹配、不升级PIT。603207/688710/301600上市日期原文核实，920016上市公告书成功空仍未证明。
- 全75财务期参考预登记后取得113份PDF，62期成功、12失败/1空；初次仅附件回放、不评分的旧清单保留。进一步[财务原文核对](P17_FORMAL_FINANCIAL_VALUES_20261001.md)三阶段142→176→180项均精度内一致；180/225，45未验证（39无参考、6无独立印刷口径）。机器辅助行/表头/期间/单位核对，九代表页目视检查，不声称逐页人工审查。
- layout2候选跨行误取费用风险在计分前隔离，未进金融快照；收紧续行并对数值在标签前、银行本集团/本行四列做显式原表抄录。142/176/180各阶段比较文件均保留。四个公开索引诊断发现920110旧年报返回832110；未自动接受别名，其他失败原因仍未知。
- 后续单独冻结瑞丰年报摘要请求，当地18:51:22～18:51:23真实采集1份PDF，1调用/1尝试、零重试/缓存。独立锁定第3页2024年列两字段后比较均一致，累计182/225项；43未验证（36无参考、7无独立印刷口径）。原75期批次不改写，补充后共114份PDF覆盖63期。第3页目视检查累计财务代表页10页；正式DataService持久回放、索引/正文哈希、采集前不可见及错误来源/scope正文拒绝通过，新快照未另行重启。
- 本轮5项CNINFO索引诊断均成功返回：四BSE代码标题空、康佳2025年报两行。康佳2024期有效f_ann_date在2026年，原“2024年报”标题错配；冻结补充计划后当地19:01:55～19:01:56取2025年报/摘要2PDF，1调用/1尝试、零重试/缓存。原文第9页明确差错更正，91/92页合并利润表2024第二列三字段先独立锁定后比较，全一致；累计185/225、40未验证（33 BSE无参考、7缺独立口径）。两PDF持久授权/PIT/哈希及无网络重算通过；瑞丰旧182重放保持。共116PDF覆盖64期，财务目视代表页12页。未倒填修订公开时点，未放宽BSE旧码或声明新快照重启。
- 新QA脚本compileall、采集及各项无网络重算通过；生产模块未改，本轮未重跑完整unittest，119项全通过仍是前轮隔离机制回归。三表跨日及P1.9三实时失败不变。

## P1.7 最新北交所限定身份补充

- [旧代码身份与财务参考](P17_BSE_IDENTITY_20261001.md)：官方代码表四行和三则切换通知经实际渲染DOM读取，封存限定投影及带时区观测时间；不是原HTTP响应或全市场历史映射。佳先股份切换为2025-05-06，其余三家为2025-10-09；没有按代码数字或orgId猜映射。
- `QualifiedCNInfoIdentity`固定资格SHA、四个官方QA依据、四公司/11请求、scope/orgId/日期窗口/标题；每条旧码索引校验具体切换日期，原始旧码及资格字节保留在源索引。默认Provider仍严格同码。金融来源仍CNINFO，资格不倒填历史available_at。
- 当地19:30:14～19:30:42，冻结11请求全部非空、11Provider尝试、零重试/缓存，共18PDF；Provider尝试不是底层HTTP总数。33项原文列/期间/单位先固定后比较全部一致，累计218/225、零不一致、7缺独立对应口径。按SSE/SZSE/BSE为101/72/45；收入/归母/总收入为74/75/69。原75期113PDF批次及142→176→180→182→185阶段不覆盖，累计134PDF覆盖全部75期，代表财务页目视16页。
- 7项未验证：601009三期营业总收入；601528一季报营业收入、半年报/年报营业总收入；600500年报营业总收入。银行同一印刷收入行不重复冒充另一字段独立真值。
- 最新生产变更回归离线123项112通过/11 PostgreSQL跳过；隔离数据库123项全通过、0跳过。compileall/pip check及源码包构建通过，合成测试不计金融真值。
- 专用验收容器`stock-research-p17`核实命名卷`stock-research-p17-data`及127.0.0.1绑定后实际重启；11组18PDF身份/PIT/授权/哈希与218项比较通过。全部25股75组/149源Artifact/488事实、旧113PDF、180/182/185阶段、日期案例四边界两版本及P1.8十六组/375事实质量回放通过。证据`.runtime/p17-bse-persistence-restart.json`，日志`p17-bse-post-restart-{bse,formal,p18,financial}.log`。
- 前节“未取得官方代码正文、185/225、生产模块未改及未另行重启”均为该历史阶段结果；本节记录后续实际完成项。三表跨日、942行情缺参考、920016上市原文、通用历史版本范围及三实时接口门槛不变。

## P1.7 深交所历史归档及单日补充

- 实际读取官方行情页、报表脚本和归档页，确认1815_stock_snapshot的旧日查询返回归档提示，1815_stock按单日期读取历史表；量额为万股/万元、所有交易方式汇总。12源文件哈希复核通过，8资源失败保留。
- 计划SHA52001627fe1ad264b4d2b6affe21d8bce3c71c7a0a41cf9cfd40834a8ce82dfe在批次与数值比较前固定。当地20:06:46～20:10:30，90HTTP尝试、89行、零重试/缓存；000001在2024-09-30一次worker失败未取得参考。配置monotonic2.5秒、UTC起点最小差2.487659秒，任意60秒最多24次，非Tushare配额证明。
- 540位置严格436一致/98差异/6缺参考，89行356价格字段全一致；量额80一致、41量/57额差异。两批分母分别合并：新增行情1896一致/72差异/510缺参考/72预期停牌缺行，原666位置526一致/26差异/114未验证；财务218/225保持，不能宣称全市场99.5%。
- 56项正差不足末位100股/元，42项是创业板21日量额成对负差；截位与交易方式差异待独立证明。000016金额96元差的官方XLSX仍为同一两位小数文本，没有更高精度。未放大容差、填补2024盘后数据或自动修改金融值。
- 源字节、授权DataService旧快照/来源Artifact及严格比较无网络重算保持；compare/extension按预期退出2，属于可重复的未通过结果。三个QA脚本compileall通过，生产模块未变，不重记此前123项全回归为本轮新执行。证据szse_history_discovery/szse_archive，日志p17-szse-archive-*.log。
- 以上为原90请求历史阶段。后续补充计划SHA0fb69d72e90a3754f090beb70594dfe36093e100a28f004291f6538108858508，当地20:28:41～20:28:43取得原失败一日，1尝试/0重试/0缓存，5一致/1差异；当前540位置441一致/99差异/0缺参考，360价格全一致、42量/57额差异。原666当前531一致/27差异/108未验证，其余分母不变。
- 当地20:37:43～20:38:57从官方大宗汇总及其实际明细链接取得宁德时代2024-09-26汇总1行/协议成交4行，印刷量额之和一致；解释大部分差额，仍有3054股/635583元未闭合，不能由残差倒推盘后固定价格量额。17份源文件哈希及诊断无网络回放通过；单日严格比较退出2，三个变更QA脚本py_compile通过。生产模块/金融值/容差未变，本轮未重跑全套机制回归。

## P1.7 北交所官方日K参考补充

- [独立参考报告](P17_BSE_DOM_MARKET_20261001.md)：官方股票页链接进入丰光精密个股页，日K图实际点击提示，逐日证券/日期/标签/单位可见；没有读取内部图表状态或猜API。公开脚本两次独立有界请求均失败，后次明确302且未跟随；失败清单保留，不能判历史数据不存在。
- 原五股/85证券日/510字段参考计划SHA6a233c99345232c2adc59b8208b8f9daed7e527447c57fdc7e47bd6ba4927b7c，价格0.005元、量额半印刷步50股/元；9月15提示发现样本先见，其他值在Tushare比较前固定，不作盲样统计保证。
- 当地21:06:39～21:15:20取得920510的2026-09-15～24八开市日，21:17:32封存限定DOM投影SHA/Artifact 5e632a3120bec09fe9b0ba4573877f8d5d802e629e3b93ce60a3f3dd81e80cd1。不是原HTTP字节或全市场表，不升级历史available_at。
- 48/48在原精度内一致，32完全相等；原授权DataService固定快照/源附件/PIT读及哈希重算保持。当前25股行情1944一致/72差异/462缺参考/72预期停牌缺行。原1896/510及其他阶段不覆盖，财务218/225与原六股531/27/108保持。
- BSE原510分母仍48一致/462缺参考，其余4股近期及5股旧窗口共77日待补；本批返回0不能代表P1.7或Phase 1通过。三个QA脚本py_compile及无网络回放通过，未重跑全套unittest，生产模块未变。

## P1.9 前轮有界分页

- [分页及复测报告](P19_BOUNDED_PAGINATION_20261001.md)：原三个AKShare函数在隔离worker使用有界分页助手，保留原URL/筛选/字段和SDK映射；单页一次尝试、最多100页/10000行、单页2MiB、进程硬截止120秒。完整性要求源总数稳定、覆盖所有页、无重复/截断，成功源页只按实际捕获时刻可见，读取源附件也受权限/PIT/哈希约束。
- 合成SDK映射测试首次发现东财自动f140/f141未保留导致列长度错误，依据旧真实小页的字段修正，原三接口全部23列映射核验通过；不是实时金融验证。旧快照不变，只有合格新分页可标源总数覆盖，市场全集/报价新鲜性仍未知。
- 原初轮失败及修正轮均保存；当地15:48:01–15:48:04三接口各1HTTP尝试、0重试，ProxyError且未取得HTTP响应。不能判为完整表通过，也不能由错误类确定网络根因。后续时间校验/CLI显示变更由119项回归验证，没有追加真实成功证据。

## P1.7 本轮日期精度历史版本

- [真实两版案例](P17_RELEASE_DATE_PIT_20261001.md)：CNINFO 300122 的2024原摘要与2026更正公告，官方索引日期/证券/公告ID/附件URL/PDF哈希及具体合并利润字段共同资格核对。应用固定资格SHA，普通日期和今日 Tushare 响应不自动升级。
- `verified_release_date` 保留 `published_at=NULL`，最早披露次日零点（+08:00）可见。四个公开前/后、更正前/后边界通过，历史system=0、入库后可见、来源/scope/附件授权通过；更正归母净利润实际在PDF第9页，新逐字段引用纠正旧探索清单的第8页错误，旧文件保留。
- 2次无网络导入，3物理记录对应2文件版本，旧原版快照追加后不变；持久容器/命名卷实际重启后回放通过，同时原P1.7的9/120记录及P1.8十六组回放通过。精确日内首次发布时间和全市场资格仍未知，四字段不加进原666项质量分母。
- 本轮真实北交所官网分时页单次HTTP403，归档 `.artifacts/p17_20261001/bse_discovery/page-manifest.json`；没有行情参考，不计质量通过。

## P1.7 本轮行情与持续调用

- 原六股/两个行情窗口/三个财报期、666个指标单元和旧快照不变。沪市三股306项全参考、深市两股近期96项参考、财务48项，去重共450项；原27项行情与新沪市参考重合，不重复加分。分层SSE/SZSE/BSE为330/111/9，仍有216项无参考。
- 深交所默认响应只有201行，较早窗口108项仍缺；北交所行情102项未取得。16项成交量初次采用半股精度而失败，整数手来源只能支持半手50股容差；保留旧失败及事后规则修正，96项精度内一致（66项完全相等）。未证明全市场准确率或特殊层覆盖。
- 六股三表×三轮，54/54非空、54尝试、零重试/缓存命中；实际起点跨度132.515秒、最小间隔2.5秒，任意60秒最多24次。54快照和字节哈希、采集前不可见、来源授权回放通过。只证明本次配置速率，普通CLI默认速率、账号最高80、三表跨日及长期SLA仍未认证。
- 上轮新脚本与预登记规则在scripts/evaluation，官网行情参考及持续调用证据在.artifacts/p17_20261001。当轮只改QA脚本、运行回放及compileall；本轮日期资格实现另改生产模块并重新运行111项回归。

## P1.7 前轮财务扩展

- 参考采集计划预先归档：初次 18 请求中 13 个取得 23 PDF，4 个空结果、1 个失败保留；明确列出缺失对象后补充 5 请求全部成功、7 PDF，共 30 PDF，为六股三个财务期间提供官方参考。
- 48/54 财务单元独立比较全部一致；按 SSE/SZSE/BSE 为 24/15/9。银行六个营业总收入字段没有独立印刷口径，不把营业收入别名重复计为真值。原行情 27 项保持，合计 **75/666 一致，591 项未核对**；未证明广泛准确率或新上市/停牌样本覆盖。原 35/666 历史结果未改写。
- 920118 的官方索引日期比 Tushare ann_date 早一天，双源日期均保留。索引零点不是准确发布时间；anns_d 实测业务码 40203 权限不足，无真实 verified_release。
- 标准 Tushare 日线/利润表 Provider v2 先保存所有请求字段返回行，再筛选窗口；包含字段顺序、行数、业务码和调用起止时间。真实日线 9 行、年报 123 行（选中 1 行），2 调用/2 尝试/0 重试，归档无 Token。不能由此宣布持续配额通过。
- 原 P1.7 质量/更正核验、9/120 条旧快照、P1.8 十六请求及新标准归档回放通过；来源授权与采集前不可见保持。证据在 .artifacts/p17_20261001，细节见上述扩展报告。

## P1.8 真实数据与质量

- 预先归档 `evaluation/p18_20261001_sample_plan.json` 后执行。`attempt2` 当地 2026-10-01 00:32:33–00:33:19：16 逻辑请求/16 尝试、全部非空，0 重试。主证据 `.artifacts/p18_20261001/attempt2.json`；样本成功不证明持续可用性/配额。
- Tushare：沪深日历 24、两股复权 17、000300.SH 指数日线 9、399300.SZ 月度权重 300、三公司资产负债 3、现金流原始记录 6。三对现金流数值相同，仅 update_flag 不同，保留两行血缘、查询各返回一行事实；数值冲突不会静默合并。
- CNINFO：公共 HTTPS 索引及原始 PDF 13 份，包括 000001 年报与 300122 原摘要/更正文件。根据标题不自动推断修订关系；全部文件按本次采集时刻可见。
- AKShare：当前名称表和 stock_news_em 返回近期搜索结果；原始关键字搜索含“600000 股”的其他公司文章，按正文公司提及/正确限定代码过滤后保留 6 篇、排除 4 篇。摘要不作为全文，正文为匹配标题的源 HTML；名称核验仅适用于当前列表，公司提及不代表新闻排他归属或因果。
- 财务独立 PDF 对照 **16/16 一致**：平安银行年报 PDF 页 122/123/134/135、浦发摘要页 3、宁德时代摘要页 4。字段采集后选取，不是盲样统计认证。参考值锁定在 evaluation，PDF 保存在 P1.7 原文归档。
- 375 可见事实共 404 指标单元，归档响应到字段/单位映射、资产负债/现金变动恒等式、300 权重粒度与合计、24 个官方日历开市标记及 19 份文档字节检查全部通过。404 映射检查不计入独立金融真值准确率。
- 重启持久 PostgreSQL 后，16 组采集前可见数 0、未授权来源可见数 0、错误 scope 拒绝、快照和源字节哈希不变；旧 P1.7 首/末快照 9/120 条及原哈希保持。真实 CLI 合法 PDF 导出与原文件 SHA 相同，非法权限被拒绝，已有导出不覆盖。
- `attempt1` 原始捕获及当时回放证据保留：首次回放暴露 update_flag 事实歧义，随后发现新闻证券归属误匹配并修复。旧 p18-1 新闻未确认归属，现不作为合格股票新闻返回；最终验收使用 attempt2，不使用旧轮结果充当通过证据。

## 三源权限与覆盖边界

- Tushare Token 已仅配置项目忽略的 `.env`，不写 Windows 用户变量。曾实测 stock_basic 5569 行、weekly/monthly、三表、宏观及扩展接口可达；news 返回 40203，suspend_d 空表不证明停牌覆盖。用户称三表80次/分钟；本轮只验证24次/分钟、54次持续调用，80最高及跨日仍未验证。
- CNINFO OAuth 与基本信息接口曾成功；p_info3030 返回 VIP 权限不足。当前公告通过公共站点正式接入，不把新闻 API 权限失败视为已解决，也不声称已接入其 API 历史 PIT。
- AKShare 1.18.97 七接口历史实测：上交所总貌 8 行、深交所总貌 14 行、机构参与度 43 行、关注指数 30 行；三项实时接口 ProxyError/超时。此前候选 15 项中 14 返回表、13 非空；index_zh_a_hist 两次 ProxyError。局部 NO_PROXY 完整实时调用仍超时，没有修改系统代理。10-01 追加诊断：全 A 股原路由小页 HTTP 200/1 行，但标准全表捕获仍 TransientProviderError；创业板/科创板原节点及显式 82 节点均 ProxyError，三类直连均 ConnectionError。小页不能证明全市场捕获通过。此次新增新闻正式 Provider 不解决这三项行情问题。详见 [AKShare 验证](AKSHARE_VALIDATION.md)。
- P1.8普通扩展真实值为observed_at：报告期、ann_date、月度权重日期、新闻标称时间和未来日历生效日不证明历史版本可见；限定两文件资格的日期精度路径另列。当前复权不是总收益保证，月度权重不是每日历史成员。NULL不填零；北交所日历及通用历史别名未扩展；限定四公司11公告旧码资格另列。查询coverage仍not_verified。
- 业务 Tool 与 Calculation 算子属于 Phase 2；不因 Tool 尚未实现而额外判 Phase 1 失败。逐域输入判断见 [覆盖评估](SOURCE_COVERAGE_AND_PHASE1_ACCEPTANCE.md)。

## 测试与环境

| 实际执行 | 结果 |
| --- | --- |
| Phase 1 末轮离线 unittest，PYTHONPATH=src | 123项：112通过、11 PostgreSQL项因未设置专用测试DSN跳过；日志p17-bse-identity-offline.log；当前 Phase 2 最新回归见本文首节。 |
| Phase 1 末轮 scripts/test-postgres.ps1 -Image 57c72fd2a128 | **123项全通过、0跳过**；含11项实际PostgreSQL集成，隔离容器仅绑定127.0.0.1、测试后回收；日志p17-bse-identity-postgres.log。 |
| 最新重启持久验收库及 P1.8/P1.7 回放 | 25股75组/149源Artifact/488事实、新11组18PDF/218项比较、旧113PDF与180/182/185阶段、P1.8十六组/375事实及日期案例保持，PIT/授权检查通过。 |
| run_p17_quota.py --verify-only / SSE、SZSE 精度及 combined_quality | 54个持续调用快照通过；450/666独立对照在来源精度内一致，原深市精度失败按预期重现。 |
| run_p17_release_date.py --verify-only，持久库重启后 | 两文件/四字段及四个日期边界通过，来源/scope/附件授权、历史system=0、旧快照保持；精确日内时间未验证。 |
| run_p19_bounded_spot.py --label corrected --verify-only | 冻结失败结果复核：三接口均失败、成功表回放0；不算完整行情验收通过。 |
| check_p17_reference_extension.py --verify-only / check_p17_operational.py | 财务 48/48、合计 75/666 一致；两份 Provider v2 原始归档、采集前不可见及未授权正文拒绝通过。 |
| check_p18_quality.py --verify-only | 重新计算与封存质量证据一致，16 独立财务字段一致。 |
| check_p18_cli.py | 实际 CLI 查询/PDF 导出/权限拒绝/禁止覆盖通过。 |
| check_p17_rural_bank_reference.py / --verify-only | 新年报摘要2字段一致，合并原180为182/225；43未验证。持久库快照/附件授权/PIT/哈希及无网络重算通过；新增两脚本compileall通过，未重跑完整unittest。 |
| check_p17_rural_bank_reference.py --case konka / --verify-only | 新后续年报2024比较列3字段一致，累计185/225、40未验证；两PDF授权/PIT/哈希及无网络重算通过。旧瑞丰182重算保持，新代码打印列检查通过。 |
| 旧身份发现阶段 discover_p17_bse_identity.py --verify-only / compileall | 当时5项公开索引原始Artifact重算保持，未接受身份别名/金融事实；两QA脚本compileall通过，该阶段生产模块未变。后续显式资格及123项完整回归另列。 |
| compileall、pip check、CLI --help | 执行通过；用 setuptools 构建源码发行包并检查：新增域/迁移文件存在，本地凭据、.runtime、.artifacts 未包含。 |
| 北交所限定身份资格及独立数值复核 | check_p17_bse_qualified_references.py及bse_financial_values_review无网络重算/重启后保持；11期18PDF、33新增字段全部一致，累计218/225、7未验证。 |
| 深交所历史归档及严格差异复核 | 原90尝试89行及436/98/6保持；单日1尝试成功后540字段441一致/99差异/0缺参考。源17文件哈希及大宗4行诊断回放通过，严格单日补充重算退出2，不算质量验收通过；三个QA脚本py_compile通过。 |
| 北交所限定DOM日K参考及比较 | 丰光精密原登记8日/48字段全部精度内一致，32完全相等；固定字节SHA、原授权快照/源附件及无网络重算保持。原BSE510分母中462缺参考；三QA脚本py_compile通过。 |
| 历史基线 | 原75项67通过/8跳过；扩展104项94通过/10跳过；日期资格111项100通过/11跳过；有界分页119项108通过/11跳过，各轮隔离均全通过。当前123项。 |

最新日志为 `.runtime/p17-bse-identity-offline.log`、`p17-bse-identity-postgres.log`；原119项日志p19-bounded-final-offline.log和p19-bounded-final-postgres.log保留；此前日期资格111项、扩展104项及P1.8日志保留。合成fixture不作为金融真值。Python3.11.9、PostgreSQL16.14；持久验收库stock-research-p17使用命名卷stock-research-p17-data，本地DSN忽略、仅127.0.0.1绑定。测试跳过不代表未实现数据库，命名卷有持久化。

P1.8 当轮对 src/scripts/evaluation/docs/README 和 P1.8 原始证据共 120 个文件进行项目 Tushare Token/验收库密码的精确扫描，匹配 0；没有打印凭据。未安装 build 模块，源码包使用已有 setuptools 的构建后端成功生成与核验。

P1.7 扩展轮重新扫描 src/scripts/evaluation/docs/README 及 P1.7/P1.9 新证据共 233 个文件，项目 Tushare Token/验收库密码匹配 0；源码包 42 个条目，模块/迁移齐备，密钥文件和运行目录未包含。初次包检查规则误匹配合法 tushare.py，修正规则后复核通过，未改动包内容。结果在 .runtime/p17-extension-secret-scan.json 与 p17-extension-distribution-check.json。

行情/持续调用轮最终扫描333个文件，项目Tushare Token/验收库密码匹配0；新官方参考封装单次实测与URL拒绝通过。证据为.runtime/p17-market-quota-final-secret-scan.json和.artifacts/p17_20261001/exchange_http_check，未改写旧捕获代码哈希。

本轮日期资格变更扫描src/scripts/tests/docs/evaluation/README及新日期/BSE证据共118文件，项目Tushare Token/验收库密码匹配0；源码发行包复核新合格文件Provider与schema_v2存在，密钥文件和运行目录排除。证据为.runtime/p17-release-date-secret-scan.json和p17-release-date-distribution-check.json；compileall及真实日期案例最终回放通过。

本轮实时分页变更扫描src/scripts/tests/docs/evaluation/README及新分页失败证据共112文件，项目Tushare Token/验收库密码匹配0；发行包44条目，新分页及资格模块均存在，密钥文件/运行目录未包含。证据为.runtime/p19-bounded-secret-scan.json和p19-bounded-distribution-check.json；最终日期案例及分页失败结果复核通过（成功实时表仍0）。

扩大样本财务180项阶段扫描src/scripts/tests/evaluation/docs/README及formal/formal_discovery共735文件（含PDF），项目Tushare Token/验收库密码匹配0；证据.runtime/p17-formal-secret-scan.json。瑞丰摘要补充后按相同范围另扫747文件，匹配0；证据.runtime/p17-rural-bank-secret-scan.json，未输出密钥。

康佳比较期及BSE身份索引诊断后同范围扫描769文件，项目Tushare Token/验收库密码匹配0；证据.runtime/p17-konka-secret-scan.json。新增QA查询/比较/封存文件不含密钥，完整回归与发行包未在本轮重跑。

最新北交所限定身份实现后扫描src/scripts/tests/evaluation/docs/README及formal/formal_discovery共847文件（含PDF），项目Tushare Token/验收库密码精确匹配0，未输出凭据；证据`.runtime/p17-bse-identity-secret-scan.json`。更新README后重建源码包并检查45条目，新cninfo_identity、qualified_income、akshare_spot及两SQL迁移存在，本地密钥文件/.runtime/.artifacts排除，包内精确密钥匹配0；证据`.runtime/p17-bse-identity-distribution-check.json`与构建日志`p17-bse-identity-distribution.log`。

最新深交所归档阶段扫描上述源码/测试/文档/计划及formal/formal_discovery、szse_archive、szse_history_discovery共967文件，项目Tushare Token/验收库密码精确匹配0，未输出凭据。更新README后源码包构建及45条目检查通过，必需Provider/两SQL迁移齐备，密钥文件与运行目录排除，包内精确匹配0；证据`.runtime/p17-szse-archive-secret-distribution-check.json`及`p17-szse-archive-distribution.log`。此次只改QA和文档，123项全回归仍为前轮实际执行。

单日补充/大宗诊断轮扫描相同范围并加入szse_archive_gap，共986文件，项目Tushare Token/验收库密码精确匹配0；新源码包45条目、必需Provider/两SQL存在、密钥文件及运行目录排除、包内精确匹配0。证据`.runtime/p17-szse-gap-secret-distribution-check.json`、构建日志`p17-szse-gap-build.log`。仅QA/文档修改，未重跑完整unittest。

按已确认近期新闻范围，P1.8 attempt2冻结快照及原文质量无网络回放再次通过，复用原16请求/375可见事实，没有新采集或扩大覆盖声明。日志`.runtime/p18-recent-scope-replay.log`与`p18-recent-scope-quality-replay.log`。

北交所日K参考轮扫描上述范围并加入bse_quote_discovery/bse_dom_reference，共997文件，项目Tushare Token/验收库密码匹配0；更新README后的新源码包45条目，必需Provider与两SQL齐备、密钥及运行目录排除、包内匹配0。证据`.runtime/p17-bse-dom-secret-distribution-check.json`及`p17-bse-dom-build.log`；无网络比较日志`p17-bse-dom-replay.log`。此前隔离123项机制基线保持，本轮没有重跑完整unittest。

## DeepSeek 独立适配器

按用户授权提前接入配置的阿里云百炼 HTTPS 端点及 deepseek-v4-flash-0731，不替换模型。历史一次 llm-check 返回 OK、finish_reason=stop、模型名一致：输入 13、输出 1、合计 14 Token，计时 1000 ms；单次不是 SLA。test_api.txt 不输出、不复制、不进分发；当时 Tool Calling 与Runtime未开始，后续固定Single Runtime及本轮JSON动作动态策略已实现，真实验收见首节；原生tool_calls未接入。

## 后续补充与交接

1. P1.7 后续补充：归档量额99项差异（其中25股72项、原六股27项）及单日大宗残差尚未闭合；北交所25股计划其余77日/462字段参考及7财务独立口径待补。原六股另有108未验证。更多历史版本/精确日内依据及已验证24次/分钟配置的三表跨日复测保留，当前不阻塞首版。
2. P1.9 后续补充：三项实时完整表仍失败，保留 ProxyError/超时及分页证据；以后取得真实成功表才能验收该扩展，当前不阻塞首版。无需继续此会话网络诊断。
3. 保留历史新闻、北交所日历、历史证券名称/代码映射及更细财务字段为未完成扩展；首版近期新闻依已确认范围验收。
4. Phase2固定Single与Phase3有界首版/新合法v2限定验证结果保持；Phase4 M1有界首版已交付，下一工作包P4.3/P4.4受限Child/领域委派尚未实现。本轮初始提前结束表现及601009未复测保留。现有快照/scope/源Artifact及命名卷继续复用；Phase5/6额外实验、交易未启动。广泛Phase3认证列后续，不阻塞M1、不改旧分数。
