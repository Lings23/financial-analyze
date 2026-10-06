# 股票研究数据层与 Single Agent

2026-10-06 Phase6首轮限定验收完成：显式Parent v3只优化无损metadata表示，baseline Parent v2、Child显式v3；两已有case四真实运行及只读回放均4/4通过。实际父子Token少4.59%、同状态wire净省3414字节，未证实延迟改善；12000字节及旧默认/身份/恢复/安全限制保持。原Phase5 8/9与Parent v2同案例复验1/1分别保留，不扩大并行启用、不进入下一阶段。完整诊断、冻结Trace、失败/跳过、实际账本和可复现命令见[Phase6首轮记录](docs/PHASE6_FIRST_ROUND_20261006.md)。

Phase6冻结结果可零模型/Provider/Checkpoint追加只读复验（完整测试与历史审计串行运行）：

```powershell
$env:PYTHONPATH = 'src'
& .venv\Scripts\python.exe scripts/phase6_evaluate.py --replay --plan-sha256 2b80c8622949757194d298155f315bdac23fd2d25da1edd228bd23630edab5e1
```

Phase 1 已按调整后的日频首版范围验收；Phase 2 已交付固定流程的单股研究概览，带聚合工具、确定性计算、证据、预算、恢复与 Markdown/JSON 输出。2026-10-02 经明确批准完成一次真实 DeepSeek 联调及无额外模型调用的回放；整体 Agent 成功率尚未完成独立真实评测。

## 文档入口

- [架构设计](docs/ARCHITECTURE.md)：原方案 22 项设计与取舍。
- [实施计划](docs/PLAN.md)：Phase 0–6、Phase 1 工作包与验收门槛。
- [开发约束](docs/CONSTRAINTS.md)：PIT、来源、权限、阶段边界。
- [执行状态](docs/STATUS.md)：已实现、实际测试与未完成事项。
- [AKShare 接口候选清单](docs/AKSHARE_INTERFACE_CANDIDATES.md)：内置检索层筛选的后续数据对象与验证顺序。
- [AKShare 网络与 PIT 验证](docs/AKSHARE_VALIDATION.md)：候选接口小样本实测、代理对照和历史版本边界。
- [三源覆盖与 Phase 1 验收](docs/SOURCE_COVERAGE_AND_PHASE1_ACCEPTANCE.md)：AKShare、Tushare、CNINFO 对六类业务域的输入覆盖及验收缺口。
- [P1.7 真实数据验收方案](docs/P17_REAL_DATA_ACCEPTANCE.md)与[执行记录](docs/P17_ACCEPTANCE_RUN_20260930.md)：预登记样本、独立原文对照、持久数据库回放及未通过项。
- [P1.7 行情与持续调用](docs/P17_MARKET_AND_QUOTA_20261001.md)：450/666独立指标核对、来源精度及54次共享24次/分钟调用。
- [P1.7 日期精度历史 PIT](docs/P17_RELEASE_DATE_PIT_20261001.md)：两份明确核对的 CNINFO 原版/更正稿、次日边界、授权附件和持久重启回放。
- [P1.9 有界分页及复测](docs/P19_BOUNDED_PAGINATION_20261001.md)：原三实时接口单页一次尝试、完整分页检查和源证据授权；真实全表仍失败。
- [P1.7 官方原文扩展](docs/P17_REFERENCE_EXTENSION_20261001.md)：18 个财务期间、48 项独立财务比较及标准 Provider v2 归档验证。
- [P1.8 分项验收记录](docs/P18_ACCEPTANCE_RUN_20260930.md)：日历、复权、指数、两张新增报表、公告和新闻适配的证据与缺口。
- [P1.8 实施与首版验收](docs/P18_IMPLEMENTATION_AND_ACCEPTANCE_20261001.md)：最新三源接入、近期新闻范围、真实原文对照与重启回放。

## 已有能力

2026-10-02 已追加 Phase 3 有界 Single Research：五类固定假设检验、支持/反证/冲突/缺口、合格事件时间锚点、独立 Fraction Claim 校验与无损上下文引用。Phase 3 广泛真实模型/专家质量认证尚未完成；实现与实际执行结果见 [记录](docs/PHASE3_IMPLEMENTATION_20261002.md)。

本轮质量验收补齐原归档同期窗口，19/25财务假设可判定；全部129假设仍有110不足。用户具体批准后完成29次DeepSeek请求，原质量23/29=79.3%低于85%，175数值/325证据/29无网络回放通过。报告系统核对补充后29/29展示通过，原模型分数不改，整体仍未通过。默认CLI/生产库尚未自动物化归档投影，下一轮指令方案未实测，详见 [阻塞与修复方案](docs/PHASE3_QUALITY_ACCEPTANCE_20261002.md)。

- 统一证券、日期窗口、Decimal 数值与单位、数据来源、修订版本和时间依据。
- Tushare 日频未复权 OHLCV、合并累计利润表核心字段。
- Tushare 沪深日历、复权因子、指数日线/月度权重、合并资产负债与累计现金流核心字段；CNINFO 公告 PDF、AKShare 近期新闻索引与匹配原文 HTML。
- public / system 两种 PIT 查询，先过滤可见版本再选择最新版本。
- PostgreSQL 不可变记录/快照、事务写入、内容寻址原始结果归档。
- Provider 能力注册、显式 fallback、有限重试、限流、进程内在途合并与 TTL 缓存。
- 离线合成演示、标准库测试和真实 PostgreSQL 集成测试。
- AKShare 七接口的受控采集与范围隔离的不可变捕获快照；当前仅保存观察时点的数据表。

## 安装与离线验证（PowerShell）

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[postgres]'
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m stock_research demo
```

未配置专用 PostgreSQL 测试 DSN 时，集成测试会明确 skip，其他测试不需要网络、Token 或数据库。演示全部使用合成值，不是真实股票财务数据。

只运行标准库部分也可使用 `PYTHONPATH=src`，无需安装数据库驱动。2026-10-01 最终实测：离线123项中112通过、11项PostgreSQL跳过；隔离PostgreSQL测试容器中123项全部通过。已安装的可选AKShare SDK参与三接口合成字段映射回归，不能当作真实金融验证。

## AKShare 临时数据来源

安装 AKShare 可选依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[akshare]'
```

七个指定接口可用一条命令逐一采集；`--date` 是深交所总貌请求日期，两个热度接口使用 `--symbol` 六位股票代码。`--endpoint` 可只运行其中一个接口，单独运行非深交所接口时可省略 `--date`。

```powershell
.\.venv\Scripts\python.exe -m stock_research akshare-check --scope local --date 2026-09-24 --symbol 600000 --timeout 30
.\.venv\Scripts\python.exe -m stock_research akshare-check --scope local --endpoint stock_sse_summary
```

命令仅输出各接口状态、列名、行数、捕获时间和快照 ID，不输出整张行情表。成功时，AKShare 转换后的数据表保存于 `.artifacts` 的 scope 隔离目录；读取时必须提供同一 scope、快照 ID 和带时区 cutoff：

```powershell
.\.venv\Scripts\python.exe -m stock_research akshare-read --scope local --snapshot <snapshot_id> --as-of 2026-09-28T18:00:00+08:00 --mode system
```

捕获快照仅从实际捕获时刻起可见。上交所函数返回最近可得报告日，深交所函数按指定日期请求；实时行情没有交易所级逐行发布时间。千股千评的历史行是当前抓到的版本，不能据行内交易日推断当时可见。当前未将这些不同粒度的数据纳入 `DataService` 的单证券历史查询，也未与 Tushare 配成自动 fallback。归档是 AKShare 解析后的表，并非上游原始 HTTP 响应；没有独立准确率核验。

当前 AKShare 版本的上交所与深交所总貌函数在内部使用 HTTP，快照带 `upstream_transport_unverified` 标记。`akshare-check` 每接口仅做一次调用，使用隔离子进程在 `--timeout` 后终止；上游分页可能使全市场实时行情比单股接口耗时更长。失败会逐项记录安全的错误类别，不把空响应说成完整覆盖。

## DeepSeek 模型接入

已通过用户提供的 `test_api.txt` 接入阿里云百炼兼容接口，使用指定模型 **`deepseek-v4-flash-0731`**，不替换为其他别名。此适配器是独立基础能力，不依赖 Tushare 或 PostgreSQL，也不代表完整研究 Agent 已完成。

配置文件格式如下（示例均为占位符，保留本机真实文件即可）：

```text
Base URL:https://<your-workspace>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
API KEY:<your-api-key>
```

`test_api.txt` 已加入 `.gitignore` 和发行包排除规则；程序只读取凭据，不生成副本，不回显密钥。可用 `--config` 显式指定另一份同格式本机配置。

连接验证会发送一次最小请求并消耗少量模型配额：

```powershell
.\.venv\Scripts\python.exe -m stock_research llm-check --config test_api.txt
.\.venv\Scripts\python.exe -m stock_research llm-chat --config test_api.txt --prompt "请用一句话解释证据可追溯性。" --max-tokens 128
```

`llm-check` 要求回复 `OK`、结束原因为 `stop` 且响应模型名与请求完全一致，才报告 `verified`。`llm-chat` 返回模型正文及 Usage；若达到长度上限则标记 `truncated` 并返回非零退出码。未知 Usage 保持 null，不伪装成零成本。

默认非流式、关闭思考，最大输出 256 Token（检查命令 16）、超时 30 秒；适配器限制输出不超过 4096 Token、输入文本不超过 32000 字符。禁止重定向，错误消息不包含网关原始响应或密钥，没有自动重试或隐式模型回退。Socket 超时并非严格的进程硬截止时间。

独立适配器使用文本协议。Phase 2 `research` 通过严格 JSON 选择已有事实并校验数值血缘；Phase 4 M1 新增严格JSON动作动态循环（应用层工具调用，未接入原生tool_calls）。开放式事实生成未实现。`llm-chat` 是开发者模型调用入口，其内容不能直接作为已验证金融研究报告。

## PostgreSQL 配置

通过进程环境配置 `STOCK_RESEARCH_DSN`，然后执行：

```powershell
.\.venv\Scripts\python.exe -m stock_research migrate
```

DSN 仅从环境读取，不作为命令参数输出。表位于 `stock_research` schema。记录、快照和成员关系有禁止 UPDATE/DELETE 的触发器，迁移可重复执行。当前 schema v2：`schema_v2.sql` 追加新记录类型标识，保留 v1 payload/快照；未来变更继续新增有版本的迁移。

数据库连接角色是可信内部角色；应用通过 scope 隔离访问，尚未实现供不可信用户直接连接数据库的 RLS/多租户认证服务。

## 采集与查询

从项目根目录运行 CLI 时，`ingest` 优先读取进程环境变量 `TUSHARE_TOKEN`；未设置时读取项目本地、已忽略的 `.env` 中唯一一行 `TUSHARE_TOKEN=<token>`。`tushare.txt` 和 `.env` 均不纳入 Git 或源码发行包；不要在聊天中发送 Token。`STOCK_RESEARCH_DSN` 仍需通过进程环境配置。首批 HTTPS Transport 不降级 HTTP、不跟随重定向；股票列表、日线、利润表已做真实调用。P1.7 的 18 次请求、120 条规范化记录和官方 PDF 小样本核对见[执行记录](docs/P17_ACCEPTANCE_RUN_20260930.md)；其他接口仅有单接口探针，持续配额仍待核验。

采集示例（命令会使用真实账号配额）：

```powershell
.\.venv\Scripts\python.exe -m stock_research ingest --scope local --symbol 600519 --exchange SSE --dataset market_daily --start 2025-03-01 --end 2025-03-31
.\.venv\Scripts\python.exe -m stock_research ingest --scope local --symbol 600519 --exchange SSE --dataset financial_income --start 2024-12-31 --end 2024-12-31
```

返回 `snapshot_id`。增量合并已有记录时显式添加 `--parent-snapshot <id>`，否则每次生成仅含本次数据的快照。Artifact 默认保存在当前目录 `.artifacts`，不能删除仍被快照引用的内容。

查询示例（用实际快照 ID 替换占位符）：

```powershell
.\.venv\Scripts\python.exe -m stock_research query --scope local --symbol 600519 --exchange SSE --dataset financial_income --start 2024-12-31 --end 2024-12-31 --snapshot <snapshot_id> --as-of 2025-02-01T23:59:59+08:00 --mode public
```

查询只读已保存快照，不触发网络。`--scope` 是可信本机操作者选择的数据命名空间，不是对远程不可信用户的认证机制。通用历史名称/代码映射尚未建立；CNINFO 可显式配置固定SHA、scope、orgId与请求窗口的北交所旧码资格，当前仅核实四家公司、11个公告请求。

## 时间语义

日频查询窗口指 trade_date，利润表窗口指 report_period，二者都包含起止日，单次最多跨 366 天。Tushare income 的 start_date/end_date 是公告日期过滤，不把它们误当报告期，因此本版按单只股票读取有界历史响应后本地过滤报告期。

Tushare 当前接口返回值并不证明“当时的内容版本”。因此 `available_at` 保守地取响应抓取完成时间；`ann_date`、`f_ann_date` 保留作来源元数据，不能回填历史可见性。新采集数据用于早于采集时点的历史查询，通常返回 `no_visible_data`，这是预期保护。

只有已经资格核对的 Provider 才允许提供历史可见记录。精确时间使用 `verified_release`；仅发布日期使用 `verified_release_date`，保留 `published_at=NULL`，最早次日零点（+08:00）可见。当前仅明确核对的 300122 两份 CNINFO 文件支持日期精度，普通三源抓取仍为 `observed_at`。`system` 另外检查实际入库时间；重复提交缓存捕获结果保持首次入库时间。真实日期精度回放：`python scripts/run_p17_release_date.py --verify-only`（需原持久验收库和归档文件）。

`status=available` 仅表示有可用记录，**不表示窗口数据完整**。没有交易日历/披露覆盖检查时始终返回 `coverage=not_verified`。停牌、缺失、未上市不能被推断为零收益或零成交。

## 重试、缓存与 fallback

默认总采集预算 30 秒、单次 10 秒、最多 3 次尝试、每 Provider 启动间隔 1 秒、并发 2。真实配额可能更严格，需调整 ExecutionPolicy。Fallback 共用总 deadline。

只重试显式瞬时网络/HTTP 错误；认证、未知 API 错误、Schema 错误不盲目重试。只有调用方配置并授权的兼容 Provider 才能 fallback；正式来源已有 Tushare、CNINFO 公告及 AKShare 近期新闻，但没有已验证的同口径三源 fallback，失败返回错误。

采集缓存是“当前数据捕获”缓存，键含 scope、来源权限、Provider/版本、证券、窗口和口径；不含研究 cutoff，因为采集不回答历史问题。历史查询没有缓存，始终对固定快照执行 PIT。未来增加查询缓存时必须包含 cutoff/mode/snapshot。

缓存默认最多 128 项、TTL 60 秒；不缓存失败和空响应。采集完成后持久化的记录和快照不随 TTL 消失。去重仅对同一个进程中的同一 Executor 有效。

标准库线程无法强制终止违约 Provider；调用者等待有 deadline，HTTP 有 socket/响应体限制，晚到结果丢弃。后台任务可能需要等待当前 socket 超时退出，因此不把配置秒数宣称为进程终止的硬实时 SLA。

## 集成测试

对专用临时数据库设置 `STOCK_RESEARCH_TEST_DSN` 后运行全部测试。测试会新增随机命名的 scope，不删除数据库既有业务记录；不要使用生产 DSN。

也可自动创建并回收一个仅绑定 127.0.0.1、无持久卷的测试容器：

```powershell
.\scripts\test-postgres.ps1 -Image postgres:16
```

需要已运行的 Docker 与项目 `.venv`。脚本不使用生产库，测试容器停止后自动删除。

常规 Tushare 日线/利润表 Provider v2 将请求字段的全部返回行归档后再筛选报告期，记录响应/选中行数、字段顺序和带时区调用起止时间。归档排除密钥、消息、额外字段和请求头；旧 v1 不可变记录不改写。真实年报验证保存 123 行、选中 1 行。

## P1.7 持久验收库与回放

专用验收容器 `stock-research-p17` 使用 Docker 命名卷 `stock-research-p17-data`。启动脚本会在被忽略的 `.runtime/p17-dsn.txt` 保存本机 DSN；容器重启后会刷新随机映射的本机端口。该库只绑定 127.0.0.1，与上面的临时测试容器隔离。

```powershell
.\scripts\start-p17-postgres.ps1
.\.venv\Scripts\python.exe scripts/run_p17_pilot.py --replay-only
.\.venv\Scripts\python.exe scripts/check_p17_quality.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_revision.py --verify-only
```

验收原始响应、官方 PDF 和比较结果保存在被忽略的 `.artifacts/p17_20260930/` 和 `.artifacts/p17_20261001/`；冻结样本和独立参考值在 `evaluation/`。结果是小样本通过、P1.7 整项未通过，详见执行记录、官方参考扩展及行情/持续调用报告。新增无网络复核命令为 `scripts/run_p17_quota.py --verify-only`、`scripts/check_p17_sse_market.py --verify-only`、`scripts/check_p17_szse_precision.py` 和 `scripts/check_p17_combined_quality.py`。补充核验可执行 `scripts/check_p17_reference_extension.py --verify-only` 与 `scripts/check_p17_operational.py`，不发起供应商网络调用，需原证据及 pdftotext。

## 研究与动态Agent入口

Phase 3 现可通过 `research --workflow research` 运行。请求沿用既有 `symbol/exchange/as_of/mode/bindings/benchmark`，增加 `objective`（`single_stock_research` 或 `event_review`）、`hypotheses` 和可选 `event_record_id`。事件复核必须显式提供可见来源记录 ID 并包含 `event_chronology` 检验。固定目录为 `mechanical_adjustment`、`market_direction`、`financial_deterioration`、`cashflow_divergence`、`event_chronology`；省略时检验全部五项，缺来源或同报告期基数会返回证据不足。

Phase4 M1已提供`research --workflow dynamic --question ... --with-model`：模型逐轮规划/选工具/观察/请求结束，程序独立核对必需检查和精确事实；`--preview-model`仅生成首轮消息、不执行工具或付费调用。输入仍需可信应用确认的StudyRequest证券/窗口/PIT/快照与必需假设，question不能扩大能力或授权。默认8决策/12工具/48000预算记账Token/240秒，独立Spec保持旧固定回放。

2026-10-05 CLI动态默认`single-dynamic-v2`：尚有未执行检查的finish返回`required_checks_pending`类型化反馈，在原决策/Token/deadline额度内继续；`--dynamic-version single-dynamic-v1`可恢复历史v1。Python库`DynamicSpec()`仍保留v1，v2需显式指定。

P4.3兼容入口`--financial-child`（仅dynamic/v2）：父运行可串行调用唯一受限Financial Child，Child只读父原绑定的财务快照并回传结构化来源/Evidence/Usage，父再执行计算与检验。根总上限12决策/16工具/72000记账Token；Child先预留最多3决策/1工具/18000Token/120秒，截止不晚于父，取消传播，未知结果不自动重发或释放额度。该模式仍使用原`dynamic-parent-financial-v1`身份和root-budget/v1；预览不会启动Child：

```powershell
.\.venv\Scripts\python.exe -m stock_research research --workflow dynamic --financial-child --request .artifacts/phase3/real-initial/example-request.json --scope p17-formal-20261001 --allow-provider tushare --artifacts .artifacts/p17_20261001/formal/artifacts --runs .runtime/phase4-child-cli --output .artifacts/phase4/child-preview --question '读取已绑定财务证据，核对原清单要求的检验' --preview-model
```

同日后续授权的P4.4新增`--domain-agents`（仅dynamic/v2，与`--financial-child`互斥）。Context Remediation 后新CLI运行默认使用`DomainParentSpec`/`dynamic-parent-domains-v2`；原版本用`--domain-version dynamic-parent-domains-v1`显式固定。该模式仍严格串行，每领域最多一个Child、合计最多两个。Financial Child只读原财务绑定，Market Child只读原`market_daily`及已绑定的`trade_calendar`/`adjustment_factor`，均继承父cutoff/PIT/快照和权限。父负责数值计算、假设与独立验证，没有独立Router模型。

P4.5新增显式`--parallel-domains`（仅dynamic/v2，与上述两模式互斥；不接受`--domain-version`）。同一DynamicRuntime使用独立ParallelParentSpec，Parent可选择普通直接/串行tool动作，或`{"action":"parallel","tools":["financial_child","market_child"],"plan":["读取两个独立必要来源，再合并检验"]}`。只有两个源尚未启动且相互独立时可并行，可信DAG强制calculation→hypotheses→verification等待依赖。root-budget/v3在Parent Run锁下一次预留两Child最大额度并保留Parent剩余局部预算，深度固定1；恢复不重付费、不重复导入，未知调用不重发。12000字节冻结、原无损上下文保留，所有新Dynamic运行开始采观测Telemetry。实际验收及边界见[P4.5记录](docs/PHASE4_P45_IMPLEMENTATION_20261005.md)，不自动进入Phase 5。

预览可沿用下方命令，将`--domain-agents`替换为`--parallel-domains`并选择新的输出目录；实际运行再用`--with-model --config test_api.txt`。恢复并行checkpoint时保留同一模式、请求、question和配置，使用`--resume <run_id>`。

Phase5失败修复增加显式`--parallel-version dynamic-parent-parallel-v2`，仅与`--parallel-domains`搭配；默认仍`dynamic-parent-parallel-v1`。v2把原Runtime必需执行检查进度和精确下一步候选放入模型输入，证据不足仍须完成verification；不自动执行候选，不改完成检查、重复停止、预算或12000上限。新v2运行/恢复需保留同一显式版本，旧v1输入和身份保持。

2026-10-06明确授权的Phase 5增加独立路线评估脚本，固定三项已知合法源任务×direct/serial/parallel九个真实运行，Child显式v3。先冻结任务、准确动作格式、源授权/oracle、源码与预算，再外发；预算120父子决策/720000记账Token/2400秒。只复用本地不可变源，金融Provider网络请求为零。目录只建立一次，重复`--prepare`或`--live`拒绝，失败/未知调用保留且不重发。`--replay`只读回放，既不付费也不追加Checkpoint：

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/phase5_evaluate.py --prepare
$phase5PlanSha=(Get-FileHash -LiteralPath .artifacts/phase5/targeted-20261006/plan.json -Algorithm SHA256).Hash.ToLowerInvariant()
.\.venv\Scripts\python.exe scripts/phase5_evaluate.py --live --plan-sha256 $phase5PlanSha
.\.venv\Scripts\python.exe scripts/phase5_evaluate.py --replay --plan-sha256 $phase5PlanSha
```

这组命令要求原Phase3/P4冻结文件与公开源归档仍在本机；`--live`向`test_api.txt`的配置端点进行有界付费模型请求。新目录保存完整报告/Trace/消息回执/Checkpoint/评估数据哈希；旧P4.5失败及v2/v3同案例复验单列历史，不计新任务。合法非正基数不足与完成研究结论分开，三任务分母不膨胀为九。结果与启用决定见[Phase 5记录](docs/PHASE5_EVALUATION_20261006.md)和STATUS；默认协议、12000字节上限保持，Phase6未启动。

后续Parent v2最小修复只复验原688184并行案例，使用单独不可覆盖目录与16决策/96000记账Token/480秒预算。要求原冻结源码副本`.artifacts/phase5/parent-progress-original-source-20261006`及原全部证据仍在；每个原文件逐hash核验。复验不贡献独立新任务，不改原8/9或原九运行启用决定：

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/phase5_parent_repair.py --prepare
$phase5RepairPlanSha=(Get-FileHash -LiteralPath .artifacts/phase5/parent-progress-v2-20261006/plan.json -Algorithm SHA256).Hash.ToLowerInvariant()
.\.venv\Scripts\python.exe scripts/phase5_parent_repair.py --live --plan-sha256 $phase5RepairPlanSha
.\.venv\Scripts\python.exe scripts/phase5_parent_repair.py --replay --plan-sha256 $phase5RepairPlanSha
```

新root-budget/v2默认父子合计16决策/18工具/96000记账Token；Parent局部仍8/12/48000/240秒，每Child仍最多3/1/18000/120秒。派发前持久预留，根预算不足时不启动Child；未知额度保留、取消向下传播，恢复不重置账本或重发未知结果。Parent只接收有限的委派状态/结果哈希以及授权的普通源Observation，不能从模型获取金融值。仅预览首轮Parent消息可执行（本机原数据及授权仍须存在，输出目录须为新目录）：

新v2使用无损目录和按需上下文表示，消息上限仍为12000字节。JSON保留Runtime的完整context元数据；Markdown展示目录引用、披露阶段与消息字节，同时保留全部事实、Evidence和实际Trace。首轮预览只写消息及其表示元数据，不调用模型、数据工具或Child。该版本的实际验证结果继续以STATUS为准。

```powershell
.\.venv\Scripts\python.exe -m stock_research research --workflow dynamic --domain-agents --request .artifacts/phase3/real-initial/example-request.json --scope p17-formal-20261001 --allow-provider tushare --artifacts .artifacts/p17_20261001/formal/artifacts --runs .runtime/phase4-domains-cli --output .artifacts/phase4/domains-preview --question '按原绑定检验选择直接工具或委派，核对可见财务和行情' --preview-model
```

需要实际运行时，用`--with-model --config test_api.txt`替换`--preview-model`并使用新的输出目录；这会启动有界父子付费模型调用。恢复须保留原manifest、question、模型启用方式、对应模式及版本。原P4.4 v1 checkpoint恢复时，保留原命令并追加`--domain-version dynamic-parent-domains-v1 --resume <run_id>`和新输出目录。`--domain-version`只在`--domain-agents`模式下有效；未启用该模式而显式指定版本会拒绝。Single dynamic v1/v2、P4.3 Financial Child及两个Child身份和上下文上限保持。P4.4最终回归与真实功能结果以[STATUS](docs/STATUS.md)的实际记录为准；不以来源Child机制测试宣称金融真值、广泛路由质量或并行能力。

此前P4.3验收472/472隔离最终回归通过（含60项新增合成机制/QA边界测试）；真实功能2/2通过，父子合计14决策/26062实测Token/0新金融采集。完整边界见[P4.3记录](docs/PHASE4_P43_IMPLEMENTATION_20261005.md)和[STATUS](docs/STATUS.md)。历史M1结果与失败保留，旧演示QA冻结源码哈希在当前新代码上会按设计拒绝；v1产品Checkpoint兼容由回归覆盖，不重写历史freeze。

此前M1验收412/412隔离回归通过；真实演示原3题1/3通过、两个提前结束失败保留。000531明确原必需步骤的定点新运行通过，合计22决策/37832实测Token/0新金融采集；不宣称原3题全通过或广泛规划质量。中文报告、实现边界、累计预留与实际预算、CLI及无网络回放命令见[Phase4 M1交付记录](docs/PHASE4_M1_IMPLEMENTATION_20261004.md)。

以下命令读取本机既有冻结数据，并生成研究报告和精确模型预览；没有模型或金融 Provider 调用。输出目录必须不存在：

```powershell
$env:PYTHONPATH='src'
$env:STOCK_RESEARCH_DSN=(Get-Content -LiteralPath .runtime/p17-dsn.txt -Raw).Trim()
.\.venv\Scripts\python.exe -m stock_research research --workflow research --request .artifacts/phase3/real-initial/example-request.json --scope p17-formal-20261001 --allow-provider tushare --artifacts .artifacts/p17_20261001/formal/artifacts --runs .runtime/phase3-cli --output .artifacts/phase3/cli-example --preview-model
```

证据不足的报告正常写出 Markdown/JSON，CLI 返回 2，不能用退出 0 冒充完整研究成功。`--preview-model` 与 `--with-model` 互斥；后者会向 `test_api.txt` 指定端点发起最多一次 `deepseek-v4-flash-0731` 付费调用，不能将此前具体批次授权视作不限量调用许可。Phase 3 已执行用户批准的29次真实验收，原选择质量未达门槛；支持状态由确定性规则产生，模型不能修改或生成因果结论。报告将遗漏依据另标“系统核对重点”，只补既有已校验Claim，原模型回答/评分和JSON不变。

可复现实验（真实离线复核需原持久验收库和 Artifact）：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_phase3.py --output .artifacts/phase3/synthetic-new
.\.venv\Scripts\python.exe scripts/accept_phase3_real.py --output .artifacts/phase3/real-new
.\.venv\Scripts\python.exe scripts/accept_phase3_event.py --output .artifacts/phase3/event-new
```

合成数据仅验证机制。50 个真实单股案例复用原数值 oracle，五类假设均缺必需输入，250 次证据不足判定不是250个实质研究成功；6个历史事件边界仅核对资格、PIT与缺证据处理，不证明真实事件影响。正文提取、自由假设/自然语言、行业/估值/流动性及广泛真实模型 L3/L5 质量尚未认证。

P1.7新增25股扩大分层样本：75次Tushare请求、489条不同持久记录/488可见事实；原1536行情/942缺参考报告保留；[深交所归档扩展](docs/P17_SZSE_ARCHIVE_20261001.md)及[北交所日K补充](docs/P17_BSE_DOM_MARKET_20261001.md)后1944一致、72量额差异、462缺参考，72停牌缺行经原文单列。原113财务PDF另加瑞丰摘要1份、康佳年报2份及北交所18份，共134份覆盖全部75期，独立核对218/225项，218精度内一致、7项缺独立对应口径；原六股666分母保持，归档及单日补充后531一致、27差异、108未验证，原450报告保留。[采样报告](docs/P17_FORMAL_SAMPLE_20261001.md)、[财务核对](docs/P17_FORMAL_FINANCIAL_VALUES_20261001.md)、[北交所限定身份资格](docs/P17_BSE_IDENTITY_20261001.md)。命名卷实际重启后全部75组和新增11组公告回放通过。无网络回放（需原库和文件）：

```powershell
.\.venv\Scripts\python.exe scripts/run_p17_formal.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_formal_market.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_formal_strata.py
.\.venv\Scripts\python.exe scripts/check_p17_formal_financial_references.py
.\.venv\Scripts\python.exe scripts/check_p17_formal_financial_values.py --review evaluation/p17_20261001_formal_financial_values_manual_review.json --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_rural_bank_reference.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_rural_bank_reference.py --case konka --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_bse_qualified_references.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_bse_dom_reference.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_formal_financial_values.py --review evaluation/p17_20261001_bse_financial_values_review.json --verify-only
```

无网络复核深交所归档可执行`scripts/collect_p17_szse_archive.py --verify-only`及`scripts/check_p17_szse_archive_extension.py --verify-only`；两条应返回2，重现未解决量额差异。单日补充后当前为441一致/99差异/0缺参考；执行`scripts/run_p17_szse_archive_gap.py --verify-only`也应返回2。`scripts/check_p17_szse_block_diagnosis.py --verify-only`返回0只证明单日大宗证据及算术回放一致，量额残差仍未闭合。

量额差异、广泛独立质量、三表跨日配额和历史版本覆盖转为后续补充；精确日内公开时间、历史新闻与完整 Benchmark 仍待扩展。Phase 1 按 2026-10-01 用户调整的日频首版范围验收通过，原全范围测试并未因此通过。Phase 2 当前交付固定 Single 首版；参见 STATUS。

## P1.8 扩展数据域

八个 Dataset：`trade_calendar`、`adjustment_factor`、`index_daily`、`index_weight`、`financial_balance`、`financial_cashflow`、`announcement`、`news_recent`。日历 kind 为 exchange、指数为 index，其余为 equity；类型不能互换。日历只支持 SSE/SZSE，财务为合并口径核心字段，权重是月度观察值。

```powershell
$env:PYTHONPATH='src'
$env:STOCK_RESEARCH_DSN = (Get-Content -LiteralPath .runtime/p17-dsn.txt -Raw).Trim()
.\.venv\Scripts\python.exe -m stock_research migrate
.\.venv\Scripts\python.exe -m stock_research domain-ingest --scope local --kind exchange --code SSE --dataset trade_calendar --start 2026-09-28 --end 2026-10-09 --provider tushare
.\.venv\Scripts\python.exe -m stock_research domain-ingest --scope local --kind index --code 000300.SH --dataset index_daily --start 2024-09-18 --end 2024-09-30 --provider tushare
.\.venv\Scripts\python.exe -m stock_research domain-ingest --scope local --kind equity --code 000001 --exchange SZSE --dataset announcement --start 2025-03-15 --end 2025-03-15 --selector '2024年年度报告' --provider cninfo
```

采集使用真实配额并返回固定快照。CNINFO 公告走公开索引和原始 PDF，不依赖未获权限的新闻 API。新闻首版按用户确认只接受采集后可见的近期新闻；摘要与原文 HTML 分别保存，核对当前公司名称或正确证券代码，数字数量和网页侧栏不建立证券归属。

```powershell
.\.venv\Scripts\python.exe -m stock_research domain-query --scope local --kind equity --code 000001 --exchange SZSE --dataset announcement --start 2025-03-15 --end 2025-03-15 --snapshot <snapshot_id> --as-of 2026-10-01T01:00:00+08:00 --mode system --providers cninfo
.\.venv\Scripts\python.exe -m stock_research domain-evidence --scope local --kind equity --code 000001 --exchange SZSE --dataset announcement --start 2025-03-15 --end 2025-03-15 --snapshot <snapshot_id> --as-of 2026-10-01T01:00:00+08:00 --mode system --providers cninfo --record <record_id> --artifact <pdf_artifact_id> --output report.pdf
```

正文读取检查相同权限/PIT，再验证附件属于可见记录；已有输出文件禁止覆盖。所有来源为 `observed_at`，行内日期与新闻标称时间不能倒填历史可见性；覆盖仍为 `not_verified`。

真实证据在 `.artifacts/p18_20261001/`；[验收报告](docs/P18_IMPLEMENTATION_AND_ACCEPTANCE_20261001.md)列出冻结计划、16 请求、375 可见事实、官方 PDF 对照及重启回放。离线回放：

```powershell
.\.venv\Scripts\python.exe scripts/run_p18_acceptance.py --label attempt2 --replay-only
.\.venv\Scripts\python.exe scripts/check_p18_quality.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p18_cli.py
```


## Phase 2：单股研究概览

请求必须固定证券、cutoff、PIT、每个数据集的窗口/快照/唯一来源；最低包含 `market_daily` 与 `financial_income`。支持追加 `trade_calendar`、`adjustment_factor`、`index_daily`（显式 benchmark）、`financial_balance`、`financial_cashflow`、`announcement`、`news_recent`。示例清单见 [601009 冻结请求](evaluation/phase2_real_601009.json)，该清单依赖本机 Phase 1 已保存的数据。

```powershell
$env:PYTHONPATH='src'
$env:STOCK_RESEARCH_DSN = (Get-Content -LiteralPath .runtime/p17-dsn.txt -Raw).Trim()
.\.venv\Scripts\python.exe -m stock_research research --request evaluation/phase2_real_601009.json --scope p17-formal-20261001 --allow-provider tushare --artifacts .artifacts/p17_20261001/formal/artifacts --output .artifacts/phase2/my-overview
```

默认仅本地读取与计算，没有模型或金融 API 网络调用。`--allow-provider` 和 `--artifacts` 可重复；所有快照必须属于当前授权 scope。`--scope` 是可信本地 CLI 参数，不提供远程登录鉴权。输出目录必须不存在；生成 `report.md` 和 `report.json`。退出码 0 表示流程完成，2 表示部分结果或已分类错误，3 表示其他失败；`completed` 不表示数据覆盖或准确率认证，仍须检查 gaps 和 coverage。

显式加 `--with-model --config test_api.txt` 才会把已算事实的名称/值/单位/窗口交给指定 DeepSeek 端点作最多三个重点选择；每次运行最多一次付费调用，无自动重试或模型替换。2026-10-02 用户明确批准 `.artifacts/phase2/proposed-model-messages.json` 中的 5 条事实后，单次真实联调通过；[已联调报告](.artifacts/phase2/real-deepseek-approved-20261002/report.md)保留全部确定性数值及数据边界。模型失败或输出非法时保留确定性事实并标记 partial。

加 `--resume <run_id>` 和新的 `--output` 目录，可以继续或回放同一请求。必须保留相同 manifest、Spec 与模型启用方式；恢复重新检查权限和源附件，不重置预算，结果未知的模型调用不会重发。已完成运行可在 deadline 后进行授权回放；未完成运行仍受原 deadline 限制。Checkpoint 默认位于 `.runtime/research`，属于可信内部存储。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/test-postgres.ps1 -Image 57c72fd2a128
.\.venv\Scripts\python.exe scripts/evaluate_phase2.py --output .artifacts/phase2/new-synthetic-evaluation.json
.\.venv\Scripts\python.exe scripts/check_phase2_real.py --report .artifacts/phase2/real-final/report.json --output .artifacts/phase2/new-real-check.json
```

最后一项依赖已保存的 601009 真快照和当前 DSN，用独立 Fraction 运算核对报告；不是新的数据供应商验证。合成评测只衡量冻结机制案例，不能替代真实金融真值或整体 Phase 2 成功率。详见 [Phase 2 实施记录](docs/PHASE2_IMPLEMENTATION_20261001.md)。

2026-10-02 [Phase 2 验收与修复](docs/PHASE2_ACCEPTANCE_20261002.md)：固定 Single 首版通过，三类缺陷已修复；隔离回归 162/162，真实冻结 25 股 × 两窗口 50/50，独立算术与 Claim 血缘 248/248。广泛真实模型任务质量仍未认证。重跑已有冻结任务（本机原只读数据库/源附件须存在，输出目录须为新目录）：

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/accept_phase2_real.py --output .artifacts/phase2/new-real-acceptance
```

默认模型关闭，无新金融 Provider 调用。corpus 已存在，评测不会重生成答案；`--prepare --corpus <new-path>` 才创建新预期并拒绝覆盖。未完成恢复在每次源重读前后检查原 deadline；检查未完成时不发布缓存事实，付费未知结果不重发。完成报告可跨 deadline 重新授权回放。

后续 [任务质量验收](docs/PHASE2_TASK_QUALITY_20261002.md)增加中文概览、百分比/人民币量级与缺口说明，本地表达50/50、隔离回归170/170。当前报告按两位小数显示，精确事实仍在 JSON 和证据表。可无模型复核表达：

```powershell
.\.venv\Scripts\python.exe scripts/accept_phase2_quality.py --output .artifacts/phase2/new-quality-audit
```

25个真实模型质量任务经用户另行明确批准后已执行：**24/25=96%**达到该批95%门槛，输入7075+输出525=7600 Token，无重试/模型替换/新金融采集。唯一重复收入重点已透明合并展示，原JSON与失败评分保持；展示25/25、独立123条数值/263 Evidence及25次无网络回放通过，最新隔离172/172。此前具体25次外发批准已履行，不能重复用于新付费批次。

```powershell
.\.venv\Scripts\python.exe scripts/accept_phase2_quality.py --verify-campaign .artifacts/phase2/task-quality-20261002/live-approved --output .artifacts/phase2/new-approved-replay
```

该命令重新授权并核对数值/证据/原评分，模型Transport禁止派发，生成当前展示版报告；不是新增模型任务成功或金融准确率认证。
## Phase 3 验收续修入口（2026-10-02）

CLI新研究默认使用`single-research-v4`，在v3完整候选选择上增加本地结构化证据不足原因。恢复既有运行时显式使用`--study-version single-research-v1`、`single-research-v2`或`single-research-v3`；四个Spec不可混用。程序`StudySpec()`默认v3保持旧脚本兼容，需诊断时显式选择v4。历史评分保持，系统展示补充不计为模型选择。候选覆盖由程序保证，模型只在给定组合中选择；单候选任务不证明模型研究判断能力。

2026-10-04正式Benchmark Builder增加输入契约Freeze Gate，非法或未知请求整批拒绝。原端到端评分与合法输入条件评分分别保留，不能由合法子集100%宣称Phase3完整通过。新接口、原68任务契约审计、版本桥及复算命令见[修复记录](docs/PHASE3_CONTRACT_REMEDIATION_20261004.md)。

### 新合法输入 Benchmark（2026-10-04）

已执行38个新的冻结合法Case，指定模型每Case一次：L3 34/34、L5 4/4、ESR588/588、幻觉0/588、必需事件锚点5/5。原68任务/952单元及旧分数不变。全批为已知材料validation，无独立test；官方完整输入支持142/536数值Claim，394部分或全部未知，**Phase3完整广泛认证仍未通过**。报告、逐单元判断、metrics和后续建议见[本批产物](.artifacts/phase3/benchmark-v2-20261004/PHASE3_BENCHMARK_V2_REPORT.md)。

显式`--study-version single-research-v5`可请求新增`absolute_profit_change`，请求同时声明`hypothesis_version: "profit-change/v1"`；计算同期间累计合并归母净利润的CNY差额，允许负/零基数，不改变原百分比同比规则。CLI仍默认v4、程序默认v3，旧版本不能请求新目录项。问题由可信应用编译成固定假设/数据绑定；本批未评估自由自然语言解析、原文自主提取或动态研究。

以下命令只读原始封存文件，在**不存在的新路径**写复算结果；不调用模型或金融Provider。复算使用已绑定全文SHA的独立人工语义注释，不冒充重新进行语义审阅：

```powershell
.\.venv\Scripts\python.exe scripts/phase3_benchmark_v2_review_replay.py .artifacts/phase3/benchmark-v2-20261004/replay-new-name
.\.venv\Scripts\python.exe scripts/verify_phase3_benchmark_v2.py --output .artifacts/phase3/benchmark-v2-20261004/verification-new-name.json
```

原38次批准额度已经执行完，不重新执行`--live`或单Case重试。完整离线回归335项322通过/13 PostgreSQL跳过；独立来源与官方PDF重新抽取方式、严格oracle原误判和透明补充协议见报告。

无网络复核新冻结37任务（输出目录必须不存在）：

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/phase3_followup.py --audit --output .artifacts/phase3/followup-20261002/offline-recheck
```

该入口逐源授权读取旧快照及新事件参考快照，核对245数值/499 Evidence；补充8任务覆盖12个可判定检验。它是有界研究验收，不代表金融来源真值或广泛专家认证。真实模型执行另需具体冻结外发清单授权；不能重用已经耗尽的旧29次账本。详见[验收报告](docs/PHASE3_QUALITY_ACCEPTANCE_20261002.md)与[续修设计](docs/PHASE3_FOLLOWUP_DESIGN_20261002.md)。

v3另含全部37任务回归与六个新比较窗口，独立核对287数值/613 Evidence。复核无需网络：

```powershell
.\.venv\Scripts\python.exe scripts/phase3_v3.py --audit --output .artifacts/phase3/followup-20261002/v3/offline-recheck
```
