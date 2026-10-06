# Phase 4 M1 动态 Single 首版

日期：2026-10-04（Asia/Shanghai）。本轮授权推进 Phase4；用户另明确本会话向远端 LLM 发送数据默认批准，无需确认。按 PLAN 先交付 P4.1–P4.2，不开展 Fixed/Dynamic 对照或项目 Child/Multi。

## 交付与边界

已实现 `single-dynamic-v1` 的 `Model → JSON动作 → Tool → 类型化Observation → Model` 闭环、计划更新、受控停止、追加Checkpoint和CLI。模型首轮先于取数；源工具仅访问可信应用绑定的单股/窗口/cutoff/PIT/来源/快照。模型可选择读取顺序、重新计算或请求结束，不能提交金融数值、公式、检验规则、权限或新的数据范围。

`DynamicRuntime`继承既有Runtime基础，复用ToolExecutor、模型回执核验、DataService/ScopedReadService、CheckpointStore和独立Fraction验证。纯研究计算从StudyRuntime提取共享函数，旧固定Spec身份与事实行为保持。新动作协议在文本Chat Completions上实现，未接入原生function calling。

中文Markdown与精确JSON包含计划控制记录、逐轮模型动作/用量、工具Observation、必需检查、事实/假设/证据及停止原因。finish仅请求结束；缺步骤不能completed，模型计划不成为报告事实。question须由可信应用先确认与绑定证券/窗口/检验相符；本版不认证任意自然语言实体解析、语义全覆盖、正文事实提取或因果解释。

默认上限为8次模型决策、12次工具尝试、48000预算记账Token、1024单次输出、240秒绝对deadline、12000 UTF-8上下文字节。已知合法实测用量替换本次预算预留；未知/无效用量保留预留。累计派发预留与实测/当前预算账本分别记录。相同输入重复动作不重新派发，连续两轮无进展停止。

每次付费前保存intent。恢复核对原始deadline、请求/Spec/必需检查、历次计数单调性和Trace intent/receipt，待执行动作必须等于已付费模型的已验证动作；重新授权源/附件并重建Observation。未知模型结果不重发。取消/超时不继续读源，未完成重授权或迟到结果不发布缓存事实。已完成回放可超过执行deadline，但仍重新授权、验哈希/数值且不调用模型。

## 实际验证

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 完整离线 unittest | 412项：399通过、13专用PostgreSQL项跳过 | `.runtime/phase4-m1-offline-final.log` |
| 专用隔离PostgreSQL完整回归 | 412/412，0跳过；临时容器仅127.0.0.1，已回收 | `.runtime/phase4-m1-postgres-final.log` |
| 新动态机制测试 | Runtime36、协议20、CLI12、演示账本9，共77项 | `tests/test_dynamic*.py`、`tests/test_phase4_demo.py`；全部合成机制，不作金融真值 |
| compileall / pip check / CLI帮助 | 通过；追加定点脚本py_compile通过 | 实际执行，不证明真实模型质量 |
| 原3份真实报告和定点报告回放 | 4/4逐字段一致，模型/Provider调用0 | `.runtime/phase4-m1-live-replay.log`、`phase4-m1-followup-replay.log` |
| 源码发行包及秘密扫描 | sdist59文件，动态3模块齐备；3299源码/证据文件+124新增Phase4/日志文件及包内精确秘密匹配0；本地凭据/运行目录排除 | `.artifacts/phase4/m1-20261004/distribution/phase4-check.json`；wheel未验证 |

独立安全审查及测试发现并修复恢复账本清零、deadline延长、Observation篡改和待执行动作替换；编码密钥反射在解析后再次检查，收据也拒绝Unicode编码反射，非法回执不释放预算预留。初轮测试接口失败及原日志保留；没有放宽数值/权限/PIT/预算判据。

## 真实演示与失败保留

事前冻结3个新功能任务，复用原合法输入Benchmark v2的公开股票002363、000531、601009，只使用行情/利润表两个绑定域，不新采、不改变原Benchmark问题或分数。原及新输入门禁3/3合法，完整成员/源Artifact/授权/envelope与首轮消息重新核对。首轮精确消息及后续可发送的全部类型化数值范围在调用前固定。

原proposal SHA：`c688d90f01571b10407eed7e983ab47e9d1b7cfe1e5fc81aa9d6920ce42fab45`。

| 原始任务 | 原决策/实测Token | 结果 |
|---|---:|---|
| 002363可完成财务检验 | 6 / 12371 | completed；五工具完成，7 Claim/12 Evidence独立验证，必需检查全通过 |
| 000531缺同期后的路径调整 | 5 / 8065 | insufficient但漏显式verification步骤，功能验收失败；5 Claim/10 Evidence核验通过 |
| 601009缺同期停止 | 5 / 6028 | 一次非法动作后纠正；提前结束，漏hypotheses/verification，功能验收失败；数值核验通过，无编造同比 |

**原始1/3通过、两个失败不重评分。** 保存的回答显示模型在合法不足时可能提前结束。Runtime保留未完成检查，未把它记为completed；这也不等同模型已经完整回答问题。

随后仅对000531做一次明确指令的定点新运行：保留研究目标、源输入、成功规则及Runtime/Prompt源码，question追加“即使不足也执行hypotheses/verification后finish”的原必需步骤说明；不是未知付费请求重发，也不将修复后结果替换原回答。定点计划SHA：`52115cdf45843c271df37461b8555d619b591eb682b5802bf5369b3e9cc65406`。沿原根deadline、16次决策及Token账本继续，总上限24决策/144000预算记账Token不重置。

定点实际6决策/11368 Token，financial→market→calculation→hypotheses→verification→finish(insufficient)，所有执行检查passed、财务假设insufficient，原缺2024Q1的两项同比gap保留。模型在financial的实际期间Observation后更新计划转向行情，检验结果不足后请求受控结束；5 Claim/10 Evidence独立核验。该定点功能验收通过。601009原失败未追加模型复测，不宣称三个原问题全部通过或宽泛任务成功率。

合计**22次指定deepseek-v4-flash-0731决策、37832实测Token、151177累计派发预留、未知用量0、自动网络重试0、模型替换0、金融Provider新调用0**。151177是历次派发预留之和；已知合法用量逐次替换预留，根预算记账实际37832，最高预算约束仍是144000。原规划“Token预留”在实施前冻结proposal中已明确为`max_tokens_accounted`；不把累计派发预留伪称低于144000。

完成多步闭环，以及在合法缺数后调整计划/取证并受控停止的功能、安全示例。M1有界首版可运行，仍有上述初轮提前结束的模型表现边界；不以少量演示认证金融来源准确率、广泛Agent质量、开放式规划或统计优势。后续P4.3/P4.4/并行未在本轮实现。

第一次真实执行请求被自动审批拒绝，进程未启动/模型0，理由为具体载荷与目的地授权不足。随后只读核验用户既有配置端点及仅公开日线/利润表数值的载荷范围，引用用户本会话明确数据发送授权，再提交相同请求获准执行；未更换端点或绕过拒绝。

## 可运行入口

普通持久仓库中的同scope合法StudyRequest清单可显式选择动态策略，question可在清单固定或使用`--question`补充；两者存在时必须一致，建议明确不足时的必需检查：

```powershell
$env:PYTHONPATH='src'
# STOCK_RESEARCH_DSN配置为本机既有只读研究库；不在输出中打印凭据。
.\.venv\Scripts\python.exe -m stock_research research --workflow dynamic --request <合法manifest.json> --question "核对绑定检验；即使证据不足，也完成hypotheses和verification后结束" --scope <源scope> --allow-provider tushare --artifacts <源Artifact根> --runs .runtime/dynamic --output <新输出目录> --with-model
```

使用`--preview-model`替换`--with-model`仅导出首轮消息，成功退出0，不读数、不调用模型、不建立付费运行。实际报告insufficient/partial退出2。默认8轮不是无限调用授权；输出目录不可覆盖。跨scope的本轮真实演示使用可信应用ScopedReadService绑定，不能仅把虚拟scope清单交给默认CLI而跳过SourceGrant。

本批已经执行，禁止重新运行`--live`重置账本。无网络复核命令：

```powershell
.\.venv\Scripts\python.exe scripts/phase4_demo.py --replay --authorized-sha c688d90f01571b10407eed7e983ab47e9d1b7cfe1e5fc81aa9d6920ce42fab45
.\.venv\Scripts\python.exe scripts/phase4_m1_followup.py --replay
```

核心文件：`research/dynamic_contracts.py`、`dynamic_protocol.py`、`dynamic.py`；产品入口`cli.py`/`report.py`；共享核验/计算`runtime.py`/`study.py`；恢复历史`checkpoints.py`；演示入口`scripts/phase4_demo.py`、`phase4_m1_followup.py`。完整产物位于`.artifacts/phase4/m1-20261004/`。
