# P4.5 Child任务推进修复与同案例复验

日期：2026-10-05（Asia/Shanghai）。**v3修复与P4.5限定真实完整并行闭环验收通过。** 本记录与原P4.5实施/验收报告分开；原任务 `p45-600500-independent-required-domains` 的真实功能 **0/1**、v2修复复验 **0/1** 完整保留，v3同案例修复复验 **1/1**。原六笔付费消息/回执/checkpoint/报告和所有历史分母不改。本轮复验不是新独立任务样本，不进入Phase 5、不调整12000字节阈值。

## 诊断：直接原因与待验证诱因

已核对AGENTS、CONSTRAINTS、PLAN、ARCHITECTURE、STATUS、P4.4 Context修复/P4.5记录、当前Runtime/Spec/协议、原完整模型输入/回执及checkpoint。已证实：Financial首轮读取成功，后两轮都返回相同financial读取动作；工具仍只执行一次，连续两次重复无进展后no_progress停止。第二轮已有completed_tools=[financial]、available source Observation及5条记录，第三轮已有duplicate_no_progress。Financial输入1572/2127/2175 UTF-8字节，任务最高5680/12000，未超限。

待验证诱因：available_tools列出授权读取能力但未单列当前可推进动作；required_checks只有名称而没有passed；coverage_not_verified/historical_release_not_verified可能与执行未完成混淆；重复反馈只有错误代码；system同时给出静态读取与结束示例。Market在相同缺口下读取后正常finish，故不能凭一次失败断言模型根因或缺口必然导致循环。

## 最小修复与兼容

新增显式Financial/Market Child v2及纯确定性child-progress/v1：required_checks的执行状态、read_completed/pending_checks/can_finish、独立source_quality、完整合法action JSON候选；重复读取反馈说明未派发工具并给同一合法下一步。读取前候选read，读取后按原非空available规则给completed或insufficient finish候选。source Observation及其缺口/引用不删除、不升级为verified。Child执行完成只完成受委派读取；Parent仍须join全部必需分支、calculation、hypotheses、verification及合法finish。

原DynamicRuntime、Registry/Executor、Evidence/Trace/Checkpoint、root-budget/v3、并行DAG、权限/PIT、绝对deadline与P4.4无损Builder不改。默认Child v1保留，旧wire不变；显式v2 Child identity进入Parent configuration恢复绑定。CLI新运行使用 `--parallel-domains --child-protocol-version v2`，旧checkpoint维持v1。没有自动把重复动作转成完成，没有提高决策/工具/Token/deadline/context cap。

## 离线机制与历史回放

合成Transport只证明机制契约，不能证明真实模型问题解决。原失败零模型回放：报告相同、functional_passed=false。六份P4.3/P4.4历史报告6/6相同，模型/Provider/Checkpoint追加0、原文件SHA和SQLite行数保持。证据 `.runtime/p45-child-repair-{original,legacy}-replay.log`、`p45-child-repair-legacy-replay.json`。原P4.5目录57文件另存哈希基线 `.runtime/p45-child-repair-original-baseline.json`。

v2完整回归已执行：纯离线720项706通过/14数据库跳过，隔离PostgreSQL720/720通过并回收容器；日志 `.runtime/p45-child-repair-{offline,postgres}.log`。新增40项合成机制包含双域推进、缺口保留、提前finish/持续重复拒绝、direct/serial/parallel、撤权/取消/deadline/late、unknown付费结果、已完成未join和已知duplicate恢复。最后恢复夹具初版未同步兄弟已接受回执，可正确触发取消partial；加accepted checkpoint同步后1/1及连续5/5通过，生产Runtime未改。

## 新冻结同案例真实复验

新harness `scripts/phase4_p45_child_repair_demo.py`，一次性目录 `.artifacts/phase4/p45-child-progress-20261005/attempt-1`。计划保留原question/request、security/window/cutoff/public PIT/snapshot/sources/scope/grants/envelope/oracle和模型端点，冻结新源码内容hash及v2 Child身份。Parent仍8决策/12工具/48000记账Token/240秒，每Child3/1/18000/120秒，根16/18/96000，独立campaign16/96000/480秒，context12000。新绝对deadline采用原继承规则，新run不恢复原预算。

冻结的成功条件：两个必要Child实际模型I/O重叠并合法结束，Parent完整calculation→hypotheses→verification→finish、全部必需检查passed及原确定性7 Fact/12 Evidence oracle/权限/PIT/血缘相符，并完成无网络确定性回放。原失败与修复复验分别统计，实际结果见后文；v2首次复验结束时P4.5仍未通过。

## v2首轮真实修复复验：失败保留

计划SHA `4b19677c7005e4c2e212ec5b931e2b78eca1199c2c08fbc3c1cc3864da3f90b2`。实际仍 **0/1，partial / parallel_required_branch_incomplete**，不是外部条件豁免。Parent1决策/1450 Token，Financial3/2343，Market3/2183；总根7决策/4工具/5976实测Token，unknown0、金融Provider0。组预留6决策/4工具/36000Token，组实际6/4/4526；Parent保留7决策/10工具/46550Token。wall10000ms、parallel section7948ms，实际Child模型I/O重叠true，最大5680/12000、overflow0。

两个Child均只执行一次读取，第二/三轮都选择finish，因此反复读取症状没有在这次复验中再现。新wire明确read_completed/can_finish=true、read检查passed，合法候选有reason且无refs，质量缺口原样；但四份真实finish回执均漏reason并误带refs:[]。严格parse_action连续invalid_action后触发no_progress；Parent未计算/假设/验证，Fact/Claim/Evidence均0。不能把“选了finish”算作修复成功。

七份wire/回执/Telemetry与冻结源、协议和账本逐笔一致。该失败零模型回放相同，证据 `.runtime/p45-child-repair-attempt-1-replay.log`。v2源码59文件与plan原SHA完全相符的快照另存 `frozen-source-attempt-1/`，不改attempt-1目录；v1五份Child paid wire逐字节一致及原0/1保持。

## 依据新回执的v3修复

v2输入、身份和回放不变；新增 `financial-child-v3` / `market-child-v3`。确定性当前动作contract列出必需/禁用键；FINISH须action/reason/plan，reason不可缺，tool/refs禁止。当前精确候选JSON放system末尾，要求逐键原样返回，不扩展plan。invalid_action反馈只给可信contract/合法候选，不反射模型文字。严格parser、no_progress、required_checks和所有安全/预算条件不改，不自动修补或执行动作。

新harness `phase4_p45_child_repair_v3_demo.py`冻结attempt-2，保留原及v2全部失败哈希、同输入/授权/预算/端点。新独立样本0，累计同案例修复尝试2；以下实际结果完整通过后才更新P4.5状态。

## v3最终验收分项

**P4.5限定功能验收通过，不自动进入Phase 5。** v3同案例复验1/1为真实配置模型闭环，合成夹具不计此分数。原独立任务0/1、v2修复复验0/1分别保留，没有覆盖失败、改变历史分母或统计成独立新任务。

| 分项 | 已执行结果与限界 |
|---|---|
| Implementation | 显式Child v3，默认v1与旧v2不变；仅Spec版本白名单、确定性消息协议与CLI入口修改，DynamicRuntime/Executor/根预算/并行DAG/权限不重写。精确候选与格式反馈仍须模型实际返回合法JSON，Runtime不替其补键或完成。 |
| Regression | 最终746项：离线732通过/14数据库跳过，隔离PostgreSQL746/746通过并清理容器；compileall/pip check/CLI帮助通过。新增66项机制/QA，原680项保留。首次v3 PG 745通过/1旧并发夹具竞态失败日志保留；仅同步Market保持running至组取消，原2失败/2unknown断言、测试总数不变，稳定性10/10及完整回归通过。 |
| Parallel correctness | 两Child实际模型请求区间重叠、两个running线程；Parent下一决策在合法两源join后。Market先返回、Financial后返回，canonical_merge_order始终financial→market。反向顺序/每域唯一/重复不启动/依赖gate由完整合成回归覆盖。 |
| Root-budget correctness | 现有v3账本原子两Child最大预留及Parent headroom保留；根16/18/96000不变。真实总9决策/7工具/16597Token，unknown0/未结算0；最后剩7/11/79403。unknown不释放/不重发、oversubscription拒绝、resume不重复预留由机制回归覆盖。 |
| Permission/PIT | 原question/request/scope/grants/envelope/oracle不变。实际12 Evidence的snapshot/cutoff/available_at/Provider/原Child工具调用血缘一致；模型输入双域隔离，每Child仅其工具和来源。源/cached读取及resume/回父仍重授权；跨域/撤权案例为合成安全证明。本次新金融Provider调用0，不冒称新Provider验证。 |
| Cancellation/late result | 原绝对deadline及Root→Parent→Child取消规则保留；实际Child deadline≤Parent≤Root。完整机制回归证明取消/timeout/late不导入及撤权不派发；真实本次cancelled/failed/late均0，没有付费真实故障试验。 |
| Recovery | unknown intent/已完成未join/已知duplicate后续轮等注入回归通过；真实三份结果零模型/Provider/Checkpoint追加回放同原报告。187份三阶段Artifact保持，v2 59份原源码SHA快照匹配；无重复Child/预留/Token/Evidence导入。 |
| Context telemetry | 9真实turn，wire UTF-8 bytes/SHA、角色/路由/turn及input/output/total Token逐笔对照；Telemetry未进入prompt。before最高19174，after最高10916/12000，overflow0；7 Fact/7 Claim/12 Evidence保留，Lazy Disclosure仅明细按阶段披露。不可可靠拆分的压缩贡献继续null，分桶残差仍按既有契约记录。 |
| Parallel telemetry | 真实group/branch起止、queue/execution/join等待、组原子预留/实际用量、完成/规范合并次序写入Trace，回放一致。sum_execution/section约1.69仅候选观测，不宣称Multi优于Single。 |
| Real end-to-end validation | Financial read→finish、Market read→finish；Parent parallel→calculation→hypotheses→verification→finish，六检查passed、7 Fact/7 Claim/12 Evidence、独立Fraction算术和冻结源绑定verified，functional_passed=true。 |
| Remaining gaps | 同案例两次修复复验，独立新样本0、非盲；不能推断广泛任务质量、金融真值/历史发布准确性、最优cap或Multi性能。旧覆盖率与历史发布缺口保留，六条报告gaps不删除。Phase 5/6未开展。 |

最终日志 `.runtime/p45-child-repair-v3-{offline,postgres}-final.log`，首次PG失败日志 `p45-child-repair-v3-postgres.log`，针对性48项机制/稳定性10项日志分别保留。最终审计 `.runtime/p45-child-repair-final-audit.json`：9/9真实Telemetry与回执一致、三报告无网络回放、187文件SHA保持。审计初稿误把模型view的evidence_ids当作canonical Fact字段，KeyError日志保留；按实际Fact.inputs核对所有Evidence链接后通过，未改生产报告或源码。

## v3冻结请求与实际逐轮记录

目录 `.artifacts/phase4/p45-child-progress-20261005/attempt-2/`。计划SHA：

`b9d53e7d281321244763a47686d8bf19769a9025e60f72be40944bd264051b7a`

源码版本以60文件逐文件SHA清单为准，清单规范digest：

`08ddfaa7813f1b3414c2b2408d8256717c6d47078a9efb86e8a2afdc48d3c1c9`

原证券600500/SSE，public PIT、cutoff `2026-10-04T00:00:00+08:00`；financial_income 2024-06-30至2025-06-30、market_daily 2026-09-16至2026-09-24，tushare原snapshot `2fd28cf7588ae798a8b4014b353d5dee14ab671eab31e8e6bde5b7db29bda22a`。question完整字节与原plan一致；完整sources/授权/oracle/required_checks/限额见plan。模型仅配置端点的deepseek-v4-flash-0731，绝对campaign deadline在外发前冻结为 `2026-10-05T14:43:20.542557+00:00`；Parent240秒、Child120秒不变。

| 实际外发 | 角色/轮/动作 | before→after UTF-8 bytes | input/output Token |
|---|---|---:|---:|
| 1 | Parent 1 parallel | 5482→5680 | 1410/31 |
| 2 | Market 1 market read | 2619→2619 | 640/23 |
| 3 | Financial 1 financial read | 2662→2662 | 640/23 |
| 4 | Market 2 finish completed | 3181→3181 | 822/21 |
| 5 | Financial 2 finish completed | 3382→3382 | 899/21 |
| 6 | Parent 2 calculation | 6818→6996 | 1939/40 |
| 7 | Parent 3 hypotheses | 12760→9288 | 2953/36 |
| 8 | Parent 4 verification | 18865→10916 | 3759/33 |
| 9 | Parent 5 finish completed | 19174→10152 | 3284/23 |

读取完成后两个真实finish均有reason=completed、无refs/tool且与当前候选完全一致；每Child仅一次工具、两模型决策。五Parent决策13508Token，Financial1583、Market1506；总16597。根完整分配累计85432，与实际模型派发累计预留66396区分，不混作实际账单。组预留6决策/4工具/36000Token，实际4/4/3089；Parent后续预算未被吃尽。

parallel_group_id `9e82c646d780459eb6907305a6645d49`；Financial queue92ms/execution6269ms/join335ms，Market211/5071/1414；组section6696ms、sum_execution11340ms，总wall20390ms。完成顺序market→financial，规范合并financial→market；取消/失败/late/unknown均0。九份dispatch/interval及其paid intent相符，实际模型网络调用交叠。

最终六项检查read:financial/read:market/calculation/hypotheses/verification/hypothesis:financial_deterioration均passed；描述性财务方向状态按原源oracle保留，不改因果强度或Provider准确性。before是相同system/control的完整typed基线，初始目录开销可出现负saved；不是与历史原wire直接比较。

可只读复现（真实live目录一次性，不重复付款）：

```powershell
$env:PYTHONPATH='src'
.venv/Scripts/python.exe scripts/phase4_p45_child_repair_v3_demo.py --replay --plan-sha256 b9d53e7d281321244763a47686d8bf19769a9025e60f72be40944bd264051b7a
```

原P4.5 **0/1**；v2同案例修复复验 **0/1**；v3同案例修复复验 **1/1**。旧P4.4/P4.3的所有统计不变，修复复验独立新任务样本 **0**。

交付复核：最终六份旧P4.3/P4.4报告再次6/6相同，模型/Provider/Checkpoint追加0、原文件SHA/SQLite行数保持，证据 `.runtime/p45-child-repair-final-legacy-replay.json`。源码、测试、文档、旧/新阶段Artifact与修复日志3972文件精确秘密匹配0，秘密值未输出；证据 `.runtime/p45-child-repair-secret-scan.json`。未外部发布或打包新发行物。最新源码冻结保持，无模型替换。
