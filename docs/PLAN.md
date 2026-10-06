# 实施计划与验收

基线日期：2026-09-28。目标阈值均为建议，不是实测结果。实际结果见 STATUS。2026-10-01 用户授权的首版范围调整优先于下文原广泛验收目标；原测试结果及质量分母保留。

**当前授权（2026-10-06，Asia/Shanghai）：Phase 6 首轮实际瓶颈诊断、一个最小版本化优化及有界验收。** 本次用户明确执行授权覆盖此前不自动进入Phase6的边界；下文Phase5/P4的结果、失败、分母、paid wire、Checkpoint和冻结文件均保持历史事实。先审查真实Trace、Context/Parallel Telemetry及付费账本，再选择一个有实测依据的确定性无损表示或授权内复用瓶颈；不扩大并行启用范围、不进入下一阶段。

本轮事前验收设计：固定12000 UTF-8字节，不做阈值调参、LLM摘要或有损裁剪；模型输入变更使用显式新版本，默认、旧协议/身份/恢复保持。每次读取/缓存/披露/恢复重授权，原finish、no_progress、根原子预留、Parent headroom、cancel/deadline和未知付费处理保持。先离线机制、权限/PIT、兼容恢复及历史只读回放，再冻结已有合法案例、baseline/candidate、同请求/源/oracle/评分/顺序/独立预算；最多3案例各两运行（最多6），campaign96父子决策/576000记账Token/1800秒，Parent原8/12/48000/240秒、Child显式v3且原3/1/18000/120秒、根16/18/96000保持。付费intent先持久化，未知结果停止外发、不重发/释放、不复用旧预算。失败保留并仅在剩余原额度与运行上限内做有依据的最小修复。

验收核对完整Fact/Claim/Evidence/合法不足、全部必需执行检查、PIT/cutoff/snapshot/grants/lineage/预算及零模型/Provider/Checkpoint追加只读回放；质量、已知Token、记账Token、累计预留、实际字节及模型网络/工具/排队/读取/验证延迟分别报告（不可分解项明确未知，不重复相加嵌套时间）。三个已知案例不是六个独立样本，Phase5三个任务九路线不是九个样本；历史失败不能作为等质量性能baseline，修复复验独立新任务0。20% Token/15% P95仍仅历史候选目标，小样本不宣称P95改善/统计优势，无可证实收益保留原默认。具体瓶颈、版本和冻结哈希在真实外发前补录，最终另交Phase6报告。

首轮选定瓶颈为现有模型视图内仍重复的精确元数据列表（derived Observation的Claim/Evidence列表、来源期间与共同窗口等）；真实paid wire诊断已确认重复，当前已有Lazy Disclosure及行metadata去重的收益不重复归功新优化。仅新增显式`dynamic-parent-parallel-v3` / `dynamic-context-view/v2`无损表示，baseline为显式Parent v2，Child都为v3；保留v2可信revision执行反馈，旧默认及所有旧wire不变。新表示必须严格回解为旧v1视图再核对catalog，不能缩写数值/改变事实/披露闭包。先以原paid状态核验净字节收益（含新增解码说明），不冒充新模型Token收益。

冻结首轮603207与688184两个已有合法案例各baseline/candidate一次，共4运行；request/question/源/授权/oracle逐字沿用Phase5对应parallel输入。顺序为603207 baseline→candidate、688184 candidate→baseline，固定预热/非随机条件与模型时段混杂另列。最多额外2运行仅在失败后另行冻结同案例修复配对并继承本轮96/576000/1800账本与deadline，不自动消费、不扩大额度。两个case为已知非盲性能复验，独立新任务0；920110仅历史诊断，首轮不宣称其candidate已验证。

**Phase6首轮限定验收已完成，四真实运行4/4及零模型/Provider/Checkpoint追加回放4/4通过。** 同状态无损wire净省3414字节，实际baseline34305→candidate32730Token（少4.59%）；Runtime37313→37329ms，未证实延迟改善。两case已知非盲、独立新任务0，不声称P95/统计优势、20%Token目标或扩大并行。只接受显式表示版本，默认/12000/原所有安全与预算保持，不进入下一阶段，余2修复槽位未用。完整结果见[Phase6首轮记录](PHASE6_FIRST_ROUND_20261006.md)。

外发前最终离线828项814通过/14数据库跳过、隔离PostgreSQL828/828及19/19历史零网络回放通过；中间失败日志另保留。Phase6实际计划已冻结于`.artifacts/phase6/first-round-20261006/plan.json`，SHA `2b80c8622949757194d298155f315bdac23fd2d25da1edd228bd23630edab5e1`；73份独立源码副本与source-manifest SHA `e53c9a0ecf90f23e66bc40a5b26f3f02fe480dad2ccc8f77df316a2a95262eb6`封存，密钥文件0。新Dataset SHA `b8ed9e61c6d1f2695df974e80efce7de6af14368ab4b9e17675a642285b30c84`，Trace manifest SHA `34ed3ca9e228e43056e0b6ee9f81e2bc041660b489ad1d57b047f2ea0fa1a4a2`；原Phase5 8/9、Parent v2同案例1/1及全部历史失败/分母/paid wire/Checkpoint不改。

## Phase5及P4历史记录（当轮授权与结果保留）

**当前授权（2026-10-06，Asia/Shanghai）：推进 Phase 5，必要外部模型请求在本会话全部批准。** P4.5 已通过限定真实闭环，现开始实际 Dynamic/Multi 路线定向评估。复用同一 DynamicRuntime、无损 Context、Financial/Market Child v3、Registry/Executor、Evidence/Trace/Checkpoint；不新增 Provider、金融 Dataset 或领域 Agent，不启动 Phase 6。此前“不自动进入 Phase 5”是已履行的阶段边界，本次明确请求授权进入。

**后续修复与复验授权：若验收不通过，设计最小修改方案，并尝试重新验收。** 原688184失败定位为Parent将已检验的假设不足误作执行完成。最小方案为显式`dynamic-parent-parallel-v2`：从Runtime原revision检查生成短`control.execution`，显示pending/can_finish及精确合法下一步JSON候选；原协议输入不增字段，候选不执行工具或扩大权限，不改finish/no_progress/预算/DAG。先机制与兼容回归，再事前冻结原688184同请求/源/模型/Child v3/局部限制的新单项复验；独立新campaign最多16父子决策/96000记账Token/480秒，Parent仍240秒，12000字节不变。原8/9及所有原件保留，原冻结62文件先按SHA复制至独立目录；新复验单列、独立新任务0，不将原分数重写9/9。失败则保留并基于实际wire继续修复，不自动Phase6。

**该最小修复及限定同案例复验已完成：1/1通过。** 显式Parent v2/Child v3完整真实parallel→calculation→hypotheses→verification→finish；五项执行检查passed，6Facts/12Evidence及原非正基数不足保留，9决策/16937记账Token/unknown0/未结算0，最高11318/12000，实际Child模型I/O重叠。新报告只读回放1/1相同，794/794隔离回归通过。原8/9与`bounded_opt_in_not_supported`保持，复验独立新任务0、其余case的v2未实测，不改原9/9启用决定或默认；Phase6未启动。新冻结计划SHA `695fb5f6633e9989b015314d8bfe526486daa250ad848034204e00435e238731`，明细见STATUS与[Phase 5记录](PHASE5_EVALUATION_20261006.md)。

**本轮已完成上述有界Phase 5评估并冻结实际Trace；扩大并行启用门槛未通过。** 原计划一次真实9运行，direct3/3、serial3/3、parallel2/3，合计8/9；688184并行Parent未完成verification而连续提前finish，被原检查拒绝并no_progress停止。全77父子决策/157821已知暨记账Token/unknown0，9/9只读回放一致，775/775隔离回归通过。决定为 `bounded_opt_in_not_supported`；保留新失败与旧分母，不改默认/12000，不启动Phase6。样本非盲、三case非九独立任务，不认证统计优势；实际与边界见[Phase 5记录](PHASE5_EVALUATION_20261006.md)和STATUS。下文事前设计与历史授权保持。

本轮事前范围为三个新 Dynamic validation 任务：603207 普通财务同比、920110 北交所输入、688184 非正基数。均使用已知 Phase 3 合法不可变财务/行情快照，非盲、非独立金融真值；每项直接工具、串行 Child、并行 Child 三路线，共九个真实运行，独立任务分母为三。业务请求、PIT/cutoff/snapshot/source grants、必需检查与确定性 oracle 同项一致；路线指令和工具可见集差异显式记录。直接路线使用既有 compact Parent Spec 的受限普通工具集，不能称为原生 Single Spec 的隔离因果实验。

独立新 campaign 上限 **120 次父子决策、720000 记账 Token、2400 秒绝对时限**；每个 Parent 局部仍 8 决策/12 工具/48000 Token/240 秒，Child 仍 3/1/18000/120，串行/并行根仍 16/18/96000；12000 UTF-8 字节固定。先冻结任务/源码/授权/模型端点哈希/预算/评分和每路线顺序，再派发；每次付费 intent 先持久化，未知保留且不重发。失败不删分母、不事后修改任务或增加预算。新 Trace Dataset 是评估证据目录，不扩张金融数据层。

事前启用规则：九个运行都满足原必需检查、确定性数值及源绑定/PIT/授权/血缘验证，根预算未知和未结算均为零，九个零模型回放一致，三个并行运行都有真实 Child 模型 I/O 重叠，才支持既有两个独立必要来源范围的显式 Child v3 opt-in。不修改默认协议，不自动选择路线；其他情况保留失败并不扩大启用范围。质量、完整父子已知/记账/预留 Token、wall/section 延迟、context/parallel telemetry 分别报告；小样本不声明统计优势、不调阈值。旧 P4.5 原失败及 v2/v3 同案例复验单列历史诊断，不能计作新任务。实际执行见 STATUS 与本轮独立记录。

**最新工作已完成：P4.5 Child推进的版本化修复与同案例真实复验。** 旧v1/v2身份/输入/checkpoint保持；v2修复复验0/1保留，新增v3精确动作字段/可信格式反馈后同输入同预算真实复验1/1完整通过，P4.5限定功能验收通过。最终746项隔离回归全通过；Parent全部六项必需检查、7 Fact/7 Claim/12 Evidence、实际Child模型并发及零模型回放通过。原独立任务0/1不改，修复复验独立新样本0。不自动进入Phase 5，不据少量Trace调12000阈值；细节见[修复记录](PHASE4_P45_CHILD_PROGRESS_REPAIR_20261005.md)和STATUS。下文P4.5首次未通过状态是当轮历史记录。

**最新授权（2026-10-05）：P4.5 Parallel Multi/M3。** 复用已完成P4.1–P4.4及无损Context Builder，在同一DynamicRuntime上实现Financial/Market两个独立必要源Child并行。先审查真实代码，再做最小版本化修改、离线/隔离数据库机制回归、冻结一项新的真实联合任务及零模型回放；最终结果以STATUS和[P4.5独立记录](PHASE4_P45_IMPLEMENTATION_20261005.md)为准。以下“P4.5未启动”仅描述历史轮次，不限制这次明确授权。

P4.5交付包括可信固定DAG、root-budget/v3原子组预留及Parent剩余局部预算保留、独立Child状态与绝对deadline、取消/迟到丢弃、按原授权/PIT/Evidence规则回父、每分支崩溃恢复及幂等canonical merge。显式新CLI入口`--parallel-domains`保留直接/串行兼容，旧模式/身份/失败/分母不改。固定12000 UTF-8 bytes、P4.4全部无损压缩及canonical对象必须保持；Context/Parallel Telemetry只记录，不据少量Trace调参数。机制合成夹具与真实功能分开，真实调用失败必须留档，不提高预算或改问题覆盖失败。阶段完成与否按独立验收记录判定，不自动开展Phase 5。

后续顺序固定为：P4.5开始采Trace → Phase 5积累实际Dynamic/Multi数据并冻结代表性Trace Dataset → Phase 6 threshold sweep/replay，结合Success/Token/Latency/Safety重新校准context cap。12000的正式统计校准留给Phase 6，本轮不声称它是最优值。

首次P4.5验收历史（保留）：680/680隔离PostgreSQL回归、原六报告6/6无模型回放；当时新冻结600500任务两Child确实并发，但Financial重复读取/no_progress，Parent partial，功能0/1，失败回放相同，P4.5当轮未通过。原问题/预算/Spec和失败未覆盖。其后有依据的Child诊断、v2失败及v3完整通过分别记于本文件首节、STATUS与独立修复记录；Phase 5未自动启动。

**当前路线调整（2026-10-04，Asia/Shanghai）：优先交付具有动态规划能力的 Single Agent，再逐步研究 Multi-Agent。** 用户明确不再开展 Fixed 与 Dynamic、Agent 与固定 workflow 的效率/效果对照实验。本节及新增 Phase 4 计划优先于下文历史阶段安排；取消这类对照作为交付或阶段入口的门槛。既有固定流程用于兼容、回放和回归，不再作为研究比较对象。

此前独立规划轮次仅修改文档，现已履行。2026-10-04 用户追加要求“阅读 PLAN/ARCHITECTURE/CONSTRAINTS，推进 Phase4”，本轮开始 P4.1–P4.2 M1 动态首版实施；随后明确本会话向远端 LLM 发送数据默认批准，无需再确认。仍按最多3个任务/24次决策/144000 Token的有界演示执行，不复用旧调用额度。先完成 M1，再按本文顺序推进后续工作包，不先补齐广泛 Phase 3 质量认证、全市场数据或正式 Benchmark。Phase 3 原冻结完整验收未通过的事实、分母和分数保留；新功能自身的权限/PIT/数值/预算/恢复缺陷仍必须修复。实际结果见 STATUS。

2026-10-05 用户明确追加“收口 M1 typed premature finish rejection，再实现 P4.3 最小 Agent-as-Tool”。本轮只做一个串行 Financial Child；不进入 P4.4 Router/多个领域 Agent 或 P4.5 并行。新独立验证最多两项已有公开快照任务、20次模型决策（父子合计）、120000记账Token、720秒，不复用10-04已过期账本；原失败保留。具体实现和实际验收见 STATUS。

同日后续用户明确授权“执行P4.4编写与检查验收”。新本轮实施Financial/Market两领域串行委派M2：同Parent模型用普通tool动作选择直接或AgentTool，至多每域一个Child；不增加独立Router模型，不进入P4.5并行、输入UI/自然语言请求编译、新Provider或交易。新Parent身份及root-budget/v2保持旧P4.3回放；根默认16决策/18工具/96000记账Token，父局部仍8/12/48000/240秒，每Child至多3/1/18000/120秒。验收冻结两项已有合法公开快照任务，独立campaign最多28决策/168000记账Token/720秒；机制、真实路由及恢复结果只按实际记录。

实际本轮P4.4代码及542/542隔离工程回归通过，原真实功能1/2、路由2/2；一次原额度内的明确JSON动作字段新run仍在hypotheses后触及12000字节上下文上限，定点0/1。合计25决策/38188实测记账Token，原失败/截止/预算保留。完整财务混合闭环尚未通过；下一步需版本化动作纠错与上下文配置/控制文本方案、事前冻结后复测，不能删Evidence或重置旧账本，P4.5暂不启动。实际证据见[本轮记录](PHASE4_P44_IMPLEMENTATION_20261005.md)和STATUS。

同日新请求授权 **P4.4 Context Remediation 阻塞修复**。新`dynamic-parent-domains-v2`保持12000 UTF-8字节上限、原模型和原002363冻结请求（744字节question）；旧v1身份/消息/恢复入口保留。完整类型化Observation、Claim、Evidence存入原授权Checkpoint目录，公共scope/metadata去重，模型视图保留全部Claim值及完整引用目录；默认按当前首个未执行检查选择Evidence闭包，严格`disclose`动作可在原预算内读取已有对象。重复question/plan/schema控制信息每轮只放一次，不用摘要、截断或数值改写。单元/回归须覆盖可逆编解码、范围绑定、授权撤销、恢复/未知结果、披露计账和不冒充检查完成；真实定点要求原7 Facts/12 Evidence及来源一致，calculation→hypotheses→verification→finish完整闭环。独立新campaign只含一项，最多16父子决策/96000记账Token/480秒，Parent局部240秒等原限额不变；新结果另列，旧1/2与定点0/1不改。该包不开展Phase 6全面缓存、性能阈值或质量统计优化，P4.5继续未启动，实际结果仅据STATUS。

本包已完成：606/606隔离回归、原冻结002363新真实复测1/1，全部7 Facts/12 Evidence及来源一致，最高10247/12000字节，8父子决策/15608实测Token；新报告1/1及旧五报告5/5无网络恢复一致。原1/2与定点0/1不改，P4.5/完整Phase 6未开始。冻结与实际证据见[本轮记录](PHASE4_P44_CONTEXT_REMEDIATION_20261005.md)，不将单项功能复测泛化为质量/性能认证。

| Phase | Goal / Modules | Input → Output | Dependencies | Acceptance / Metrics | Risks |
|---|---|---|---|---|---|
| 0 | 问题边界、数据契约、指标字典、Provider 调查、Benchmark | 需求/来源文档 → Case 规范和真值规范 | 无 | 六层至少 60 种子；关键字段完整率 100%；真值可追溯 | 真值/授权未具备 |
| 1 | Provider、Schema、PIT、PostgreSQL、快照、Artifact、基础缓存/合并请求 | 契约/授权来源 → 可重放数据层 | 最小 Phase 0 契约 | 首版按下文调整范围验收；机制回归、真实采集及持久回放通过；≥99.5% 广泛质量认证移入后续 | 历史版本/配额及覆盖仍有边界 |
| 2 | 共享 Runtime、Registry/Executor、聚合 Tool、Evidence/Trace/Checkpoint；固定概览 | 数据层 → Fixed Single | Phase 1 首版 | 已有限定验收见 STATUS；原 L1/L2 ≥95%、计算 ≥99%、血缘 100% 目标及边界保留 | 不将固定步骤称为动态规划 |
| 3 | Research、Hypothesis、Claim Verification、Context；固定研究 | 固定 Single → 有界 Research Single | Phase 2 | 原 L3/L5 ≥85%、ESR ≥98%、Hallucination ≤1%、关键锚点 100% 的完整验收未通过；不再作为 M1 前置补证项目 | 数据/任务前置条件限制仍需显式报告 |
| 4 | 先 Dynamic Single Loop，再 Agent-as-Tool、Child、领域委派与并行 | 已有 Runtime/研究工具 → 动态 Agent 首版 → Multi 原型 | 复用 Phase 2/3 已实现能力及合法输入；不等待原 Phase 3 广泛质量认证 | M1 功能闭环与安全验收；随后 M2/M3 父子权限、预算、取消和证据验收；无 Fixed/Dynamic 对照 | 循环失控、重复调用、委派失真 |
| 5 | 后续 Dynamic/Multi 定向评估与启用决策 | 可运行的动态 Single/Multi + 实际委派任务 → 有范围的启用决定 | Phase 4 可运行原型；不阻塞 M1 或 Multi 原型建设 | 仅围绕 Multi 增量价值评估质量/成本/延迟/安全；事前确定范围和上限，不要求旧 A/B/C 或全套消融 | 小样本不能宣称广泛优势 |
| 6 | Lazy Disclosure、缓存/压缩、阈值优化 | 可运行 Agent 的 Trace/实际瓶颈 → 优化配置 | 先取得可用 Agent，按瓶颈安排 | 原 Token -20% 或 P95 -15% 为候选优化目标；Success 降幅 ≤1pp、PIT 0；不是 M1 前置门槛 | 缓存/压缩失真 |

## 当前实施主线：先交付 Dynamic Single（2026-10-04 已开始 M1 实施）

Phase 1 可靠数据 → Phase 2 固定 Single/共享 Runtime → Phase 3 固定 Research/验证工具 → **P4.1–P4.2 动态 Single 首版 M1** → P4.3 Agent-as-Tool/串行 Child → P4.4 领域委派 M2 → P4.5 并行 Multi M3 → Phase 5 定向评估 → Phase 6 优化。

Fixed/Dynamic 是执行策略，Research 是研究能力，Single/Multi 是运行组织方式。Research Single 现有实现仍是固定策略；动态 Agent 必须根据本轮 Observation 决定后续行动。Agent-as-Tool 复用同一 Runtime 核心；第一次受限 Child 即构成最小 Multi，领域路由与并行是后续扩展。

### M1 产品范围与动态能力

- 输入：一个单股自然语言研究问题，加可信应用确认的证券、窗口、cutoff、PIT、来源/快照 manifest 和权限。用户指定问题目标，模型拆解目标、安排步骤、选择工具、依据结果调整计划。关键范围缺失或问题超出可用能力时明确提示澄清/不支持，不猜证券、事件或时间，不用事后数据补齐。
- 首版复用已有行情、财务、基准等聚合读取，以及确定性计算、既有假设检验和 Claim Verification；仅将必要调用入口整理为有 Schema 的工具。现有可用字段/算子决定研究边界，不要求先做新 Provider、正文抽取、行业/估值工具、任意代码执行或完整自然语言实体解析。
- 执行：`Model → 结构化动作 → Runtime 校验 → Tool → 类型化 Observation → Model`，直到完成或受控停止。首轮生成简短计划及第一步；后续模型可以改变工具顺序、选择合法的另一条取证路径、报告不足或结束。不得先把固定全套工具执行完再让模型选重点，并把这种流程标为 Dynamic。
- 协议：首版使用指定模型现有 Chat Completions 文本接口，返回严格 JSON 动作（工具名、受限参数/引用、计划更新或 finish）；这是应用层动态工具调用，不声称原生 function calling 已接入。不以原生 `tool_calls`、新框架或更换模型为前提；动作格式错误必须记录并受预算限制，不能静默退回固定流程冒充动态成功。
- 数值和假设结论由工具计算/检验，模型只决定动作和引用；工具参数只能选择已绑定的数据/算子引用，不能提交任意公式、事实值、scope、快照或新 cutoff。模型的计划摘要是控制信息，不直接成为报告事实；不记录模型隐式推理。
- 输出：中文 Markdown/精确 JSON 报告、可核查 Claim/Evidence、可见的计划更新与工具执行记录、用量及停止原因。模型 finish 只是结束请求，Runtime 独立验证事实及事前确定的必需检查；重规划不得删除必需检查以获得 completed，未完成则明确 partial/insufficient。
- 产品入口：已扩展 `research --workflow dynamic --question ...`，manifest 继续绑定可信范围与必需假设；保留 overview/research 与旧 Spec 恢复。新动态策略有独立 Spec/Checkpoint 身份。`--preview-model`只生成首轮消息，不执行固定取数；动态执行显式使用`--with-model`。question表达目标，可信应用需事先确认其与绑定证券/窗口/检验相符；completed表示这些必需检查完成，不宣称任意自然语言解析或语义全覆盖。

### Phase 4 工作包与交付顺序

| 工作包 | 最小交付 | 完成条件与依赖 |
|---|---|---|
| P4.1 Dynamic Single-Agent Loop | 在既有 Runtime 中增加动态执行策略；严格动作 Schema；复用 Registry/Executor；取数/计算/检验结果回传模型；逐轮 Evidence/Trace/Checkpoint | 实际出现 Model→Tool→Observation→Model，后续工具由模型选择；从第一轮就强制权限、PIT、预算、deadline 和取消 |
| P4.2 Replanning / Stop / M1 交付 | Observation 驱动的计划更新；重复/无进展检测；受控停止；恢复账本；CLI 与中文报告 | 与 P4.1 合成一个交付里程碑 M1；完成下列功能/安全检查和少量真实演示即可交付，不等待比较实验 |
| P4.3 Agent-as-Tool / Child Run | M1 上封装一个领域 AgentSpec 为 Tool，先串行 Child；独立状态/消息，结构化结果和父子证据关联 | 同一 Runtime 核心；创建第一个 Child 就收窄工具/数据授权、预留根预算、传播取消；Child 不再 spawn |
| P4.4 Router / Domain Delegation | 从一至两个实际需要的领域开始；父 Agent 使用同一动作协议选择直接调用普通 Tool 或委派 AgentTool | 与 P4.3 形成可运行的领域 Multi 原型 M2；不预建完整 Agent 群或独立 Router 模型，不等待 Phase 5 统计实验 |
| P4.5 Parallel / Root Budget / Cancellation | M2 基础上增加有依赖的并行调度、根预算原子预留、排队/取消/迟到结果与部分失败处理 | 形成 M3；根预算和取消在 P4.3 已存在，此包验证并发正确性，不重复建设 Runtime |

### 2026-10-05 M1 收口与 P4.3 实现范围

- CLI动态默认显式 `single-dynamic-v2`，提前finish返回 `required_checks_pending`/`pending_checks`，修正计决策/Token/无进展账本；`--dynamic-version single-dynamic-v1`保持旧恢复。库的 `DynamicSpec()` 仍为历史v1，使用v2需显式版本。
- `--financial-child`仅适用于dynamic/v2，使用独立 `dynamic-parent-financial-v1` 身份；Parent仍有普通工具，最多启动一个 `financial-child-v1`。Child自身动态选择financial读取及finish，独立状态/消息/局部计划，复用同一个DynamicRuntime循环，不增加Router或第二运行引擎。
- Child仅回传财务来源结果、Evidence记录/附件/快照/实际读取调用引用、状态/缺口/Usage；父导入`financial` Observation后执行既有计算、假设检验和独立数值验证。首版不让Child生成研究Claim或扩展财务算子。
- 父局部上限维持8决策/12工具/48000Token/240秒；根父子合计最多12决策/16工具/72000记账Token。Child最多3决策/1工具/18000记账Token/120秒，启动前完整预留，deadline不晚于父/root。所有失败与未知额度计账，恢复核对Trace/账本/Child结果并重查来源。
- P4.3验收覆盖交集授权、只读原绑定/PIT/快照、禁止Child spawn、取消/迟到丢弃、额度不足零Child派发、未知付费/Child不自动重发、结构化结果/父子Evidence关联及无网络完成回放。合成测试只证明机制；两个真实模型任务仅证明本次功能边界。

M1 已实现的默认配置为最多 **8 次模型决策（包含 finish/格式修正）、12 次工具尝试、48000 总 Token 预算、单次输出 1024 Token、240 秒绝对 deadline、单次模型上下文 12000 UTF-8 字节**；不是实测 SLA。所有输入输出及失败尝试计账，合法已知实际用量替换本次预留，未知/无效用量保留预留；累计派发预留与预算记账分别报告。上下文用逐轮有界的类型化状态视图，不复制无限历史；不能容纳必需证据就停止，不以丢失证据或提前做有损压缩换取继续运行。

已无新证据时重复相同动作不重复派发；返回明确结果并计入决策轮，连续两轮无进展终止。缺证据可在同一授权 manifest 内改选有用工具；权限/PIT/完整性违规及取消立即停止；瞬时 Provider 重试仍只有原责任层。每次付费派发前保存 intent，未知结果不得自动重发；恢复沿用原总预算、原绝对 deadline 和授权检查。

### M1 最小验收与停止扩张规则

验收回答“动态 Agent 能否工作且守住边界”，不回答“Agent 是否优于 workflow”。功能样例在执行前固定任务目标和成功条件，不建设新的大规模真值或对照 campaign。

1. **闭环与重规划**：离线协议 fixture 覆盖至少两步工具调用、Observation 导致下一步改变、已满足目标后 finish、证据不足停止；fixture 只证明机制。Trace 必须能区分模型决策、工具结果和程序强制验证。
2. **必要安全回归**：覆盖非法动作/未知引用、越权、PIT、快照变更、伪造数值、删除必需检查、重复无进展、轮数/Token/deadline/取消、崩溃恢复和未知付费结果；适用既有测试继续通过。离线命令为 `PYTHONPATH=src` 环境下的 `python -m unittest discover -s tests -v`；跳过项如实记录，受影响的持久化能力另作针对性回放。
3. **少量真实模型演示**：在已有合法快照中选择最多 3 个端到端任务，覆盖可完成的多步研究、Observation 驱动的路径调整、证据不足受控结束。合计最多24次模型决策/144000预算记账Token（实施前冻结为`max_tokens_accounted`，已知替换预留、未知保留；累计派发预留另列）；定点修复不重置总账本/deadline。使用用户配置端点和指定模型，不新增金融采集、不复用旧耗尽额度。本会话数据发送已明确默认批准，实际22次及失败保留见STATUS；旧规划本身不当作已执行记录。
4. **验收记录**：报告功能通过/失败、每次用量、数值/引用核验及实际停止原因；至少有真实多步闭环与路径调整证据才能称为可用动态首版。缺少真实验证时只记“机制通过、真实验证未完成”；失败保留，修复相关缺陷后定点复测，不扩大为 Fixed/Dynamic 对照或广泛统计认证。
5. **交付即转下一步**：M1 达到上述范围后提供可运行命令、报告和 Trace，后续开发进入 P4.3/P4.4 的 Multi 原型问题。原 Phase 3 补证、全市场覆盖、60/300 任务集、六类消融、成本最优性证明均不在 M1 关键路径。旧结果不改；额外能力按实际需求另列。

### Phase 5/6 的新定位

Phase 5 留给未来已可运行的 Dynamic Single 与 Multi：针对真实委派任务判断领域隔离、分工和并行是否带来收益，记录完整父子质量/成本/延迟/安全。不再安排 Fixed/Dynamic、Agent/workflow、细/粗工具三组必做对照，也不把置信区间或全套消融作为 M1/M2/M3 原型交付前提。是否扩大 Multi 使用范围应依据事前声明的目标、安全和资源上限；若未来要宣称统计优势，再单独规划所需样本，不能由演示推断。

Phase 6 在可运行 Agent 出现实际瓶颈后再做上下文压缩、缓存和 Lazy Disclosure。基础授权缓存、无损引用上下文、去重与预算从早期保留，不延后安全能力。

## 历史授权范围

以下保留各轮当时的范围与执行记录；其中“本轮”“后续”按所在日期理解。当前优先级以上方 2026-10-04 动态首版规划为准。

用户已授权写入 Markdown 文档并开始 Phase 1。原先“仅设计、禁止业务代码”的限制已由本轮实现请求解除；研究业务和阶段边界仍然有效。

追加授权（2026-09-28）：通过 `test_api.txt` 接入 `deepseek-v4-flash-0731`。提前落实独立 Model/Transport Adapter 与 CLI 联调入口，属于 Phase 2 前置基础能力；不代表 Phase 2 已整体启动或 Phase 1 已验收。模型接入不依赖 PostgreSQL 或 Tushare 凭据。

追加授权（2026-09-28）：在 Tushare Pro 接入前，以 AKShare 对指定的交易所总貌、A 股/创业板/科创板实时行情、机构参与度和用户关注指数七个接口做受控采集与联调。不同数据粒度先保存为观察时点的独立不可变捕获快照；尚未验证口径前不作为 Tushare `DataRecord` 的自动 fallback，也不反填历史可见时间。

追加授权（2026-09-28）：读取项目本地 `tushare.txt`，仅在项目本地环境配置 Tushare Token。用户提供的可访问范围为股票列表、日/周/月行情、三大财报（用户称 80 次/分钟）和宏观经济；具体接口权限、配额及数据口径须逐项实测，不据此宣布 P1.7/P1.8 完成。

追加范围确认（2026-10-01）：用户接受新闻首版为“实际采集后可见的近期新闻”，历史新闻列为后续扩展。P1.8 用 AKShare 近期索引与对应原文 HTML，校验当前公司名称或含正确交易所后缀的证券代码；索引摘要不冒充全文，当前名称不作为历史名称映射。历史新闻权限不足不再阻塞此首版范围，但 P1.7 的历史版本验收要求继续保留。

## Phase 1 工作包

### 2026-10-01 首版范围调整与 Phase 2 授权

用户要求跳过两项剩余工作、验收 Phase 1 并推进 Phase 2，以尽快取得初版效果。两项指 P1.7 剩余真实数据验证（广泛独立质量、更多历史版本及三表跨日验证）和 P1.9 三项实时完整表。上述工作转为后续补充，不再阻塞日频研究首版，不标记测试通过。

- Phase 1 首版范围：已接入的三源日频观察数据、财务核心字段、日历/复权/指数、公告和采集后可见的近期新闻；保留限定两版日期精度历史案例。历史新闻、任意历史 PIT、全市场覆盖及实时完整行情不作首版承诺。
- 首版验收依据：契约/PIT/权限/不可变快照机制及隔离 PostgreSQL 回归通过，真实三源采集与持久重启回放通过，P1.8 冻结样本通过。原 ≥99.5% 广泛真实质量目标移入后续认证，不声称已经达到；未核对及存在量额差异的输入仍须显示来源和覆盖边界。
- 运行约束继续有效：普通数据不得倒填历史可见性，所有读取授权、缺失不填零、无静默 fallback、无 LLM 填数；有限调用及已验证的保守速率保持，不以跳过配额验证为由提高并发。
- 据已有证据，Phase 1 按上述首版范围验收通过。原全范围 P1.7/P1.9 未通过事实和冻结证据保留；不改历史报告。
- Phase 2 建议先交付单股研究概览：明确证券/窗口/cutoff/快照，Market 与 Financial 聚合 Tool，确定性计算，受控 DeepSeek 解读，带证据与执行记录的报告。先采用固定有界计划，再增量扩展自然语言及工具循环。Phase 2 整体成功率门槛仍需独立评测，不能由一个示例宣布全部通过。
- 用户随后明确要求本会话只修改 PLAN 和 STATUS 后停止，Phase 2 在其他会话推进。本会话没有保留新增 Phase 2 代码、没有生成研究报告或执行 Phase 2 联调；原独立 DeepSeek 适配器保持。后续会话应读取本节作为新的范围授权，CONSTRAINTS 中旧的阶段限制据此解释；PIT/权限/不可变性等约束继续适用。

1. P1.1：可安装 Python 包、统一证券/查询/记录/时间/权限契约。
2. P1.2：严格 PIT 版本选择、public/system 模式、不可变快照。
3. P1.3：Provider Registry、可注入 Transport、Tushare daily/income 首批适配、单位规范化。
4. P1.4：有界重试/超时/限流、同请求合并、授权隔离缓存、失败不缓存。
5. P1.5：PostgreSQL schema/repository、内容寻址 Artifact，内存测试仓库。
6. P1.6：合成数据测试与 PostgreSQL 隔离集成测试；离线 smoke 命令。
7. P1.7：真实 Provider 凭据与配额联调、历史原始版本验证及质量抽检。
8. P1.8：扩展交易日历/复权/指数、资产负债/现金流和官方公告/新闻适配。
9. P1.9：AKShare 七接口受控捕获、字段契约、有限执行时限、范围隔离快照与真实接口联调；进一步规范化进入研究查询需按粒度与口径另行验证。

原工作包安排先落实 P1.1–P1.6 的可验证垂直切片。P1.7 不得用模拟测试冒充完成，P1.8 已按近期新闻首版范围取得通过证据；2026-10-01 的范围调整不将 P1.7/P1.9 原失败或未验证项改写为通过。

## P1.8 首版验收口径（2026-10-01）

- 七类扩展对象分别为交易日历、复权因子、指数（日线及月度权重）、资产负债表核心字段、现金流量表核心字段、官方公告 PDF、近期新闻原文；指数使用独立主题标识，不能伪装成股票。
- 所有新来源保持 `observed_at`；未来交易日历是已采集的安排，不代表未来已发生行情。当前复权因子、指数权重、报告公告日期和新闻标称时间不证明历史版本公开时间。
- 三源适配进入统一 DataService，固定 scope、来源授权、快照、带时区 cutoff；正文读取还要验证记录可见及附件属于该记录。
- 冻结样本后真实调用必须全部非空；数据库重启后快照/附件哈希保持、采集前不可见、错误来源/范围被拒绝；扩展契约及 PostgreSQL 回归全通过。
- 至少做官方原文独立数值抽检，分别记录对照分母与未核对项。抽检及单样本联调不证明全市场准确率、任意历史窗口覆盖或持续配额。
- 结果见 [P1.8 实施与验收](P18_IMPLEMENTATION_AND_ACCEPTANCE_20261001.md)；P1.8 首版通过不能替代 P1.7/P1.9 或 Phase 1 整体门槛。

## Phase 2 固定 Single 首版（2026-10-01 本次执行）

本次用户明确要求“阅读 plan 和 status 文件，执行 phase2”，解除上一会话的仅文档停止要求。按已批准的固定计划交付切片建设，阶段目标不因一个示例而自动验收。

| 工作包 | 交付与状态 | 验证边界 |
|---|---|---|
| P2.1 契约与 Fast Runtime | 已实现 AgentSpec、严格请求 manifest、固定读数→计算→模型重点选择→校验→报告 | 单股、一次模型尝试；不接受自由自然语言任务或动态 Tool Calling |
| P2.2 Registry / Executor | 已实现六类聚合 Tool、可见/授权/Spec 交集、按域读取与本次 wave 去重 | 同 wave 聚合复用仍重新授权及验哈希；无跨进程工具并发合并 |
| P2.3 确定性计算 | 已实现已观察价格变化/回撤、因子调整价格变化、同日期基准比较、最新可见三表核心字段、同报告期正基数同比 | 未复权不是总收益；不插值、不补缺、不把累计值当 TTM；覆盖始终 not_verified |
| P2.4 Evidence / Trace / Checkpoint | 已实现数值来源链、预算/事件账本、本地 SQLite 追加哈希链、进程锁与恢复重授权 | 单机可信应用；本地读取在边界检查 deadline，不能强杀阻塞数据库 I/O；未知模型结果不重发 |
| P2.5 产品入口 | 已实现 research CLI 与Markdown/JSON报告；一次真实联调后，用户另批准25次固定质量批次并完成 | 默认模型关闭；已履行的单次/25次具体授权不扩展为未限定重复调用 |
| P2.6 评测 | 合成20/20、真实离线50/50；另25次真实模型质量24/25=96%，展示修复后25/25；123数值/263 Evidence/25回放；最新隔离回归172/172 | 固定market/income透明代理规则达到本批门槛；非专家盲样、不替代全部域/自然语言/全局统计质量认证 |

可运行首版已交付，并于 2026-10-02 按用户明确批准完成一次真实 DeepSeek 联调：指定模型一致、312 Token、严格证据选择 verified，回放没有新增模型调用。Phase 2 的整体 ≥95% Task Success / ≥99% 计算目标尚未以独立真实任务集验收；后续扩展真实独立评测。自然语言解析、动态工具循环按实际需求增量建设，不预建 Phase 3 因果/假设研究。

实现和执行证据见 [Phase 2 实施记录](PHASE2_IMPLEMENTATION_20261001.md)。

2026-10-02 本轮验收复现并修复模型重复 JSON 键、Token/输出预算校验与未完成恢复 deadline 三类缺陷，五项新增回归及真实冻结任务复测通过。**固定 Single 首版按有界单股概览范围验收通过**；广泛真实模型任务质量整体验收仍未完成，不因本轮模型关闭的 50 个任务而宣布全局 Success。详见 [Phase 2 验收与修复](PHASE2_ACCEPTANCE_20261002.md)。

后续同日用户要求进一步验收任务质量：报告表达50/50后，具体事实首次外发被自动审批拒绝，用户随后明确批准原25次清单。实际25次指定模型调用：原始任务质量24/25=96%，达到该批95%门槛；唯一重复收入重点在展示层透明合并后25/25，原模型评分和事实不改。123/123数值、263 Evidence、25/25无网络回放，最新隔离172/172；固定Single限定任务质量验收通过，透明代理规则不替代专家盲评、全局统计成功率或持续SLA。见 [任务质量验收](PHASE2_TASK_QUALITY_20261002.md)。

## Phase 3 有界 Single Research（2026-10-02 本次执行）

用户明确要求“阅读plan和status，执行phase3”，授权本轮建设 Research、Hypothesis、Claim Verification 与 Context。沿用固定 Single Runtime；Phase 4 Multi、Phase 5 完整对照、Phase 6 优化及交易不在本轮范围。

| 工作包 | 首版交付 | 验收边界 |
|---|---|---|
| P3.1 Research 契约/状态 | StudyRequest/StudySpec；单股研究与显式记录锚定的事件复核；读取前持久化固定计划，读取→计算→检验→验证→综合 | 固定目录和有限来源，不接受自由因果问题或动态检索/工具循环 |
| P3.2 Hypothesis | 复权端点影响、同日期基准方向、同报告期收入/利润同比下降、正利润负经营现金流、事件顺序五类检验 | supported/unsupported/conflicted/insufficient 均带规则、Claim、反证及缺口；支持不是因果 |
| P3.3 Claim Verification | 独立 Fraction 重算；检查完整 Claim 集、数值/单位/公式/窗口、原始值与来源版本/快照、PIT/血缘及假设状态 | 校验转换而非供应商准确率；不把 LLM 或自由正文当事实源 |
| P3.4 Context | 无损类型化引用视图，显式证券/cutoff/PIT/口径/值/时间与版本引用；本地完整 Evidence；上下文超限停止模型步骤 | 不丢 Claim 以满足预算；源标题/正文不进入模型，不构建向量库或长期记忆 |
| P3.5 报告/恢复 | research --workflow research；本地精确外发预览；v3完整候选与严格归属验证，保留v1/v2恢复；ScopeGrant逐源重授权；报告另标系统核对补充 | 默认模型关闭、每运行最多一次指定模型；本轮37+43两批分别批准，无重试/替换；旧分数不改 |
| P3.6 评测 | 有界明示样本通过：v3真实43/43原始选择，14/14聚焦任务实质完成，287数值/613 Evidence/43回放；隔离227/227 | 原129假设的110不足不改；模型从程序候选中选择，非开放式研究能力或广泛专家质量认证 |

预算默认 8 次聚合工具尝试、120 秒、16000 Token 保守预留、512 输出 Token、12000 字节模型上下文，均受原运行绝对 deadline 和恢复账本约束。事件统计使用中国市场日频收盘时刻 15:00；精确披露时点按严格事前/事后划分，日期精度从次日开始，并排除披露日作为事前端点。该统计不是事件影响估计；系统模式仍检查 ingested_at。

本轮交付有界首版，不由合成正确率或缺证据拒答宣布广泛 Phase 3 L3/L5 ≥85%、ESR ≥98%、Hallucination ≤1% 或专家因果质量整体认证。未提供合格锚点和实际对齐行情的真实事件影响、公告/新闻正文提取、行业/估值/流动性等更广假设与真实模型独立质量评测保留待扩展。

实现及实际证据见 [Phase 3 实施与验证](PHASE3_IMPLEMENTATION_20261002.md)。

同日用户追加质量验收并授权DeepSeek API。已完成归档同期投影修复，19/25财务假设可判定，全部129假设仍有110不足。原外发自动审批拒绝后，用户另明确批准修复后29次清单；实际29次指定模型，原质量23/29=79.3%未达85%，175数值/325证据/29回放通过。报告系统核对补充后29/29展示通过，原模型评分不改。默认CLI/生产库尚未自动物化归档投影；下一轮明确覆盖/引用要求的指令方案已保存但未实测，原29次额度已用完。后续保留合法PIT扩展证据对齐和新冻结独立模型验证；不启动Phase4–6或交易。详见 [质量验收与方案](PHASE3_QUALITY_ACCEPTANCE_20261002.md)。

## Phase 3 输入契约与独立评分（2026-10-04）

用户授权依照修改后的独立评审修复建议执行。正式Benchmark冻结前必须通过`benchmark-contract/v1`：核对必需Dataset与真实Provider/snapshot能力、完整成员哈希、scope授权、证券、报告期/窗口、源版本、PIT、明确事件及原cutoff下前后收盘可行性。非法/未知整批拒绝；合法输入缺数据、已知负基数或实际日期不齐不得靠筛选删除。零行捕获需原始精确查询/哈希/时刻证明，不能仅从空snapshot推断Provider不兼容或停牌。

同时保留Frozen End-to-End Request Success和Contract-valid Agent Task Success。原68/952分母及L3 12/62、真实L3 12/37、L5 2/6、新cutoff0/25不改；输入合法14/68，合法子集L3 12/12、L5 2/2，新cutoff条件分母0为not_assessable。小回归子集不是新盲样，不能替代原完整门槛。分别报告contract validity、source support、official accuracy、required-check completion、两类success、critical anchor及hallucination。

已实现single-research-v4结构化不足诊断，CLI新运行默认v4，旧v1-v3恢复显式固定版本。原公式、假设规则、源值及旧模型messages不改。优先四字段官方版本桥通过新独立annotation核对，原254/420保持，新260/414独立报告；剩余官方对应仍未知。验收执行与剩余条件见[修复记录](PHASE3_CONTRACT_REMEDIATION_20261004.md)。未来事件、非正基数替代问题或对齐策略须另版本化和预先冻结，不事后改变旧规则。

### 新合法输入 Benchmark v2（2026-10-04 追加执行）

用户另行授权构建并实际执行新 L3/L5 Benchmark，不回写原68任务。输入契约v2在原Gate上增加冻结原Artifact/full snapshot成员校验、明确事件版本及真实before/after子窗口；全批非法/未知拒绝。38个新Case预先冻结为validation，34 L3/4 L5；不称盲样，independent test为0。正式Agent、Prompt、预算、模型messages与期望行为先固定，一次模型调用/Case，随后独立Fraction及全文Codex Judge，禁止按评分改题或重跑。

新增显式 `single-research-v5` / `profit-change/v1`，只为新 `absolute_profit_change` 问题计算本期同期间累计合并归母净利润减上年金额，保留CNY符号和非正基数；原正基数百分比同比规则不变。CLI默认v4、程序默认v3保持兼容。股票/基准仍exact-date only、禁止插值；合法不足必须事前允许且有冻结原始来源证明，不能普遍把拒答算成功。

本批结果与逐单元判据见[Benchmark v2报告](../.artifacts/phase3/benchmark-v2-20261004/PHASE3_BENCHMARK_V2_REPORT.md)。新合法输入门槛、原冻结端到端指标、官方准确性覆盖分别报告；validation成绩不替代广泛能力认证。完整质量认证的独立样本/官方版本补证另列，不改变本文首节动态M1的规划优先级，本轮未开发Phase4–6或项目Multi。

## 验收与进度纪律（历史记录及持续约束）

2026-10-03完整目标审计继续生效：下面的2026-10-02有界分项通过不等于用户要求的完整Phase3质量验收。本轮补原25股缺失三域，51次官方采集，保持同股/同窗口/五检验，当前cutoff下91/125可判定，34仍不足；原29任务及110不足不改。387数值/847 Evidence、25回放、125撤权、300PIT与25项官方现金流对照通过。六个负同比基数、缺价/日期不齐、未指定事件和原事件时间条件不能靠改分母解决；用户无独立研究参考。完整L3/L5、ESR、幻觉、关键锚点仍未验收，见[完整修复与验收缺口](PHASE3_FULL_ACCEPTANCE_REPAIR_20261003.md)。

2026-10-02 用户请求持续修复质量验收，先按[续修设计](PHASE3_FOLLOWUP_DESIGN_20261002.md)执行v2，31/37仍失败；再按[v3预登记方案](PHASE3_V3_DESIGN_20261002.md)修复完整候选选择，分别获明确批准后执行43次，37回归/6迁移两组均100%原始选择通过。14/14聚焦研究任务完成实质检验、数值/血缘/锚点核对通过，**有界固定目录系统及明示样本验收通过**。原始分数和110证据不足保持，不将29个旧缺数任务计为实质成功，不替代广泛专家研究质量认证；不自动进入Phase4–6。

- Phase 0 的 60 个种子和独立财务真值未齐备时，只能记录“最小契约已建立”，不能宣称 Phase 0 完成。
- 原广泛验收范围无真实凭据/历史版本时不能完成；2026-10-01 日频首版按上述已授权范围验收，未验证扩展不计通过。
- 每个工作包记录实现文件、执行命令、实际结果、未验证事项。
- 安全门槛优先：无越权、无可识别未来证据、无 LLM 填数、无丢失血缘、恢复不放宽权限。
- 使用独立合成 PIT fixture 验证机制；真实准确率必须另行抽检。
- 原会话仅更新 PLAN/STATUS 后停止的要求已经履行；2026-10-02 当前新请求已开始 Phase 3。仍不自动进入 Phase 4–6、Multi 或交易功能。
