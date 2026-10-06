# M1 收口与 P4.3 串行 Financial Child

日期：2026-10-05（Asia/Shanghai）。用户明确授权 Runtime typed premature finish rejection 及一个串行 Financial Child，本轮范围止于 P4.3。Router、多领域 Agent、并行和交易未实现。

## 交付行为

CLI `research --workflow dynamic` 默认显式使用 `single-dynamic-v2`。Runtime发现仍有not_completed必需执行检查时，拒绝completed或insufficient finish，记录`finish_rejected`，并向下一轮返回`required_checks_pending`/`pending_checks`。检查集合由原请求固定，模型不能自报或删除。拒绝仍消耗该轮决策和实际Token；连续两次无进展停止，deadline、取消和恢复沿用原账本。已经执行检验且证据不足时可正常insufficient。

`--dynamic-version single-dynamic-v1`支持旧Checkpoint恢复。Python库`DynamicSpec()`仍默认历史v1，使用v2需`DynamicSpec(version="single-dynamic-v2")`。旧固定overview/research身份与流程保留。

`--financial-child`仅允许dynamic/v2，选择`FinancialParentSpec`/`dynamic-parent-financial-v1`。模型用普通tool动作`financial_child`、refs=[]请求唯一财务委派；程序构造严格金融子请求，模型不提供授权、scope、证券、快照、cutoff或预算。Child仅有financial读取，不具备market、calculation、hypotheses、verification或再次spawn权限。

父与Child都走同一`DynamicRuntime.run`循环，复用Registry/ToolExecutor、数据层、Chat适配器、Evidence、Trace和Checkpoint。Child有独立UUID、消息、计划、局部计账及不可变请求身份。其任务是读取财务证据，不生成研究Claim；父导入financial Observation后执行既有确定性计算/假设/独立Fraction验证。

## 权限、预算与恢复

- Child工具交集为父有效工具/可见集、可信应用委派范围和ChildSpec；数据绑定仅从父Financial绑定取子集，再受Provider白名单和原服务实时SourceGrant约束。读、缓存、结果导入、完成回放均重授权和核验原附件；活动Child也检测父委派工具撤销。
- 父局部默认8决策/12工具/48000记账Token/240秒；根父子合计12决策/16工具/72000记账Token。Child最多3决策/1工具/18000记账Token/120秒，并在第一次Child模型派发前持久预留完整局部额度。父模型及AgentTool尝试同根消费。
- Child deadline=min(父/root绝对deadline,Child开始+120秒)，取消向下传播。迟到/取消的结果不导入父Evidence。已知合法Usage替换预留，累计预留另列；未知模型保留其Token预留；完整Child未知则整份额度保留，不把未知Child尝试数写作已知0。
- checkpoint恢复交叉核对原请求/Spec/deadline、paid intent/receipt、Trace及根events历史前缀。模型结果未知和Child/tool intent未收口时停止且不重发。完成父回放会递归验证Child和原源，零模型/Provider网络调用。
- `financial-child-result/v1`返回状态、固定请求哈希、来源结果哈希、记录/附件/快照/实际读取调用引用、检查和Usage。父JSON/Markdown只公开这些结构化摘要；财务行保留在受控checkpoint/数据层。父Evidence.tool_call_id与child_evidence_links关联实际Child读取。Child部分失败显式保留，父仍可在原权限/额度内选直接工具。

## 实际测试

470项全回归：纯离线457通过、13项PostgreSQL跳过；专用隔离PostgreSQL470/470通过，无跳过。日志`.runtime/phase4-p43-offline-final.log`与`.runtime/phase4-p43-postgres-final.log`。新增58项合成测试覆盖版本化协议、typed rejection继续及两次无进展、根预留/结算/篡改、权限撤销、Child禁止spawn、PIT/固定范围、取消/迟到、未知Child及完整回放。合成数值只证明机制，不是金融真值或真实Provider联调。

随后新增2项QA汇总和未知付费拒绝测试，最终**472/472隔离回归通过**（27.239秒、无跳过）；纯离线459通过、13跳过（26.717秒）。新增总数60。最终日志`.runtime/phase4-p43-postgres-complete.log`与`phase4-p43-offline-complete.log`，原470项日志保留。

## 两项真实功能验证

独立计划`.artifacts/phase4/p43-20261005/plan.json`，SHA `dd3f7e6ff97d751a147eabfb30aaf3257f1d3d51764a4101903cbf5737561955`。复用既有合法公开快照，输入契约2/2通过，事前最多两任务/20决策/120000记账Token/720秒。端点仅为test_api.txt配置的HTTPS，固定deepseek-v4-flash-0731，密钥仅认证、不入消息或发行包；没有新金融采集、模型替代或统计比较。任务是已知样例重用，不是独立盲测。

| 任务 | 实际决策 | 实测/记账Token | 工具 | 结果 |
|---|---:|---:|---|---|
| 002363 Financial Parent | 6 | 13398 | financial_child → market → calculation → hypothemses → verification | completed，全部父必需检查通过 |
| 同任务唯一Financial Child | 2 | 990 | financial → finish | completed，一次源读取，独立状态及Evidence关联 |
| 601009 M1 v2收口 | 6 | 11674 | financial → market → calculation → hypotheses → verification | insufficient；全部必需执行通过，缺2024Q1基数，不造同比 |

**功能2/2通过；父子总14决策、26062实测暨记账Token、104549累计派发预留、0未知用量、0新金融采集。** Child根账本8决策/6工具/14388Token（含AgentTool和Child读）；Child模型派发累计预留6261Token，未用局部额度已释放。完整两份报告已实际无网络回放一致。相关JSON、消息、intent、receipt、账本及Markdown均在`live/`。

本批模型没有提前finish，typed rejection实测触发次数为0；该修正路径由合成动态运行测试验证。小样本功能通过不证明广泛规划质量、来源准确性或Agent效率优势。10-04原M1 1/3与定点复测、Phase3旧分母及失败均保留。

## 保留的QA汇总失败与完成方式

首项报告及8次已知回执保存后，冻结QA脚本使用错误汇总key `passed`，实际`old.assess`返回`functional_passed`，因此停止；原`.runtime/phase4-p43-live.log`保留。该冻结脚本原代码/计划不回写，保留此次验证的准确执行记录。

`scripts/phase4_p43_complete.py`核对全部首项消息/回执/根报告，拒绝任何未知Usage，继承原账本、预算和绝对deadline，仅执行原计划尚未启动的601009任务，使用原Agent及原评分规则，正确读取functional_passed并补全summary。没有重发首项或重置成本。`known-continuation-intent.json`记录续跑脚本SHA、原报告SHA、原账本与原因；`.runtime/phase4-p43-complete.log`记录实际结果。当前首次执行脚本是历史冻结证据，不作为可重用新campaign入口。

无网络复核（需保留原输入/Artifact/本轮文件）：

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/phase4_p43_demo.py --replay
```

产品入口仍为`research --workflow dynamic --financial-child --question ... --with-model`；预览改用`--preview-model`，不会读源、创建Child、读密钥或付费。具体manifest与数据根需由可信应用绑定。

## 发行与密钥核查

已实际构建本地sdist：3307源码/旧证据文件及发行包60文件真实密钥精确匹配0，禁入文件0，Dynamic及root_budget模块齐全；本轮81个结果/日志（含checkpoint SQLite）精确密钥匹配0。未验证wheel，未对外发布。结果为`distribution/check.json`与`final-integrity.json`；密钥只在内存中比较，不打印、不写结果值。
