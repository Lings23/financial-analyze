# Parent 上下文去重与按阶段披露设计

**2026-10-07 执行追记：用户明确授权执行 v5 后，本设计 W1b 已完成版本化实现和限定验收，真实4/4及零追加回放4/4，实测整任务Token少11.40%、Runtime增加，结果见[实施记录](CONTEXT_DISCLOSURE_V5_20261007.md)。以下“仅设计/未实施”为原设计轮次历史，不把设计字节结果当新实现的实际Token/延迟收益；W2/v6/W3 不启动。**

日期：2026-10-07（Asia/Shanghai）。状态：**设计完成，未实施新协议、未追加真实模型请求**。本轮对应用户“设计方案，去重、减少反复发送与提前发送验证信息”。以已完成的[Parent v4 验证前披露解耦](CONTEXT_VERIFICATION_DECOUPLING_20261007.md)为基线；保留 v4 四运行、失败、代码 SHA、paid wire、Checkpoint 和全部历史结果，不复用其剩余预算。

本文件是[持续上下文整合方案](CONTEXT_CONTINUATION_DESIGN_20261006.md)的 W1b 技术细节：v4 已完成，v5 先修复披露冗余，W2 再用拟议 v6/window/v1 增加分页，W3 仅由程序验证瓶颈触发。两份设计不授权自动进入实施或追加真实运行。

## 1. 结论与实测依据

采用“**完整审计留在程序侧，模型接收完整当前决策状态；验证目标按就绪状态披露；当前消息内精确去重**”。拟议显式 `dynamic-parent-parallel-v5` / `dynamic-context-disclosure-view/v2`，披露契约 `phase_gated_verification_brief/v1`；旧 v1–v4 与默认不变，Child 仍显式 v3。仅修正 v4 的披露冗余，不实施 W2 分页/context_read、验证器批处理、LLM 摘要、跨任务记忆或新 Runtime/Router/Provider/Dataset/领域 Agent。

实际源码原因：`view_verification_catalog` 无条件调用 `_verification_manifest`，再在 `encode_metadata_view` 之后追加整份 manifest；已有 codec 的 `_slots` 未涵盖 manifest。导致每份 Parent 输入新增约1072–1260 bytes，空集合哈希、catalog/binding、多个相同 revision 都重复发送。v4每例仍只有5个Parent决策，增加来自每轮内容；较长模型plan也进入下一轮。

| 两案例合计 | v3 输入Token | v4 输入Token | 差额 |
|---|---:|---:|---:|
|取源前|3163|4012|+849|
|calculation前|4245|5129|+884|
|hypotheses前|5713|6718|+1005|
|verification前|6930|6636|−294|
|finish前|6148|7277|+1129|

Child输入保持一致；总输入多3573、输出多190，共多3763 Token。上述为原端点真实回执，不能由字节比例反推。目标是消除可避免的提示词开销，同时保留原完整验证与全部安全核对。

## 2. 分开审计与模型披露

| 信息 | 程序/Checkpoint | 模型当前输入 |
|---|---|---|
|原任务、证券/窗口、带时区cutoff、PIT、snapshot/provider绑定、全部required checks|完整保留并核对|每轮完整保留，固定字段可用可逆metadata编码|
|当前 source/calculated/hypotheses/verified revision|完整64位digest，按权威状态生成|每轮精确表示；同一digest只在当前表出现一次|
|完整计算结果、datasets、Fact/Claim/Evidence、假设、缺口/反证、血缘|完整保留，原全量verifier读取|现有事实/假设/缺口/反证入口保持；不自动展开verification Evidence正文|
|完整验证audit manifest、request/content/collection哈希及scope/run绑定|按原完整对象生成、持久化与恢复核对|不发送整份；就绪时仅发送集合入口和准确数量|
|实际verification执行凭据|原v4成功工具凭据、模型动作、start/end、完整输入/结果绑定保持|验证后沿用权威执行进度与现有verification Observation；无需再发完整待验证manifest|

每次模型调用当前只有system + user，两条消息不携带上一轮上下文。因此不采用“第一轮发任务，之后只发差量”的办法；原任务、安全范围和当前状态始终常驻。去重发生在当前消息内部以及阶段之间的非必要信息披露策略，不能把省略信息解释为服务端或模型记得上一轮。

完整audit不是模型必须阅读的材料，也不是付费验证动作。模型仍实际选择 `tool=verification, refs=["hypotheses"]`，Runtime仍对完整已授权 computed/datasets调用原verifier，成功才提交原执行凭据。省略审计哈希不减少授权/PIT/快照/血缘检查。

## 3. 用权威执行状态控制披露

现有 `context_next_stage` 仅看Observation名称，可能与陈旧revision下的执行状态不一致。v5必须先从 `_check_results` 和实际执行凭据判断状态，再决定是否附加 `verification_brief`；不能只根据出现了hypotheses Observation来认定可验证。

`verification_ready` 的条件同时为：全部必需read已实际完成，calculation/hypotheses检查passed，source/calculated/hypotheses revision一致且非空，computed_sources覆盖全部当前outputs，verification检查仍not_completed，既有parallel DAG也允许执行。hypothesis结论insufficient并不免除verification。

| 当前工作阶段 | 每轮必要内容 | 验证专属内容 |
|---|---|---|
|取源前/取源中|完整任务/范围/checks、实际read进度、来源质量缺口、当前revision与合法动作|不发空集合验证manifest|
|calculation前|已完成源及原目录、完整性状态、精确calculation refs|不发验证集合/内容哈希|
|hypotheses前|原完整事实、假设所需引用、缺口/反证、合法hypotheses动作|不发待验证manifest|
|verification就绪且未执行成功|上述必要状态、完整声明假设状态和实际合法verification动作|附一份轻量verification_brief，引用完整集合并给准确数量；不自动展开Evidence|
|verification成功后的finish|全部checks/真实执行进度、原verification结果、假设状态、所有未解决缺口|不重复发送待验证manifest|

就绪时模型若选择合法disclose、提前finish或发生格式错误，下一轮仍要重建当前必要brief；不能强行“只发送一次”而依赖跨轮记忆。源或计算状态变化时，旧就绪状态失效，沿用原重算/必需检查规则，不通过视图编译补做业务工具。

## 4. 当前消息内精确去重

新增严格 `state_versions` 槽位：完整digest表按字典序去重，revision槽位用无歧义 `{"h": index}` 引用；null保留原未执行语义。财务值、计数、Claim/Evidence行ID继续保持原直接可读字段，不把任意整数都当hash索引。

```json
{
  "state_versions": {
    "digests": ["FULL_64_HEX_SOURCE_DIGEST"],
    "refs": {
      "source": {"h": 0},
      "calculated": {"h": 0},
      "hypotheses": {"h": 0},
      "verified": null
    }
  }
}
```

这是schema示意，非真实hash或可派发请求。初始source为现有 `_current({outputs:{}})` 的精确空状态digest，并由pending reads表明尚未执行读取，不将hash存在当作read完成。每轮自己带完整表；索引0仅指本消息，不能跨轮、跨run或跨scope复用。解码须检查hex格式、排序/唯一、整数类型（bool不是index）、越界/悬空、规范重编码及与权威revision完全一致。

`catalog_ref`保持一份完整literal 64位值，供现有disclose动作原样回传，避免新句柄resolver或动作变更。`binding_ref`保留现有单份字段；brief继承当前context的catalog/binding，不再复制这些字段。request_ref、complete_state_ref、manifest_ref与四个collection内容digest留在audit。第一版不截短哈希、不引入全局短ID、不把引用当权限。

## 5. 就绪时的轻量集合入口

```json
{
  "verification_brief": {
    "computed_ref": "O:hypotheses",
    "source_refs": ["O:financial", "O:market"],
    "counts": {
      "facts": 7,
      "evidence": 12,
      "hypotheses": 1,
      "source_datasets": 2,
      "source_records": 8
    }
  }
}
```

以上数量来自既有603207记录，仅作字段示例。computed_ref绑定当前catalog的完整typed hypotheses对象，其中facts/evidence/hypotheses集合与完整计算一致；source_refs覆盖全部computed_sources对应的source Observations，其source_result_ref绑定完整受控datasets。所有refs必须确实在本run当前catalog中，数量独立从完整状态复算，不能由模型提交。它们是完整集合入口，不是逐项验证覆盖证明或实际执行回执。原verification工具refs仍是 `["hypotheses"]`，没有新的工具参数或读取动作。

完整raw computed/datasets的内容哈希与输入范围继续在服务端audit/原v4执行凭据中绑定；typed catalog引用不宣称能够独立回解完整raw财务附件。继承现有disclose时仍按原授权和完整对象闭包读取，超12000准确停止，不添加分页或裁剪事实。

## 6. 减少计划与指令重复

保持每个动作必须有原 `plan` 字段、1–5项、每项240 UTF-8 bytes及完整plans ledger。新system建议“一条简短当前动作计划；必要时可多项”，执行状态/checks已有权威信息，避免每次复述任务、hash、全部已完成步骤。模型选择较长合法plan时仍逐字保存和发送，不做LLM摘要或Runtime裁剪。

不新增 `keep_plan`、plan引用动作或跨轮delta；它们会改变parser、paid身份和恢复规则，超出本最小包。新system保留全部安全/动作规则，以简短一句解释hash表和brief，不在取源阶段重复整段审计manifest说明。system与user一并精确计字节。

## 7. 代码落点、恢复与兼容

| 区域 | 拟议最小变更 |
|---|---|
|dynamic_contracts / CLI|增加显式Parent v5，默认/Child版本/全部限额不变|
|dynamic_context|分开 `build_verification_audit` 与纯model projection；保留原catalog和完整v4对象，brief按权威就绪状态生成|
|dynamic_context_metadata|独立schema v2的revision槽位codec；复用纯编码原语，旧严格codec完全保留|
|dynamic_protocol|v5选择新builder和精简system，业务action/schema与原plan规则保持|
|dynamic.py|v5继承全部v4完整源集合、真实工具凭据、读前后授权/报告/恢复检查；增加policy绑定、阶段选择与审计重建，不回退到旧弱执行检查分支|
|Checkpoint / Trace / Telemetry|复用物理追加存储，v5 policy及paid metadata独立标识；记录实际message SHA、阶段门禁、brief/hash表字节及完整audit引用，旧schema/wire不升级|

每次派发依次执行原权限/PIT/snapshot/lineage复核、权威阶段判断、视图编译、system+user精确12000检查、原局部/根预留、paid intent持久化和外发。新门禁不得产生verification成功凭据或重置no_progress。不可压缩输入仍超限时准确有界停止。

完整audit在验证目标真实生成后保存到paid metadata/Checkpoint；取源阶段不为不存在的验证集合生成空manifest。恢复从原完整catalog/state重建模型投影和所存audit，核对scope/run/request、输入revision、真实工具回执、原消息SHA与实际字节，再走原完成报告重验证；不以引用/计数代替verify，不减授权次数。第一版不新增跨任务cache；同输入audit的程序复用若后续考虑，仍需每次重授权/复核，不能以hash命中免检。

## 8. 设计期只读字节探测与验收门槛

本轮在重新核对原SourceGrant/PIT/oracle及冻结SHA后，对v4两case的10份实际Parent paid输入做**纯JSON设计样例**：移出完整manifest、增加每消息revision表、仅权威verification就绪时附brief。任务、plan、原facts/hypotheses及其他视图保持；system暂保持原v4以隔离正文变化。

| 阶段 | 603207 v4→设计样例 bytes | 688184 v4→设计样例 bytes |
|---|---:|---:|
|取源前|7217→6298|7217→6298|
|calculation前|8562→7642|8581→7661|
|hypotheses前|10483→9503|10295→9315|
|verification前|10358→9503|10255→9400|
|finish前|11144→10046|10867→9769|

合计 **94979→85435，少9544 bytes（约10.05%）**，每份少855–1098；只有两份真正就绪输入带brief。记录 `.runtime/context-dedup-design-byte-probe-20261007.json`。这是未实现schema的正文可行性测量，保留旧system的样例**不是合法可外发v5 wire**，未验证codec/parser/恢复、实际Token/延迟/金融质量；没有新的模型、Provider或Checkpoint追加，原代码/测试/冻结live材料保持。

后续实施先满足：完整事实/证据/缺口/反证不变；原verifier完整输入与实际verification执行保持；早finish/重复/合法不足规则不变；跨scope/run、陈旧revision、hash表篡改/乱序/越界、源遗漏、撤权/快照变更和恢复篡改均拒绝；同一v5 direct/serial/parallel兼容；system+user每份≤12000；v1–v4历史wire/身份/零追加回放保持。

性能门槛先看同状态每阶段字节均不增加、总体减少；然后看**整任务父子实测输入/输出/总Token**而非verification单轮或字节推算。新版全部system、hash表、brief、错误反馈、plan及可能增加的决策都计入。真实Token改善、延迟与金额必须另有实现后离线通过和新冻结有界计划，原四槽和剩余Token不可复用；本设计不发起该campaign，不声称10.05% Token收益或已完成W2。
