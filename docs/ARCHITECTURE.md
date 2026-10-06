# 股票研究 Agent 架构

状态：设计基线 v1；2026-09-28。实现进展以 [STATUS.md](STATUS.md) 为准。

2026-10-06当前明确授权Phase6首轮：基于真实Trace/Telemetry/账本先选一个有依据的最小无损优化；继续复用DynamicRuntime、Registry/Executor、Evidence、Trace和Checkpoint，不引入新Runtime/Provider/Dataset/领域Agent/Router。12000字节与默认/历史身份/恢复、安全和根预算机制冻结；模型输入变更需显式新协议。先机制/权限/PIT/兼容/历史只读回放，再冻结最多3已有案例的版本配对和独立预算后真实验收，最后零网络/零Checkpoint追加回放。不作正式阈值调参、LLM摘要、事实裁剪、扩大并行或下一阶段。后续旧“Phase6未启动”均保持各轮历史事实。

路线修订（2026-10-04/05）：Dynamic Single、P4.3串行Financial Child、P4.4串行Financial/Market委派与无损上下文已交付。同日后续P4.5请求新增独立版本ParallelParentSpec，在同一DynamicRuntime内调度两领域Child；同一Parent模型仍可选直接/串行路径，没有独立Router模型或ParallelRuntime。取消 Fixed/Dynamic、Agent/workflow 对照门槛；历史失败及分数保留，实际验收见 [STATUS.md](STATUS.md)，范围见 [PLAN.md](PLAN.md)。

同日Child推进修复提供显式Financial/Market Child v2/v3，最新验证版本通过CLI `--child-protocol-version v3`选择。Spec默认v1、旧v1/v2 system/payload与checkpoint身份保持；Parent configuration绑定显式Child Spec identity，恢复必须选择同一版本。`child-progress/v1`由已验证的唯一source Observation和不可变required_checks确定性派生：读取执行状态、独立的数据质量缺口、当前合法动作候选及重复反馈。available_tools继续表示授权能力；读取完成后候选finish，覆盖率/历史可见性缺口原样保留。v3增加当前动作必需/禁止键、system末尾精确JSON及invalid_action反馈，FINISH仍强制reason且禁止tool/refs。候选不执行动作、不授予权限、不证明Parent完成；原no_progress、重复拒绝、finish检查及Parent DAG/核验仍决定结果。Runtime/Executor/根预算/恢复/无损Context Builder均复用，Telemetry不进prompt。v2复验0/1保留，v3真实完整并行闭环1/1及零模型回放通过，原失败0/1不改，不自动进入Phase 5。详见独立[修复记录](PHASE4_P45_CHILD_PROGRESS_REPAIR_20261005.md)。

## 1. 仓库审查与决策

初次检查 `D:\workspace\financial analyze` 为空，且不是 Git 仓库；没有已有模块、框架或数据可复用。采用 Python 3.11+ 模块化单体，先建立数据与评测闭环，再建立 Single Agent。逻辑模块不等于微服务。

## 2. 业务边界

第一阶段面向 A 股日频研究：行情查询、确定性指标、基准比较、财务变化、事件研究、历史时点研究。不是自动荐股系统，不建设下单、自动交易、组合调整。缺失或不可验证数据允许输出部分结果或证据不足。不得由 LLM 编造数值。

## 3. 总体分层

用户 → 请求规范化/可信范围绑定 → AgentSpec + 共享 Runtime（固定或动态策略）→ ToolRegistry/Executor → Business Tool → Data Service → Provider Interface → Provider Adapter。

入口工作流选择与领域委派分开：`DomainParentSpec`保持原串行契约；显式`--parallel-domains`采用`ParallelParentSpec`/`dynamic-parent-parallel-v1`，模型可选择直接tool、串行AgentTool或严格parallel动作。每领域至多一个Child、合计两个，Child不能spawn。已有P4.3及P4.4入口和Spec身份保持。

### P4.5：同一 Runtime 内的有界并行

`research/parallel.py`是DynamicRuntime的调度函数，不构成第二套Runtime。Parent状态的`parallel_groups`保存固定可信DAG：financial_branch与market_branch无相互依赖；calculation依赖两者，hypotheses依赖calculation，verification依赖hypotheses。仅ready节点启动。节点持久记录reserved/running/completed/insufficient/failed/cancelled/late_discarded、独立Child run/request/deadline/工具调用/结果摘要/是否提交。两个Child用独立DynamicRuntime、Executor、RunState、messages、plan及本地预算；共享模型适配器、原DataService/Artifact/Checkpoint设施与可信授权，Worker不持有可变Parent状态或根字典。

新`root-budget/v3`在原Parent OS Run锁下由唯一协调器写入。`reserve_children`一次核验并提交两Child最大局部预算，单个checkpoint包含整个事务，成功后才submit；任何一维余额不足则无Child启动。预留额外保留Parent全部剩余局部决策/工具/Token envelope，以免必需检验被Child耗尽。默认根16决策/18工具/96000Token，Parent8/12/48000/240秒，每Child3/1/18000/120秒。v1/v2及旧串行路径不变；新并行Spec的串行路径也检查Parent headroom。没有独立共享账本CAS：并发安全来自既有Run锁、单写者和Worker只能消费已分配局部预算。

Parent收完整Child checkpoint回执后按原规则结算；未知整体回执保留全额，已知停止回执中的未知模型intent保留其Token预留。绝对Child deadline在reserve时冻结，不晚于Parent；恢复不延长、不重预留、已完成不重跑、未知付费结果不重发。取消通过Parent回调与group Event传播，已在途同步I/O受原timeout约束；返回后再检查取消/deadline，迟到数据不提交Parent。合法已提交分支保留在checkpoint，但不足的必需分支不能completed。

Join由Parent重核Child身份/domain/run/request、实际checkpoint结果哈希、tool/provider/SourceGrant、Evidence/Artifact、PIT/cutoff/snapshot及源读一致性；cache/dedup和resume仍重授权。每个源Observation只导入一次，输出键/Child摘要/计算输入及Fact/Evidence构造采用确定性顺序，真实返回顺序另列Trace，不能决定业务优先级。并行机制仍以两个必要源分支为最小范围，未建设任意模型提供的DAG或分布式队列。

P4.4的目录编解码、scope/metadata去重、Claim/Evidence引用、Observation外置与按检查Lazy Disclosure原样复用；旧wire和冻结恢复身份保持。新ParallelParentSpec固定12000 UTF-8 bytes，超限仅生成观测数据并停止，测量用重构视图绝不返回模型派发入口；不删canonical对象、改值或用LLM摘要。

横向能力：PIT、权限、预算、Evidence、Artifact、Checkpoint、Trace、Benchmark。

第一版部署：应用 + PostgreSQL + 本地内容寻址 Artifact Store。内存仓库仅供单元测试。Agent 框架、向量库、消息总线和微服务暂不引入。

## 4. Data / Provider

Tool 不绑定外部 API。Market、Financial、Benchmark、Announcement、News、Calculation 为业务域。ProviderRegistry 管供应商能力、口径、配额和健康；ToolRegistry 管业务能力、Schema 和执行权限，两者分离。

指定的七个 AKShare 接口承担独立数据捕获；当前项目本地已有 Tushare Token，Tushare 日线与利润表适配器已做单样本真实联调。交易所汇总、全市场实时快照和单股热度是不同粒度，保存为独立的观察时点快照，不直接伪装成既有单证券日频/利润表 `DataRecord`。行情/财务长期优先 Tushare；公告优先巨潮和交易所；新闻独立 Provider；AKShare 不是唯一 Ground Truth。Fallback 必须通过能力与口径契约，不能静默更换单位、复权或财务类型。三源当前能力与 Phase 1 验收判断见 [覆盖评估](SOURCE_COVERAGE_AND_PHASE1_ACCEPTANCE.md)。

证券使用稳定 security_id，区分代码、交易所、资产类型、canonical_symbol、公司名称和 Provider 映射。名称和行业的历史有效性需要独立治理，当前名称不是历史事实。

时间字段：trade_date、report_period、announcement_date、published_at、available_at、retrieved_at、ingested_at、revision_id。所有执行 cutoff 必须带时区。日期边界不自动猜测。

两种模式：

- public：重建当时公开信息，必须有内容版本的发布时间证明。
- system：重建系统当时已采集的信息，另要求 ingested_at 不晚于 cutoff。

强制 `available_at <= as_of_date`，选择截止时点可见版本；报告期绝不是公开时间。后续修订不能覆盖旧值。无历史内容证明的 Tushare 当前响应，仅从本次抓取完成时刻视为已知，不用 ann_date 倒填版本可用时间。该保守策略会降低历史覆盖率，但阻止把当前修订值冒充历史值。

不可变快照冻结记录集合；原始结果按内容哈希归档；每条结果保留单位、口径、来源、版本、时间依据、缺失字段和调用链。查询必须指定 scope、来源白名单、快照、cutoff 和 PIT 模式。

### Tushare 标准归档 v2（2026-10-01）

日线/利润表 Provider v2 保存请求字段的全部返回行，再做本地报告期筛选，记录实际字段顺序、响应/选中行数、业务码和带时区调用起止时间。未知额外字段、消息、请求头不归档；请求字段反射密钥或非标量结构时拒绝。旧 Provider v1 内容与快照不重写，新归档可追溯窗口外的返回行，不等于完整 HTTP 报文存档。银行营业总收入若只有营业收入印刷行，不把字段别名算成独立真值；不同来源公告日期均保留，日期差异不改变 observed_at 可见约束。

### P1.8 扩展实现（2026-10-01）

`domains.py` 的 `Subject` 显式区分 equity/index/exchange，`DomainDataset` 新增八个 Dataset，`DomainRecord` 共享原有授权、PIT 和不可变快照链。原有日线/利润表契约保持兼容；PostgreSQL `schema_v2.sql` 追加 `record_kind`，通过 `domain_v2` 标识解码新记录，不改写旧 payload。股票、指数成分和公告分别使用不同事实粒度。

Tushare 扩展适配器提供沪深日历、原始复权因子、价格指数日线/月度权重、合并资产负债和累计现金流核心字段。百分比、手、千元分别规范化成比例、股、元，NULL 保留；`update_flag` 保留血缘，只有数值和其余元数据完全相同的同行可以视为事实等价，标记本身不作为新版本发布时间。权重是月度观察值，不是每日历史成分证明。

CNINFO 公共 HTTPS 公告目录/索引适配器按代码与 orgId 检索，限制窗口、分页和 PDF 数量，保存原始 PDF 字节；不依赖本账号没有权限的新闻 API。AKShare 提供当前名称表及近期新闻索引，正文来自对应固定 HTTPS 原文；当前公司名称或正确的限定证券代码必须出现在标题/文章主体，侧栏及“600000 股”数量不建立证券归属。当前名称只用于当前列表核验，可能漏掉历史别名；公司被提及不说明新闻独属于该公司或造成价格变化。历史新闻不在首版范围。

补充（2026-10-01）：默认公告仍严格校验证券代码。可由可信应用显式配置`QualifiedCNInfoIdentity`，固定审核清单SHA、scope、当前/旧码、orgId、公告日期窗口/标题与切换边界；索引保留原始旧码，并内附资格原始UTF-8/哈希和实际官方DOM投影。记录保持observed_at，资格观测不得晚于捕获，索引/PDF读取继续受相同授权/PIT/哈希验证。现仅四BSE证券/11个参考请求，独立交易所身份QA不引入第四金融数据Provider、不提供全市场历史证券池或公告历史可见性。见[限定身份验证](P17_BSE_IDENTITY_20261001.md)。

文件正文通过 `DataService.evidence` 授权读取：先执行相同 scope/source/snapshot/cutoff/mode 查询，再验证附件属于可见记录，最后核对内容 SHA-256。CLI 不能用已知哈希绕过授权，导出文件禁止覆盖。三源都按完成采集时刻可见；不从 ann_date、索引日期或标称新闻时间构造 `verified_release`。当前公开站点展示的更正稿可以归档，但关联原版/更正版及可信日内发布时间仍需独立证据。

补充（2026-10-01）：普通三源适配保持上述观察策略；`QualifiedCNInfoIncomeProvider` 另从可信应用 SHA 固定的资格清单导入明确核对的历史 PDF 版本。新增 `verified_release_date` 区分日期精度：`release_date` 与索引/PDF/资格附件绑定，`published_at` 必须未知，最早次日零点（+08:00）可见；system 仍检查实际入库时间。每次读取核对全部附件，未合格 Provider 不得声称日期历史资格。新字段为空时不写入旧记录序列化，保持旧 ID；不改写 PostgreSQL 历史 payload。实际范围仅 300122 原版/更正年度利润核心两字段，见 [历史案例](P17_RELEASE_DATE_PIT_20261001.md)。

AKShare三个原实时函数在隔离worker内使用 `BoundedSpotPagination` 替换SDK公共分页助手，保留原URL/筛选/字段及23列映射。单页一次尝试、源总数及重复/截断校验、原始页字段留痕；成功捕获附加源Artifact和完成依据，每次读取同时验证源哈希/语义/PIT/权限。旧观察快照及其他接口保留原策略；不把完整分页等同于全市场全集、原子时点或报价新鲜性。真实三接口仍失败，见 [分页及复测](P19_BOUNDED_PAGINATION_20261001.md)。

## 5. Runtime

Agent = AgentSpec + Runtime；一次运行另有独立 RunState。

目标 AgentSpec 保存标识/版本、Prompt 引用、模型配置引用、工具权限上限、初始可见工具、LoopStrategy、预算、输出契约和子任务约束；不保存密钥、连接或历史。当前固定 Spec 不代表可配置动态 LoopStrategy 或 Child 约束已经实现；Phase 4 按最小需要增量扩展，旧 Spec/Checkpoint 身份保留。

Runtime 的目标职责包括 Model/Transport、ToolRegistry、ToolExecutor、受控 Hooks、EventEmitter、RunState、Checkpoint、Evidence/Artifact 接口、Budget、Trace、Approval、错误处理。金融公式和数据口径属于业务层。M1 复用已实现的授权、执行、预算、证据和恢复链，只补动态策略所需接口；通用 Hooks/Approval 框架不作为首版前置工程。

已按用户追加授权提前落实 `model_adapters/chat.py`：从本地配置读取用户指定端点与凭据，使用 Chat Completions 文本协议，模型固定为 `deepseek-v4-flash-0731`，默认关闭思考与流式输出。适配器返回请求/实际模型、正文、结束原因、请求 ID、Token 用量和耗时；不返回模型内部思考，不自动重试付费模型请求。2026-10-01 新增 `research/` 固定 Single Runtime，复用文本适配器实现严格 JSON 证据选择和结构化报告；Phase4沿用该文本适配器增加应用层JSON动作循环。原生tool_calls、自由事实生成和模型级回退未实现。

### Phase 2 固定流程实现（2026-10-01）

`contracts.py` 用不可变 AgentSpec 与 ResearchRequest 固定证券、各 Dataset 的窗口/快照/唯一 Provider、带时区 cutoff、PIT 和可选基准。可信应用另外传 AccessContext 与工具授权，模型不能修改。`tools.py` Registry 与 ProviderRegistry 分离；Market 聚合日线/日历/因子，Financial 聚合三表核心字段，另有 Benchmark、Announcement、News 与 Calculation。工具只查询已有快照，没有自动 refresh 或 fallback。

`calculation.py` 使用 Decimal 精度 34。价格变化与回撤只针对可见收盘样本；请求边界未观察、缺交易日历和覆盖未认证单独提示。基准必须日期序列完全一致，复权因子必须逐日有效；同比要求同报告期与正基数。Claim 保存公式、实际窗口和输入 Evidence；Evidence 保存源记录、原始/规范化值、单位、版本、快照、可用/发布/采集/入库时间、Tool/Provider 调用及所有附件。

Runtime 固定顺序执行，一次可选 DeepSeek 调用只接收有限事实的名称/值/单位/窗口，返回最多三个已有事实 ID。模型没有数值生产权或工具执行权；不向模型发送源正文、文档标题、scope、快照 ID 或密钥。错误模型、截断、非法 JSON、未知 ID、额外字段及异常用量均拒绝并标记 partial。报告中的文档仅为转义后的不可信来源索引，不做因果分析。

预算默认 8 个聚合工具尝试、45 秒、8k Token 预留、最多一轮模型。输入用 UTF-8 字节数加消息开销作保守预留，非精确 tokenizer 计量；实际响应用量另记，未知用量不释放预留。deadline 使用当前进程 monotonic 和持久绝对 UTC；本地 I/O 协作式边界检查并拒绝迟到结果，不声称能中断阻塞中的数据库调用。模型网络传递剩余 timeout。

`checkpoints.py` 用标准库 SQLite 追加带前序哈希的状态，不更改 PostgreSQL 数据 schema；OS 文件锁阻止同 run 并发执行，进程崩溃自动释放锁。恢复验证请求/Spec 绑定和原预算、逐域重读授权及源附件；完成报告也不得绕过该检查。模型 intent 先落盘，未知结果只返回 partial，不自动重发。数据库与 checkpoint 目录属于可信应用内部存储，CLI 的 --scope 不是远程身份认证。导出的报告文件是授权时点的本地副本，后续分发与文件访问依赖本机权限，不具有远程撤销能力。

2026-10-02 验收修复：未完成恢复在任何源重读之前和每次重读后检查原 deadline/取消；重授权未完成或迟到时，停止报告不发布缓存 Claim/文档，保留原调用/Token 预留和未知模型状态。完成报告回放继续逐域重授权及验附件，允许超过执行 deadline。模型选择 JSON 拒绝重复键；Runtime 自行检查非负整数 Token 计数、合计/预留上限及输出 Token 预算，不只依赖 Transport 校验。

任务质量补充：Markdown 概览只从既有 Claim 生成，显示百分比和人民币量级，标明四舍五入并保留原 JSON/证据精度；缺口增加中文说明，原代码保留。质量脚本分别检查报告表达、模型选择的跨域覆盖/非冗余与事实哈希，评分不改变 Runtime 的严格 verified 格式语义，也不把产品评分冒充专家金融真值。

真实批准批次暴露等额收入重点重复后，展示仅合并同值/同期间/同单位的营业收入与营业总收入配对，并明确说明合并；JSON原模型选择、全部指标与原失败评分保持。不合并不同时期/不同金额及其他同值指标；不是新模型回答，也不产生新Claim。

Trace 在 checkpoint 内记录完整完成回执与报告 hash；报告 JSON 包含生成时的执行 Trace，避免把自身 hash 递归嵌入自身。模型原文和密钥不进入 Trace。当前为串行固定计划，同 wave 只复用聚合结果且每次重新验权限/哈希；不声称已经实现设计中的跨并发批次合并或硬实时预算。

全局共享客户端、连接池、不可变注册表和限流器；每个身份隔离凭据、数据范围；每个请求固定 cutoff、总预算、快照和取消信号；每个 Agent 独立消息、计划、轮数和局部预算。

## 6. Single Agent

### Phase 3 有界研究实现（2026-10-02）

真实选择验收发现模型可能只突出价格。报告渲染增加独立标注的系统核对补充：在数值和模型格式均verified时补所选可判定假设的全部依据及已有行情/财务覆盖；只引用既有Claim，缺同比不生成值，不修改JSON/Checkpoint、模型选择或原质量评分。续修将明确覆盖/引用指令接入single-research-v2；v1指令保留，Spec identity隔离两个版本的Checkpoint，旧运行需显式v1恢复。数值和假设规则未更改，合法但低质量选择仍计失败。

续修新增ScopedReadService，只接受可信应用登记的SourceGrant。逐次解析recipient scope、原source scope、snapshot、provider和精确request，沿原DataService重新执行PIT及附件哈希核对；恢复、缓存复用和附件读取均不可绕过源授权。数据不跨scope复制、不合并写入生产库，模型不能提供或扩大grant。当前接入限定QA组合入口；默认单scope CLI边界保持。新采事件行情保存独立reference snapshot，只能在采集后的cutoff用于描述性回顾。

v2真实复测仍漏假设引用。v3改为程序先生成最多5个完整证据候选，每个最多3个事实/3个假设，包含可判定检验的全部Claim和现有行情/财务；模型返回某个候选的ID组合，Runtime及恢复再次校验精确归属。候选只使用已验证事实/状态，不读取验收答案，不修改缺数状态、评分函数或事后补回原回答。此设计将覆盖责任交给程序，模型仅排名；当前43任务中40任务只有1个候选、3任务有多个，不等同开放式模型研究能力。v1/v2保留用于旧Checkpoint；默认v3，三个Spec隔离。

本轮质量修复新增显式 `research/archive.py`：从原授权可见Tushare v2利润记录读取原归档，核对证券/字段/口径/采集时间/锚点版本，生成去年同期起的新规范化投影。保持原观察时刻、附件和调用血缘，使用实际投影入库时间及新版本；不默认refresh、跨scope拼接或历史披露时间升级。QA用显式MemoryRepository参考快照逐次重建并重新授权；默认CLI和生产持久库尚未接入该物化步骤。

`study_contracts.py` 的 StudyRequest/StudySpec 继承固定请求和预算契约，增加单股/事件目标、固定假设 ID 和显式来源记录锚点。`study.py` 继承既有 Runtime，复用工具授权、数据 PIT、快照、追加 checkpoint、付费 intent 和恢复重授权；研究计划在读数前落盘，Trace 增加 hypotheses_tested/claims_verified。没有增加 Multi、Provider 采集或数据库迁移。

`hypotheses.py` 维护五个固定描述性检验及证据要求，输出 supported/unsupported/conflicted/insufficient、支持 Claim、反证与缺口。模型仅从已有 Claim 和假设 ID 选择重点，不能生成规则、状态或因果解释；自由研究计划、正文抽取及新行业/估值假设尚未实现。

事件锚点只能来自本次授权/PIT 可见的记录。普通 observed_at 公告/新闻保留“捕获不是首次公开时间”；合格 financial_income 的 verified_release/verified_release_date 可提供精确或日期精度披露锚点。时间戳按中国市场 15:00 日频收盘划分，日期精度使用次日边界并排除披露日事前收盘；派生 Claim 的可用时点不早于价格和锚点。缺少任一侧实际有效收盘就不计算，已有快照/修订不改写；不估计事件因果影响。

`verification.py` 独立使用 Fraction，从授权固定输入计算完整预期 Claim 集并逐项核对，而不是调用生产 Decimal 算子作为真值。校验来源精确字段、原始值、单位、公式、窗口、快照、版本与 public/system PIT；哈希重新计算不能使伪造数值通过。最终发布和完成报告回放均执行验证。供应商质量和因果真实性不由该校验认证。

`context.py` 构建有限类型化引用视图：保留证券、cutoff/PIT、数值/单位/口径/时间及 Evidence/源版本引用；完整版本身份留在本地 Evidence，模型用固定引用解析。源正文、标题和来源控制的字符串不作为模型指令，版本身份只传固定哈希引用。超过无损字节预算时不派发模型，不截掉精确 Claim。默认模型关闭；`--preview-model` 可先保存与实际模型步骤一致的本地 messages。

默认预算为8工具/120秒/16000 Token预留/512输出/12000上下文字节，仍只有一次模型尝试；无真实模型新增外发或金融Provider调用。JSON 精确事实不变，Markdown 将假设/缺口前置。`status=partial` 和 `research_status=evidence_incomplete` 明确区分可验证部分与完整所选检验，supported 仅是描述性规则成立。

优先 Single Research Agent + 六类聚合业务 Tool，不暴露每个供应商端点。Calculation 使用固定确定性算子，不默认开放任意 Python。

Fixed/Dynamic 描述执行策略，Research 描述研究能力，Single/Multi 描述 Agent 组织方式。Phase 2 为固定概览，Phase 3 为固定研究；Fast 是任务模式，不等于动态规划。已有固定计划保留兼容/回放，不再承担 Fixed/Dynamic 对照实验基线职责。

权限/PIT/预算由 Runtime 强制，验证节点不能被模型跳过。当前假设规则由程序目录定义、模型选择已有 ID；动态首版由模型分解目标、选择工具和根据结果重规划，数值和假设状态仍由确定性工具产生。自由生成金融事实、检验规则或因果解释不在 M1 范围。

M1 当前默认上限（不是实测 SLA）：8 次模型决策、12 次工具尝试、48000 记账Token、单次输出 1024 Token、240 秒绝对 deadline、单次模型上下文 12000 UTF-8 字节。旧固定运行保持各自 Spec 上限；当前串行Parent的根合计额度见第8节。更广泛Multi的30轮/100k Token/40 Tool/360秒仍仅为历史候选配置，非当前启用能力。Token包含全部输入输出和失败尝试，合法已知用量替换当前预留，未知用量保留预留；累计派发预留另列。API分页/重试另记，结束验证和输出也受根时限/预算约束。

### Phase 4 动态 Single 首版（M1，2026-10-04 实现）

`dynamic_contracts.py`固定独立`single-dynamic-v1`身份、自然语言question和可信StudyRequest必需检验。`dynamic_protocol.py`严格拒绝重复键、未知字段、模型数值与越权引用；源读取`refs=[]`，calculation引用全部当前源工具，hypotheses/verification引用先前确定性结果。Observation仅有类型化完整性/期间和精确Claim/Evidence/检验状态；共享派生视图无损去重，源正文/标题不入模型。`dynamic.py`继承既有ResearchRuntime基础，复用ToolExecutor、模型回执核验、CheckpointStore、确定性study计算及独立Fraction验证，执行逐轮策略；旧固定Spec及行为保留。

模型 intent、消息SHA、预留及逐轮账本在派发前追加。已知合法用量替换当前预算预留，累计派发预留与实测用量分别保留；未知/无效回执保留预留并停止，不自动重发。恢复核对原始deadline、历史不可变请求/必需检查、预算单调计数、Trace intent/receipt与待执行动作，重新授权源/附件并重建Observation。重复动作不重新工具派发；连续两轮无进展停止。模型选结束后程序再次独立验数，未执行必需检查或不足不能completed。deadline/取消时不继续读源，未完成授权或迟到结果不发布旧事实。已完成回放可越过执行deadline，只执行授权/完整性复核，不派发模型。

CLI已提供`research --workflow dynamic --question ... --with-model`与仅首轮`--preview-model`。报告含中文计划控制记录、逐轮动作/Observation、不可删除检查、完整精确JSON、预算和停止原因。question须由可信应用确认与已有证券/窗口/检验目标对应；completed只证明这些绑定检查完成，任意实体解析、开放式研究、源正文提取和因果结论未实现。真实模型演示与实际测试只据STATUS记录；不以机制fixture称M1真实验收通过。

受控循环为：`Model → 动作 Schema/授权/预算校验 → Tool → 类型化 Observation → Model`。模型首轮给出简短任务计划和下一步动作，后续依据 Observation 选择工具、调整顺序/合法取证路径或请求 finish。模型可改变执行策略，不能改变可信应用绑定的证券/窗口/cutoff/PIT/快照/来源和必需检查；不能先完整执行固定工作流再把重点选择称为 Dynamic。

首版沿用已配置模型和文本 Transport，以严格 JSON 表达工具名、限定参数/引用、计划更新或 finish。应用校验后经既有 Registry/Executor 执行；金融数值和支持状态仍来自工具。此协议是应用层动态工具调用，不是已实现原生 `tool_calls`；无须等待原生 function calling 或换模型。新动态 Spec 与旧固定选择协议隔离。

Observation 仅含本次授权结果、结构化状态/缺口及精确 Claim/Evidence 引用。上下文以有界、无损类型化状态视图组织，完整工具记录保存在本地 Trace/Evidence；不复制无限历史，不把来源正文指令当控制信息。必需上下文超限就停止。计划摘要仅为控制记录，不能直接发布为事实，也不保存模型隐式推理。

每轮先保存付费 intent，后保存响应、工具动作、Observation、计划版本和账本关联。每次读取/复用重授权，恢复固定 Spec/请求/预算和绝对 deadline；未知付费结果不重发。相同输入且无新证据的重复动作不重新派发，连续两轮无进展停止；格式修正也消耗模型轮数，权限/PIT/完整性失败及取消立即终止。

finish 由 Runtime 检查事前必需检查与独立 Claim Verification 后形成报告；缺证据/未完成不得宣称 completed。交付为可运行 CLI、中文报告、精确 JSON 和可读计划/执行 Trace。验收只做闭环、重规划、安全/恢复回归及最多 3 个真实模型端到端演示，不做 Fixed/Dynamic 比较，不等待旧广泛质量补证。

2026-10-05增加独立single-dynamic-v2/Parent/Child协议：有not_completed必需检查的两种finish请求均被Runtime typed拒绝，反馈固定检查ID并继续原循环；拒绝决策与Token不返还，连续两次无进展停止。实际检查已完成且证据不足时可以insufficient。旧single-dynamic-v1的消息、身份和finish行为保持历史兼容；CLI新运行默认v2，库默认仍v1。

## 7. Research / Evidence

Observation → Hypotheses → Required Evidence → Tools → Supported/Unsupported/Insufficient → Synthesis → Verification。

下跌研究先排除除权等机械因素，再比较公司事件、行业、大盘、财务、估值、流动性。新闻与下跌同时出现不证明因果。无信息一般表示 Insufficient，而不是反证。

Evidence 记录来源、原始值、规范化值、单位、窗口、published/available/retrieved 时间、版本、原文位置、Artifact、Tool/Provider Call、计算公式与输入证据。as_of_date 是运行与证据的绑定。派生证据可用时间不早于任何输入。

Claim 引用 Evidence IDs，区分直接支持、计算、部分支持、冲突。报告区分 observed fact、supported hypothesis、weak hypothesis、insufficient evidence。Citation 由来源记录生成，不由模型补链接。

## 8. Multi-Agent

### P4.4 Financial/Market串行领域委派

2026-10-05后续授权已新增`DomainParentSpec`；程序默认保持`dynamic-parent-domains-v1`兼容身份。P4.4 Context Remediation新增独立`dynamic-parent-domains-v2`，CLI的`--workflow dynamic --domain-agents`默认选择v2；旧运行显式`--domain-version dynamic-parent-domains-v1`恢复。Parent用同一严格JSON动作协议选择普通源工具或`financial_child`/`market_child`，两个AgentTool均只接受`refs=[]`。没有独立Router模型，每个领域最多启动一个Child、总共最多两个，严格串行。Parent仍承担计算、假设检验、Claim Verification和最终报告；Child不生成Claim、规则或金融值。

`MarketRequest`只保留父原绑定的`market_daily`、`trade_calendar`、`adjustment_factor`，`MarketChildSpec`/`market-child-v1`只允许market读取；Financial Child仍只读被委派的财务源。两个Child均保持父证券、窗口、带时区cutoff、PIT、Provider和不可变快照，权限取父有效委派范围、可信应用授权、服务策略及各ChildSpec交集。每次读、缓存复用和恢复继续重授权；Child禁止再次调用AgentTool或spawn。

P4.4使用同一`root_budget.py`的独立`root-budget/v2`事件账本，父子合计默认16决策/18工具/96000记账Token，Parent局部仍为8/12/48000/240秒。每个Child在派发前持久预留至多3决策/1工具/18000Token，局部deadline不晚于父/root且最多120秒。账本拒绝活动Child期间启动第二个Child或派发父模型/工具；未知结果保留额度、不自动重发，可信回执只释放确实未用的份额。取消和迟到结果不能进入父Evidence。

成功读取的Child来源回执经父再次核验后，分别导入普通`financial`或`market` Observation；后续计算仍引用普通源工具名。Parent下一轮另外接收严格`delegation_results`：最多两项，只含固定tool/domain、completed/insufficient/partial状态及结果哈希。它是程序生成的路由反馈，不包含数值、授权或自由错误正文。Child部分失败允许父在原授权/剩余额度内选择有用的直接工具；恢复重核全部子回执、源附件、预算事件及父子Evidence关联。

新Spec、动作版本与root-budget/v2不改变旧`single-dynamic-v1/v2`、`dynamic-parent-financial-v1`、`financial-child-v1`消息和身份。旧P4.3仍使用root-budget/v1及单Child约束，原运行须用原请求/模式/Spec恢复，不能升级身份来重置账本。P4.4当前代码与最终验收结果分开记录；测试/真实演示数字只据[STATUS](STATUS.md)，不将合成机制测试当作金融真值或广泛质量认证。P4.5并行尚未实现。

### P4.3单Financial Child兼容模式

2026-10-05首轮授权的`FinancialParentSpec`/`FinancialChildSpec`继续由同一`DynamicRuntime.run`执行；financial_child注册为严格refs=[]工具。可信程序构造FinancialRequest，仅保留父原绑定财务数据及完全相同的证券/cutoff/PIT/窗口/来源/快照，Child无模型可修改的scope、权限或预算参数。有效工具为父有效权限、应用delegated_tools、ChildSpec交集；数据再受delegated_datasets/Provider与原服务实时SourceGrant限制。运行、读源、缓存和恢复均重授权，活动Child也检查父工具撤销。

`root_budget.py`只是可序列化账本，持久化由原Checkpoint/Trace负责。父模型与工具同根记账；串行Child启动前一次占用3决策/1工具/18000Token（或更小Spec），父子总额默认12/16/72000。Child使用独立UUID、消息、计划和局部账本，deadline=min(父绝对deadline,启动+120秒)，共享取消信号。完整Child未知则整份额度保留、恢复不重派发；可信局部结果可结算未用额度，未知模型预留继续计账。根events与父intent/receipt/Child结构化回执及历史前缀交叉核对。

Child只读financial，不具备calculation、market或spawn权限；不复制父历史。程序回传financial-child-result/v1，包括源结果哈希/记录附件快照引用/实际读取调用/必需检查/Usage。父重读原来源核验后导入financial Observation，并沿用原计算/假设/Verification；父Evidence.tool_call_id链接Child读取，报告child_evidence_links独立关联。Child部分失败显式保留，父可在原额度/授权内另选直接工具。取消和迟到结果不进入父Evidence。完成回放递归重核Child授权、原来源和结果哈希，零模型派发。

依赖顺序：M1 动态 Single → P4.3 Agent-as-Tool/串行 Child → P4.4 领域委派 M2 → P4.5 并行 M3。M1 交付后即可开展受限 Multi 原型；不先要求收益统计证明。原型功能/安全验收与后续扩大使用范围的判断分开。

领域委派不是默认路径。当前Parent依据可见工具、Observation及类型化委派结果选择直接或委派；更广泛的路由设计可考虑数据域、公司数、假设验证量、来源冲突、预计上下文和独立分支。“为什么”、长期窗口或公司多都不是独立充分条件。

当前领域仅Financial和Market的受限来源读取。Fundamental深度研究、Event、Risk仍为未来候选，扩展须按实际需求及新范围授权；不预建完整Agent群或独立Router模型。未来并行及依赖调度属于P4.5，当前没有实现。Synthesis/Verification仍由父阶段执行，不增加常驻Agent。

未来扩展约定由Parent传structured task、标的/窗口/cutoff/快照、白名单、Evidence引用和预算，Child返回结构化结果及Usage；当前两个来源Child只回传授权来源/缺口/血缘，不产生研究Claim或反证结论。不复制完整父历史。

Root 深度 0，最大 spawn 深度 1，Child 禁止再 spawn；最多 4 个 Child Run、并发 3；每个候选上限 6 轮/18k Token/8 Tool/120 秒，并受根预算限制。取消向下传播，失败按关键性部分完成。

上述为未来Multi候选上限，当前P4.3/P4.4仅串行执行。创建首个Child就须预留根预算，并限制局部deadline不晚于父/root，继承根请求PIT/快照/cutoff。工具和数据授权受父有效委派范围、可信应用、服务策略和ChildSpec共同限制，每次读/缓存/恢复重查。P4.5再加入并发原子预留、取消竞争和迟到结果处理，不能延后基本根预算与取消。

## 9. Agent as Tool

普通Tool是有界读取或计算；Domain Agent是领域AgentSpec与动态策略在共享Runtime上的受限运行，AgentTool将其封装进同一Registry/Executor并启动独立生命周期/状态/局部预算的Child Run。当前M2仅有Financial/Market两个来源Child；共享Evidence/Trace/Checkpoint、模型适配和根预算，不另建Multi专用Runtime，不共享可变父消息。后续定向评估再决定扩大使用范围。

全部工具直接暴露：链路短、通常便宜，但大量工具增加选择和上下文负担。Domain Agents：领域权限与上下文清晰、可隔离失败，但增加模型调用、汇总损失和可观测性成本。不能把更小顶层 Prompt 当作更低总 Token。

## 10. Context / State / Checkpoint

### Phase 6首轮：显式无损metadata表示

`dynamic-parent-parallel-v3`保持v2权威revision执行进度及原动作/完成/重复检查。仅模型视图使用`dynamic-context-view/v2`：纯`dynamic_context_metadata.py`在固定metadata位置将重复精确字符串用整数引用`symbols`，盈利的重复完整列表用`{"l":i}`引用`list_table`；原金融value单元、Fact/Evidence行ID及source records数值不改。严格回解为canonical v1 wire后再调用原expand/validate与catalog绑定核对，保留全部字符串、数组顺序、空/null、目录、缺口、source版本/时间/权限/血缘。整数只在codec固定metadata位置解释，gaps仍按原gap_table、数值不作索引；拒绝bool/dangling/未知字段/非canonical/tamper，结构与字节预算复用。

旧v1/v2 wire、默认Parent/Child v1、Spec身份和Checkpoint绑定保持。CLI显式`--parallel-version dynamic-parent-parallel-v3`与Child显式v3选择；新运行不能升级旧run重置预算。授权读取、披露、恢复、完整事实/证据、Lazy闭包、DAG、原子root预算/Parent headroom、取消/deadline/未知付费不变；Telemetry支持v2精确回解并重新构造paid wire，不将测量用于路由。此实现没有事实缓存、不跳过任何重授权/校验。实际限定验收另见[Phase6首轮记录](PHASE6_FIRST_ROUND_20261006.md)。

该首轮两个已有case四真实运行及零追加回放均4/4通过；同状态精确模型wire净省3414字节，实际父子Token少4.59%，完整事实/Evidence及20必需执行检查保持。Runtime合计无延迟改善，小样本不验证P95/SLA/统计优势；接受范围只为显式无损metadata表示。原Phase5的并行扩张门槛与原8/9不改，Parent/Child默认v1及12000保持，不自动路由、不扩大并行或进入下一阶段。运行与harness事后验证计时分开；source授权/读取等没有独立span时保留未知，不用残差冒充准确分解。

### P4.4 Context Remediation（阻塞修复；非完整Phase 6）

`dynamic_context.py`提供纯确定性catalog/arena/view编解码，无模型、网络或授权缓存。完整原请求、类型化Observation、Claim/Evidence及检查集通过可逆字符串表存储，按scope、run UUID和request内容绑定并校验哈希；`O:tool`、`C:id`、`E:id`、`H:id`是目录引用。历史Observation外置到既有追加Checkpoint，模型每轮只接收共同range、列定义、全部Claim/Hypothesis值与引用和必要Evidence，来源元数据及阶段状态保持原语义。Fact/Evidence重复长metadata用`{"s":i}`精确引用`symbols[i]`，金融value及引用ID保持字面值；重复缺口代码用`gap_table`索引，均可canonical回解并对照权威目录。仅v2按工具名稳定排序输入目录，使Checkpoint规范化后的恢复哈希一致；旧协议字节保持。

默认Evidence披露由当前首个未执行的必需检查选择：计算前提供来源状态目录，假设/finish取声明假设的输入闭包，verification取所有Claim的Evidence闭包。该选择只决定视图，不替模型选择业务动作。模型可用严格`disclose`和当前catalog哈希请求最多16个已有引用；程序展开其完整闭包并在下一轮展示，成功业务工具后清除该额外选择。全量事实/Evidence始终保存在原状态及最终报告，不把未展示对象删除或把引用当完成。question/最近plan/schema控制文本去掉逐Observation的重复副本。

披露计入原模型决策、本地及根工具/Token/绝对deadline与无进展限制，不产生新业务Observation或满足必需检查。每次编视图、披露前后和恢复均重新核验源附件、Registry及实时SourceGrant；catalog哈希不能授予权限。context_store目录与披露账本只追加，恢复重建每次已付费messages并核对intent、目录、范围、动作、读取回执及结果哈希；未知付费/工具结果不重放。Child仍用旧领域只读协议，不能披露父目录或spawn。新v2独立Spec/配置身份禁止升级旧run来重置账本。12000 UTF-8字节上限不变，无LLM摘要、事实裁剪、持久跨主体缓存或Phase 6性能目标；P4.5不启动。

消息保存近期相关对话；RunState 保存固定范围/计划/预算/状态；Evidence 保存精确事实；Artifact 保存大表、公告和原始响应。上下文只放摘要、元数据和引用，按需取回。

后续通用Context治理可研究Tool大小、外置、确定性压缩与其他候选；滑动窗口或LLM摘要不用于本轮P4.4阻塞修复，完整Phase 6须后续范围授权。不得丢标的、cutoff、数值、单位、口径、Evidence ID、来源、版本和冲突。摘要不成为事实源。

Checkpoint 在规范化、计划、整批结果提交、Child 变化、审批和验证结束后记录。保存账本和引用，不保存连接/密钥。恢复不重置预算，不盲目重放结果未知的副作用。

## 11. Reliability / Permission / HIL

可见工具 ⊆ 有效授权 ⊆ 用户权限 ∩ 服务策略 ∩ Spec 上限。执行时重查；Lazy Disclosure 不增加权限。

请求/Child/Tool/Provider 嵌套 deadline；排队、退避、分页计入总时限。Provider 是唯一网络重试责任层，避免重试叠加。认证、Schema、无效参数不重试；Agent 重规划是另一类动作。

Tool 同 wave 去重 + Provider 在途请求合并 + 已完成缓存。签名包含操作/版本/规范化参数/cutoff/快照/口径/来源策略/授权范围。共享执行仍为每个逻辑调用保留关联；等待者取消不能取消其他等待者。

写操作的幂等与读取去重分开。无幂等的 Write、HIGH_RISK、审批改变或副作用结果未知禁止自动重试。只预留审批状态机，不建设交易。

## 12. Observability

Request → Run → Turn → Tool → Provider；Evidence/Claim 是多对多血缘图，不是简单子树。

保存 trace/run/parent/turn/wave/tool/execution/provider/evidence/claim/artifact IDs，配置和快照版本、排队/执行时间、Token/API 计数、status/error/retry、cache/dedup、cutoff/新鲜度、授权决策。排除密钥和模型隐式推理。

P4.5起所有新Dynamic运行采集`context-telemetry/v1`，包含真实wire UTF-8 bytes与SHA、before/after/saved、固定cap、角色/domain/route/turn/parallel lineage、visible/total Fact/Claim/Evidence、分桶、模型派发/超限/status/stop reason和回执input/output/total tokens。before定义为相同system/control下完整typed catalog payload的确定性反事实基线，初始目录开销可能产生负saved；不能把它冒充历史P4.4原wire。Fact在当前契约中即Claim；不能可靠拆分的压缩贡献为null，不虚填零。Telemetry不进入prompt或参与路由，旧checkpoint没有此字段时保持原报告。

`parallel-telemetry/v1`记录分支/组起止、queue/execution/join_wait/wall/sum时间、根预留和实际、cancel/failed/late/unknown、真实result_order及固定canonical_merge_order；取消导致迟到时两项计数可重叠。context从paid checkpoint重建并核回执，parallel从持久group与Trace复算，完成回放不追加记录或产生付费调用。报告trace_stratum支持dynamic_single/parent_direct/parent_1_child/parent_2_child/parallel_2_child，Child另标domain和parent linkage。数据用于后续离线分位数、超限率、Token/延迟/预算/Task Success分析；本轮无Dashboard、统计优势或阈值优化。

## 13. Benchmark Dataset

2026-10-04增加独立于Research Runtime的`benchmark-contract/v1`冻结门禁。可信应用逐binding调用原授权读取和当前SourceGrant解析，另核对完整snapshot/provider能力元数据与哈希；模型/请求JSON不得提供trusted元数据。正式Builder先保存完整预检报告，非法或not_assessable整批拒绝，不筛样本。写入前重新预检，不能凭调用方自报valid=True。明确事件、源版本/PIT及原窗口/cutoff价格时间可行性属于输入契约；合法缺数据、可检查非正基数或实际日期不齐分别记数据/内在前置条件。零行Dataset须原始请求归档/响应hash/时刻的可信证明，实际Dataset成员缺行事实保留。

评分分开输出benchmark validity、source support、official accuracy、required-check completion、contract-valid success、frozen end-to-end success、critical anchor和hallucination。已冻结非法任务留在原端到端分母，条件指标分母0为not_assessable。`single-research-v4`另加本地结构化不足诊断及版本marker，不改v1-v3事实/假设payload；模型输入仍用v3完整候选。v4恢复验证schema、诊断内容和当前源权限，停止报告也拒绝伪造诊断。CLI默认v4，程序StudySpec默认v3保留旧脚本兼容；新调用可显式v4。见[具体实现和证据](PHASE3_CONTRACT_REMEDIATION_20261004.md)。

2026-10-04新Benchmark使用独立 `phase3-benchmark-contract/v2` 包装原门禁，读取可信full snapshot/源所有者与授权、复核原Artifact SHA和明确定义的事件before/after子窗口；不消费Agent输出或旧评分判题。新38题全部通过才封存manifest，Agent运行后源文件、Prompt/Spec/代码和原始响应均核hash。Source/Fraction oracle不导入生产计算，全文Judge与生成隔离；新增Markdown事实纳入支持/幻觉分母，官方未知另列，预登记合法不足只有来源证明且答全问题才允许Task Success。

`profit_change.py` 为显式v5研究追加 `financial_income.absolute_profit_change` Claim及 `absolute_profit_change` Hypothesis；请求须声明 `hypothesis_version=profit-change/v1`。读取仍走每次授权/PIT服务；金额算法使用同期间CNY差额，独立Fraction核验，delta>0 supported，否则unsupported，缺数或缺同期insufficient。v1–v4拒绝新目录项，旧百分比同比及版本序列化不变。v5复用v4诊断、上下文、预算和严格恢复验证；CLI默认v4、程序默认v3均未升级。模型仍只选择已构建的完整候选，不承担数值生产、原文自主提取或自由规划。新材料仅validation，不能把高源支持率当全部官方金融准确率或盲样泛化。入口见[本批报告](../.artifacts/phase3/benchmark-v2-20261004/PHASE3_BENCHMARK_V2_REPORT.md)。

L1 查询，L2 指标，L3 单股，L4 多股，L5 事件，L6 复杂研究。原 60 种子/约 300 正式任务集为长期评测设想，当前不追加执行，也不是动态首版或 Multi 原型入口。保留已有材料；M1 按 PLAN 做少量功能演示和必要回归。

Case 含 id/version/question/symbols/as_of_date/window/PIT mode/allowed_sources/expected_tools/forbidden_tools/required_metrics/ground_truth/expected_evidence/rules/level/snapshot/expected_status/leakage_traps/source_lineage。

真值使用冻结原始数据、独立确定性参考计算和人工/官方抽查；不能复用生产计算实现充当独立真值。事件归因按事实、时间顺序、反证和结论强度评分，不强求唯一原因。

按公司/事件/时间分组切分开发、验证、测试；真实、合成、故障 Case 分开报告。不得访问隐藏测试答案参与生成。

## 14. Quantitative Metrics

数据准确率、计算准确率、Tool Precision/Recall/F1、Task Success、Evidence Support、Hallucination、Temporal Leakage、P50/P95/P99、Token/API/金额成本、单位成功成本。按 Level 和域分层报告。

数值容差为绝对/相对容差最大值，单位、版本、时间或口径错误直接失败。缺失必需项计入失败；空答案不得靠零 Claim 获满分。最终文本另抽取 Claim 检查漏报。分别测未来信息进入上下文和进入报告。

收益、回撤、波动、Beta、Sharpe、PE percentile 固定公式、窗口、日历、无风险利率、样本量和异常处理。后续投资收益率不是研究质量的替代指标。

## 15. 后续 Dynamic Single / Multi 定向评估

2026-10-06 明确授权的 Phase 5 只增加离线确定性 Trace 评估与有界真实 campaign harness。三项已知合法源的新 Dynamic validation 任务各有 direct/serial/parallel 路线，运行仍使用既有 DynamicRuntime 与 Child v3；direct 使用 dynamic-parent-domains-v2 的受限普通工具集，以保留相同无损 Context Builder，serial 使用原领域 Parent v2，parallel 使用原 ParallelParent。Spec identity、工具集和路线指令差异均冻结并显式报告，不更改原默认或任何历史 Spec。

评估以完整根/Child 账本与 Trace 为依据；paid wire、receipt、source envelope、oracle、checkpoint 和报告由哈希固定。运行结果和模型网络区间按 case/route 配对，独立任务数与运行数分开，历史失败/修复/合成机制夹具不进入新分母。延迟只在实测运行条件下描述，不将 section/sum 比例冒称相对直接工具的加速，也不将 source-bound verification 当金融真值认证。评估不参与运行路由、权限、预算或上下文阈值决策。Phase 6 正式优化留待新的授权。

本轮实现 `trace_evaluation.py` 与 `scripts/phase5_evaluate.py`，新真实8/9及完整父子回执/Telemetry/源核对已冻结。新688184并行失败为Parent跳过必需verification并重复提前finish；Runtime原typed rejection与no_progress如实拒绝，两个Child完成及数值核对不能代替父必需执行。9/9只读报告回放一致，但事前全功能门槛未达，决定不扩大启用范围；不改变旧Runtime、默认协议、12000或路由。细节见[Phase 5记录](PHASE5_EVALUATION_20261006.md)。

同日后续明确修复授权新增显式`dynamic-parent-parallel-v2`与CLI `--parallel-version`，默认仍v1。同一Runtime从原`_check_results`的当前源revision生成`control.execution`（pending_checks/can_finish/next_action），执行状态与假设不足分离；候选只给现有授权tool的精确动作，不强制来源路由或自动执行。初始preview、每次paid输入、Context/Telemetry历史重构使用同一确定性检查，恢复重新核验源/权限；旧协议不增字段且wire保持。原finish、no_progress、DAG、root allocation、Child v3和12000上限均保持。同案例复验另外冻结，旧8/9和62文件源码副本保留，不贡献独立新样本；未开展Phase6。

该Parent v2同案例真实完整闭环1/1及零模型回放已通过，794/794隔离回归通过；第4轮模型实际选择verification，第5轮can_finish=true后请求finish(completed)，Runtime仍按原证据状态报告合法insufficient。仅验证本单项修复，不能补写原8/9或泛化其他case的v2质量；默认和12000不变。

2026-10-04 用户明确优先得到动态 Agent，取消 Fixed/Dynamic、Agent/workflow 对比；原 A 细粒度 Tool Single / B 聚合 Tool Single / C Domain Agents 三组必做安排撤销。固定运行保留兼容与回归，不以其效率/效果证明动态方案是否值得建设。

Phase 5 在动态 Single 与 Multi 都可运行后，仅围绕实际委派任务判断分工/领域隔离/并行的收益。共享模型、工具业务能力、数据、PIT、权限和验证，记录完整父子用量、失败、质量、延迟、安全和冷热缓存条件；动态 Single 同样可以具备并行工具能力，不能把并行独占为 Multi 优势。M1/M2/M3 不等待比较实验或统计显著性。

扩大 Multi 使用范围前，针对所需任务预先声明质量目标、成本/延迟上限和安全要求，按实际结果决定；安全不退化、根预算与总时限必须满足。原“质量 +5pp、CI 下界 >0、成本 ≤2 倍、P95 ≤1.5 倍”只保留为历史候选，不是现行原型交付门槛。若未来需要正式统计优势结论，再另行规划配对样本和置信区间；小规模演示不能冒充广泛优势。

## 16. Ablation

Evidence Verification、Domain Isolation、Single/Multi、Hypothesis Verification、PIT、Context Compaction 六类保留为未来问题诊断的可选手段，不再要求完整执行或作为动态首版前置。当前不启动消融；必要的故障/安全回归继续执行。未来若开展，仅改变待研究因素；无 PIT 只能在隔离实验，不能改变真实运行约束。

## 17. Fault Injection

覆盖超时、空响应、Schema 漂移、429、Search 失败、Child 超时、计算异常、部分成功、重复调用、上下文溢出、非法参数、循环、崩溃恢复、未来修订、文档指令注入、越权缓存、Evidence 写入失败。

瞬时故障有界恢复；非关键失败部分输出；关键证据或计算失败不得标记完整成功；LLM 不接管心算填空。

## 18–19. 分阶段实施与验收

见 [PLAN.md](PLAN.md)。动态首版先交付功能闭环与必要安全验收，再逐步构建受限 Multi。Phase 5 是后续定向评估，Phase 6 按实际瓶颈优化；PIT、权限、预算、基础去重与无损引用上下文始终从早期建立。

## 20. 风险与暂不实现

历史版本、时间精度、数据授权和来源配额可能限制覆盖。模型训练可能含后见知识，证据约束不能证明模型从未见过未来，需结果审查与污染测试。

暂不实现：默认 Multi、递归 Child、任意代码执行、全量底层 API Tool、向量库/知识图谱、Kafka/微服务/Kubernetes、常驻 Critic 群、自主长期记忆、任意插件热加载和自动交易。

## 21. 推荐结果

在现有可重放数据、确定性计算、证据与验证基础上，优先得到能规划、调用工具、观察结果并重规划的动态 Single；随后通过同一 Runtime 的 Agent-as-Tool 构建受限 Multi。功能交付不等待 Agent/workflow 对照实验，复杂优化依实际使用证据安排；原广泛质量缺口如实保留。

## 22. 目录职责

- `src/stock_research/`：当前模块化应用。
- `src/stock_research/providers/`：Provider 契约、注册、Tushare 适配。
- `src/stock_research/model_adapters/`：独立模型协议/Transport，和金融数据 Provider 分开。
- `src/stock_research/storage/`：版本记录、不可变快照和 Artifact 持久化。
- `tests/`：契约、PIT、数据层与故障测试。
- `evaluation/`：Case 规范、合成种子、未来独立参考计算和对照实验。
- `docs/`：架构、计划、约束、执行状态。
- 后续按实际阶段增加 runtime/tools/domain/agents，禁止为未实现能力预建空框架。

## 参考来源

- [PipesHub Domain Agents](https://github.com/pipeshub-ai/pipeshub-ai/blob/main/backend/python/app/agents/agent_loop/domain_agents.py)：AgentSpec、AgentTool、共享 Runtime、领域工具和递归边界；未宣称其实现本项目金融 PIT。
- [Tushare HTTP](https://tushare.pro/document/1?doc_id=130)、[日线](https://tushare.pro/document/2?doc_id=27)、[利润表](https://tushare.pro/document/2?doc_id=33)、[复权因子](https://tushare.pro/document/2?doc_id=28)。
- [Psycopg 使用文档](https://www.psycopg.org/psycopg3/docs/basic/usage.html)。
- [阿里云百炼 DeepSeek 接口](https://help.aliyun.com/zh/model-studio/deepseek-api)：本项目用户配置的实际网关支持该模型标识与 Chat Completions；不将 DeepSeek 官方直连的模型别名规则套用到百炼。
