# 架构与执行约束

## 必须遵守

1. 系统是研究助手；不构建自动交易、下单或组合调整。
2. 事实来自受控数据层；数值计算必须确定性，LLM 不能补缺失数值。
3. 用户于 2026-10-01 授权 Phase 2、2026-10-02 授权 Phase 3，并于 2026-10-04 要求调整规划：优先交付 Dynamic Single，再基于同一 Runtime 研究 Agent-as-Tool/Multi。取消 Fixed/Dynamic、Agent/workflow 对比实验及原 Phase 3 广泛质量补证对动态首版的阻塞；保留旧验收事实和范围限制。此前仅规划要求已履行；同日追加“推进Phase4”授权本轮 M1 实施，并明确本会话向远端 LLM 发送数据默认批准、无需确认。实际演示仍有独立事前任务/预算界限，不能重用旧耗尽额度；依 PLAN 的 M1→M2→M3 顺序，不跳过 M1 验收、不自动扩大实验或加入交易。
4. AgentSpec 与 Runtime、业务 Tool 与 Provider 分离。
5. 所有查询需要明确证券、窗口、带时区 cutoff、PIT 模式、来源范围和不可变快照。
6. `available_at <= cutoff`；system 模式另外要求 `ingested_at <= cutoff`。
7. `report_period` 不等于披露日期；`retrieved_at` 不证明历史版本公开时间。
8. 当前抓取的供应商修订值，不可仅据历史 ann_date 倒填 available_at。
9. 未知时间/版本保守处理；不得把今日新闻正文、当前指数成分用于历史事实。
10. 原始值、规范化值、单位、口径、Provider、版本、时间依据、Artifact 和调用引用可追溯。
11. 快照和记录不可变；重复写同一 ID 必须核对内容，冲突报错。
12. 权限来自可信应用上下文，不接受模型自报授权；缓存命中与复用也受授权约束。
13. 可见集不等于权限集；子 Agent 和 Lazy Disclosure 不得扩大权限。
14. 去重键包含语义与授权边界；不可跨主体泄露；不把错误缓存成成功空数据。
15. 网络重试只有一个责任层；认证、Schema、业务参数错误不得自动重试。
16. 所有网络调用有界；拒绝无限循环、无限分页、无限递归。
17. Provider Fallback 要显式配置且满足同口径契约；没有验证过的真实 fallback 就返回失败。
18. 日频未复权与总收益、财务累计/单季/TTM 分离；缺失不当成零。
19. 密钥仅经环境或受控注入；用户明确指定的本地 `test_api.txt` 属于受控输入，只读取、不复制，不进源码、日志、Artifact、错误消息、快照。项目本地 `tushare.txt` 与 `.env` 也属于受控密钥文件；这些文件必须 Git 忽略且从发行包排除。
20. 真实凭据不通过聊天或测试 fixture 保存。Tushare Transport 使用固定 HTTPS 官方端点；模型 Transport 仅向用户配置的 HTTPS 端点发送模型凭据，不跟随重定向，不隐式切换供应商或模型。
21. 合成数据明确标识，不能充当真实金融事实或 Provider 联调结果。
22. 验收只写实际执行结果；跳过的集成测试和缺失真实验证必须列明。
23. Phase 2 模型只能返回已提供的 Claim 选择 ID；自由文字、未知 ID、额外数值、错误模型或截断回答不能进入已验证输出。文档正文和标题不进入模型上下文，来源指令不能触发工具。
24. 恢复使用原请求、Spec、cutoff、快照和绝对 deadline，重新检查工具/来源授权及全部已用附件。付费调用先持久化 intent，结果未知时不得自动重发。失败尝试保留 Token 预留，不把未知用量写为零。
25. Phase 3 首版假设来自固定目录；模型只选择既有 Claim/假设 ID，不能修改支持状态、检验规则或证据。支持仅表示描述性检验成立，不表示因果；方向冲突与证据不足必须显式保留。事件捕获时间和网页标称时间不能升级为首次公开时间，日期精度采用保守次日边界并排除披露日事前价格。
26. Phase 4 动态策略允许模型分解任务、选择已授权工具和受限参数、依据 Observation 调整计划或请求结束；Runtime 执行动作、重查权限并强制验证。第 23/25 条的旧固定选择协议按旧 Spec 保留，不用来把动态执行重新限定为一次重点选择；数值、规则、证据与授权不能由模型生成或修改。首版采用严格 JSON 文本动作，未接入原生 function calling 不得声称已接入，也不得静默退回固定流程冒充动态成功。
27. 动态循环从第一轮起强制模型决策次数、工具尝试、Token、上下文大小、绝对 deadline、重复无进展及取消上限；重规划、格式修正、失败尝试均计账，恢复不重置。模型 finish 不等于完成，Runtime 根据事前必需检查判断 completed/partial/insufficient；模型不得删检查来获得成功。2026-10-05 用户授权的 v2/Parent/Child 对未完成执行检查的 completed/insufficient finish 都返回 typed `required_checks_pending` 及固定检查 ID，在原额度内继续；连续两次无进展停止。已经实际检验出的不足可正常 insufficient，旧 v1 行为及历史失败保留。
28. 重规划、Tool、AgentTool 和 Child 均继承根请求带时区 cutoff、PIT、不可变快照及允许窗口/来源绑定；只可在已有授权范围内取证，不自动 refresh、换快照或用新的 cutoff 消除缺口。Child 有效工具/数据权限不超过父运行有效委派范围、可信应用授权、服务策略和 Child Spec 的交集；每次读、缓存复用和恢复都重授权。
29. Multi 复用 Single Runtime、Registry/Executor、Evidence/Trace/Checkpoint 和预算账本，Child 仅有独立的运行状态/消息/局部预算。从首个串行 Child 开始就受根剩余轮数/调用/Token 预算、嵌套 deadline 和取消约束；并行前原子预留，未知用量不释放，Child 禁止再次 spawn。不得另建一套绕过这些约束的 Multi Runtime。
30. 2026-10-05 明确授权范围止于 P4.3：Dynamic Parent 最多调用一个串行 Financial Child；Child 只读被委派的原绑定财务快照，模型不能改父证券/cutoff/PIT/窗口/来源或申请授权。不实现 Router、多个领域 Agent 或并行。根额度先持久预留；完整 Child 结果未知时整份保留，局部用量可验证时仅释放未用额度，未知模型 Token 预留不释放。
31. 同日用户随后明确要求“执行P4.4编写与检查验收”，覆盖第30条当轮范围限制：新版本Parent可在Financial/Market两个实际领域中选择普通工具或AgentTool，每域至多一个Child、总至多两个，严格串行；原P4.3身份/单Child约束保留。复用同一Runtime及根账本，禁止独立Router模型、P4.5并行、新Provider/采集扩张和交易。新有界验收使用独立额度和冻结合法输入，不重置历史账本或改旧评分。
32. 同日追加 P4.4 Context Remediation 只修复真实 `12325 > 12000 UTF-8 bytes` 阻塞，不启动完整 Phase 6 或 P4.5。采用版本化、确定性、无损的 scope/metadata 去重、Claim/Evidence 引用、历史 Observation 外置及按当前检查披露；不得提高 12000 上限、使用 LLM 摘要或有损裁剪。完整原对象、PIT/cutoff/snapshot/权限/血缘保留，引用不构成授权或完成证明，每次披露与恢复重授权。原002363请求及7 Facts/12 Evidence定点复测使用独立事前冻结的一项任务额度16决策/96000记账Token/480秒，Parent原局部240秒及其他限制不变；旧失败、分母和账本不改写。
33. 同日后续 P4.5 Parallel Multi/M3 请求覆盖第30–32条当轮禁止并行的范围限制，仅允许既有 Financial/Market Child 在同一 DynamicRuntime 上按显式 DAG 并行；深度仍为1。Parent在现有Run锁下是根账本唯一写者，两Child最大局部额度一次性持久原子预留，并保留Parent剩余局部额度。未知付费调用不重发、不释放；完整回执结算，恢复不重置、不重复导入。权限、SourceGrant、PIT、cutoff、snapshot、Artifact读与回父检查不能放宽，迟到结果不能进入Parent研究状态。12000 UTF-8字节冻结，无损目录与Lazy Disclosure保留；必需视图仍超限时partial/dynamic_context_budget_exceeded。Context/Parallel Telemetry只观测，不修改路由或阈值；Phase 5积累代表性Trace后，Phase 6才可做正式阈值校准。本轮不新增领域、Provider、Dataset、任意代码执行或交易，也不自动进入Phase 5。

## 变更纪律

2026-10-06最新用户明确授权Phase6首轮实际瓶颈诊断、一个最小版本化无损优化及有界验收，覆盖旧不自动Phase6边界。本轮仍固定12000 UTF-8字节，不做正式阈值调参、不改默认或扩大并行范围；仅既有合法案例、显式Child v3，最多3案例/6运行，独立campaign96父子决策/576000记账Token/1800秒，原父子局部限制、安全与原子根预留保持。每次读/缓存/披露/恢复重授权；未知付费结果停止新增外发且不重发、不释放。完整历史评分/失败/分母/paid wire/Checkpoint/冻结文件保持，先离线/权限/PIT/恢复/历史只读回放，再冻结版本/输入/源/oracle/评分/顺序/预算后真实运行；失败只在剩余额度与最多6运行内另冻结最小修复。不得进入下一阶段或以少样本宣称P95/统计优势。

2026-10-06 后续用户明确要求“若验收不通过，设计最小修改方案，并尝试重新验收”。授权只修复本轮688184并行Parent重复提前finish：新增显式`dynamic-parent-parallel-v2`可信执行进度/合法动作提示，旧v1默认/身份/paid wire保留。源、请求、oracle、Child v3、完成/重复规则和12000 cap不变；原8/9与失败不得覆盖，另冻结同案例16决策/96000记账Token/480秒复验，独立新任务0。如再次失败保留并继续有证据的修复，不盲重试或扩额度；不启动Phase6。

2026-10-06 用户明确授权推进 Phase 5，并批准本会话必要的外部模型请求。该请求解除此前“不自动进入 Phase 5”的当轮边界；只开展 PLAN 所列有界实际路线评估与评估 Trace 目录，不扩大金融 Dataset/Provider/Agent、不启动 Phase 6、不修改 12000 字节上限或默认 Child 协议。事前冻结范围与新预算，保留全部历史失败及同案例复验，不把九个配对路线运行计为九个独立任务。

同日后续Child任务推进修复授权：显式Financial/Market Child v2/v3只增加确定性执行状态、独立数据质量缺口、合法下一步候选和精确动作格式反馈；旧v1/v2身份、paid wire与checkpoint回放不变。重复动作仍拒绝且计入no_progress；finish仍由原required_checks验证，Child完成不代替Parent必需核验。原600500真实失败0/1与v2修复失败0/1完整保留，v3复验严格同输入/额度且标记同案例复验、独立新样本0；如失败须保留并继续有依据的诊断，不无依据重跑或提高预算。只有完整真实并行闭环才能通过P4.5，不自动进入Phase 5。

- 更新架构影响时同步 ARCHITECTURE；改变阶段范围同步 PLAN；每轮实现更新 STATUS。
- README 提供可复现命令；测试必须覆盖 PIT 修订、边界时间、权限缓存、并发去重、Schema 和错误分类。
- PostgreSQL 集成测试使用专用隔离实例或显式测试 DSN，禁止指向生产库。
- 不因工具可用就引入大型框架或自动创建多 Agent。
- 不自动部署、发布外部内容或提交交易。

## 暂不实现

LangGraph 强依赖、任意代码沙箱、分布式去重、向量库/知识图谱、消息总线、递归子 Agent、自动长期记忆、通用插件热加载。具体触发条件见架构与计划。
