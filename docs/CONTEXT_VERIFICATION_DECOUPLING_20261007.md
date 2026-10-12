# 验证前 Evidence 披露解耦：首个最小实施包

日期：2026-10-07（Asia/Shanghai）。状态：**本包实现及限定验收完成**。范围仅为 W1 验证入口与模型披露解耦；W2 通用分页、`context_read`、W3 验证器批处理及无限续跑均未实施。此请求覆盖此前仅调研边界，不复用历史 campaign 余额。

## 源码依据与实现

原 `dynamic_context.view_catalog` 在 `current_stage == verification` 时将全部 facts 加入 `claim_ids`，随后按每个 Claim 的 `evidence_ids` 自动展开闭包。`dynamic_protocol.dynamic_messages` 根据已完成 Observation 选择该阶段，再把闭包写入 system + user 两条消息。原 Parent v3 仅改变精确 metadata 编码，仍遵守这一完整披露约定。

`DynamicRuntime._verify_computed` 则从完整 `state.calculated` 和 `computed_sources` 对应的 pinned datasets 调用原 `verification.verify`。原 verifier 独立从源重建预期事实集合，校验数值、完整性、输入引用、单位/公式、可见时间、Provider/版本/Artifact/快照和假设；没有读取模型消息或要求 Evidence 曾被模型展示。因此本包不改 verifier、计算器或金融数据语义。

显式 `dynamic-parent-parallel-v4` 使用新的 `dynamic-context-disclosure-view/v1` 和 `verification_evidence_opt_in/v1` 披露契约。复用现有完整 catalog、行编码及 metadata 原语，但新视图不能独立回解为旧 verification 全量视图；这是披露语义变更，不能称为旧 codec 的等价编码优化。仅关闭 verification 阶段的自动 Evidence 闭包：原任务、绑定范围、required checks、完整事实与假设、缺口、冲突及反证引用、source/calculated/hypotheses/verified revision 和合法下一步保留。完整集合由绑定 catalog/request/run/scope 和内容 hash 的 manifest 引用及准确数量表示；manifest 明确 `execution_receipt: false`。已有 `disclose` 仍可显式读取完整原对象与闭包，没有新增分页动作。

工具始终读取完整已授权源与 computed。只有模型实际选择 `verification`，原确定性工具成功并提交真实 `tool_started/tool_finished` 与 v4 `verification_execution` 凭据后，必需 verification 检查才能 passed。凭据绑定源及计算/假设 revision、完整 computed/datasets 内容、实际模型决策/调用 ID 和 verifier 结果；自动重验证、manifest、计数、视图或 Child 完成均不能产生该凭据。v4 恢复还核对 calculation/hypotheses 的实际动作和 Observation，重建历史 paid wire；旧版进度和恢复分支保持。

v4 对标为当前 revision 的计算额外核对 `computed_sources == sorted(outputs)`，防止恢复篡改把一个算术有效的子集送给原 verifier，从而遗漏已执行来源的事实；合法陈旧计算仍按原来源集合重验证，必需检查继续 pending，不能完成当前 verification。每次外发、所选动作、工具提交、报告交付和恢复重建前后重查来源与授权，末尾源复核不递归调用 verifier。

每轮仍先走原 source/Artifact/权限/PIT/快照重验证，然后编视图、按原 system + user UTF-8 总字节口径检查 12000 上限、预留原 Token 和根预算、持久化 paid intent，最后外发。v4 仅将明确大小溢出记为 `dynamic_context_budget_exceeded`；schema/绑定错误不能被伪装为字节问题。仍不能装入的事实、目录、依赖或控制信息准确有界停止，不裁剪。新 Telemetry 分开记录展示/权威集合数量、manifest 开销和 Evidence 表披露差；字节不能代替实测 Token。

## 版本选择与兼容

CLI 在既有动态 Parent 入口显式选择：`--parallel-domains --parallel-version dynamic-parent-parallel-v4 --child-protocol-version v3`。同一新 Parent 可以按模型原动作选择 direct、serial 或已有两 Child parallel；入口不代表扩大并行启用范围。库使用 `ParallelParentSpec(version="dynamic-parent-parallel-v4")` 并显式配置 Financial/Market Child v3。所有默认仍是历史版本。

新 Spec 和 context policy 绑定新身份，恢复必须用原版本、原请求/权限/快照/deadline；不升级旧 run，不重置预算。完整 state/catalog/最终 Fact/Claim/Evidence、缺口、血缘及旧 paid wire/Checkpoint/冻结文件/失败/分母保持。finish/no_progress、原局部/根额度、原子根预留、Parent headroom、deadline/cancel、未知付费停止均保持。

## 验收边界

先执行 `PYTHONPATH=src python -m unittest discover -s tests -v`，合成扩量只证明机制。数据库只可使用专用隔离实例；缺少可用实例时必须列出跳过。旧材料只读回放禁止新增模型、Provider 和 Checkpoint 追加。

真实外发前冻结 `.artifacts/context-verification/first-minimal-20261007` 中独立计划：最多两既有合法 case，各 Parent v3 baseline/v4 candidate 一次，最多四运行，Child 均显式 v3；原请求/源/授权/oracle/评分/局部和根限制不变。新 campaign 64 父子决策、384000 记账 Token、1800 秒，不借旧余额；未知付费停止、不重发，失败留存，无自动扩额或下一工作包。

只读筛查发现旧串行 prior-remediation 002363 超限失败，当前 Phase5/6 compact Parent 记录尚未发现 verification 超限。若最终预检未找到合法当前 v3 超限输入，使用已有合法样例验收兼容和质量，并标注“真实超限恢复尚未验证”；不改题或填充假 Evidence。

## 实际结果

最终完整回归 `.runtime/context-verification-offline-complete.log`：**861项，847通过、14数据库跳过、0失败/错误**；新增27项核心/安全机制与6项harness机制，均不作金融真值或真实模型质量。专用 Docker PostgreSQL daemon 不可用，本轮未运行 PostgreSQL 集成，也未使用其他 DSN；SQLite 持久化/恢复实际执行。compileall、pip check、CLI帮助、git diff --check通过。前一860项修复回归846通过/14跳过另留 `.runtime/context-verification-offline-verified.log`；最后新增完整源集合负控1/1通过后重新跑了上述861项，不以旧结果代替最终版本。

旧19报告回放与原Phase6四报告回放 **23/23完全一致**，模型/Provider/Checkpoint追加0；5371份Phase2–6历史文件SHA保持，原P45失败、Phase5原8/9和各复验分母均未改。证据 `.runtime/context-verification-historical-replay.{json,log}` 与 `context-verification-phase6-replay.log`。旧Phase6结果独立保存，不计入本包真实分母。

真实计划SHA `de569712135701e55959c46dabd834ac8e7129c996d40e30b12f9a416e792391`，冻结66份实施代码SHA、最终代码/测试/log绑定、两既有case的原请求/源/grants/oracle/评分及四个新run。新campaign实际 **4/4通过，4/4零模型/Provider/Checkpoint追加回放一致**；两603207均completed、7 Fact/12 Evidence，两688184均合法insufficient/evidence_insufficient、6 Fact/12 Evidence，非正基数缺口保持。共26 Fact/48 Evidence，20项必需执行检查全部passed，四次verification均模型实际选择并成功执行；合法假设不足另列，没有提前结束冒充完成。两Child实际I/O重叠4/4、父子PIT/权限/快照/血缘与原根/局部预算核对通过；新v4凭据仅实际工具产生。

| 案例 | 版本 | 状态 | 父子实测暨记账 Token | Runtime ms | Parent全部派发字节 |
|---|---|---|---:|---:|---:|
|603207|v3 baseline|completed|16450|18719|44495|
|603207|v4 candidate|completed|18370|21703|47764|
|688184|v4 candidate|合法insufficient|18085|21531|47215|
|688184|v3 baseline|合法insufficient|16242|19219|44170|

**实际总成本未下降。** baseline合计32692 Token，candidate36455，多3763（11.51%）；Runtime合计37938→43234ms，多5296（13.96%）。Parent全部派发88665→94979 bytes，多6314；manifest和新控制信息有开销，且模型计划长度不同。模型I/O区间去重合计18585→19557ms，transport累计20986→21938ms；verification工具span288→650ms，包含授权/读取等，并非纯Fraction CPU。来源读取/授权、Checkpoint和服务端排队没有独立分解，未知而非0；不重复相加嵌套span，也不宣称P95或统计优势。无配置端点单价或账单，金额及额外货币费用未知，只报告实测 Token。

实际candidate验证前paid状态精确回编同状态v3（仅本地测量、未派发）：603207 **10709→10358 bytes**，12 Evidence正文→0；688184 **10578→10255**，11→0，合计净省674。它与上面的实际独立baseline运行字节不同，因为相同状态保持candidate的原plan/control；不能将反事实字节换算成反事实Token/延迟。完整授权catalog/程序核验仍各有12 Evidence，没有事实或证据删除。全部36份实际输入按system+user原口径计量，最高 **11144/12000 bytes**。

总计36父子决策/28工具/69147已知暨记账Token（prompt67989+completion1158），unknown0、未结算Child0、金融Provider网络0。累计派发预留277100、根累计含组预留353244分别列出，不是实付Token；四运行槽位全部使用，未扩额、不借旧额度、不进入下一包。新Trace Dataset SHA `8085fd04c2fc435b65894b46052868435ec3a713bebd66df498193842e9d5752`。新只读audit核对12run SQLite哈希链、36份paid状态/原消息/回执和四次实际verification；证据 `.runtime/context-verification-real-{replay,audit}.json`、`context-verification-local-metrics.json`。决定为 `limited_explicit_verification_disclosure_accepted`，仅接受显式W1行为，默认保持。

真实失败0、修复追加运行0、计划跳过0；开发与离线失败如下完整保留。**真实超限恢复尚未验证**，这两已知非盲case是兼容/质量验收，独立新任务0，不能宣称分页或金融Provider真值验收。W2/general pagination/context_read、无限续跑、验证器批处理和更大不可压缩工作集均未验证/未实施；完成本包后停止。

纯本地同状态定量核对 `.runtime/context-verification-synthetic-size.json`：80 行合法 pinned 合成行情 + 原合成财务源，7 Fact/85 Evidence，原 Parent v3 system+user 19091 bytes，新 v4 10854，少8237；完整原 verifier 检查7事实/85证据/1假设。该测量无模型/Provider网络/Checkpoint追加，控制为相同空 plan/decision1；端到端实际工具与 finish 另由机制测试验证，不能当作真实金融超限恢复。300 行合成案例的其他必需输入仍超限，准确 partial/context budget 停止，完整源记录保留。

只读真实预检 `.runtime/context-verification-real-preflight-20261007.json` 核对5371份 Phase2–6历史文件，模型/Provider/Checkpoint追加0：两实际 v3 验证前视图分别10617/10521 bytes，均未超12000；同状态候选测量10266/10198，Evidence正文12→0、11→0。仅旧002363串行 prior-remediation 超限，不是当前 v3 验证前超限案例；真实超限恢复尚未验证。上述字节为本地测量，不代表真实 Token 或延迟收益。

中间失败保留：`.runtime/context-verification-root-targeted.log` 的20项首次定向有1失败/3错误；其中撤权时序暴露真实新安全缺口，另外为测试契约/夹具问题。`.runtime/context-verification-offline-first.log` 为850项835通过/1合成规模停止断言失败/14数据库跳过；100行规模在其他必需视图仍会超限，改用合法80行证明本包成功路径，并另保留300行准确停止测试，未改变12000或完成规则。`.runtime/context-verification-offline-final.log` 为860项845通过/1最终重验证撤权失败/14跳过；随后复核末尾源权限（不递归运行verifier）修复，四项撤权负控实际4/4通过，日志 `.runtime/context-verification-revocation-repair.log`。修复后完整回归另写新文件，不覆盖这些失败。

Harness初次6项中的2错误（把合法hypothesis insufficient当失败、Windows只读SQLite句柄未关闭）记录在 `.runtime/context-verification-harness-initial-failure-20261007.json`，日志v2保留；仅修QA判据与显式关闭句柄，实际必需检查/原评分保持。随后harness6/6与核心24/24定向通过；根进程合并30/30通过记录在 `.runtime/context-verification-targeted-final.log`，后续两个安全负控由最终全套另验。均不计真实模型或金融真值。

交付完整性 `.runtime/context-verification-delivery-integrity.json`：609份源码/文档/本包证据/日志精确密钥匹配0、禁入秘密文件0，66实施SHA与最终测试gate匹配，5371历史及全部live文件保持；检查无模型/Provider/Checkpoint追加。本轮以plan的实施SHA冻结，不声称事前生成源码副本。最终统计/文件探测曾分别因猜测`root_usage.tools`和不存在的`source-manifest.json`出现两个只读QA错误，修正后复算/完整性通过；记录 `.runtime/context-verification-postrun-qa-diagnostics.json`，没有核心或冻结材料改动。交付索引 `.artifacts/context-verification/first-minimal-20261007/acceptance.json` 绑定plan、gate、probe、Trace、replay、audit和完整性。
