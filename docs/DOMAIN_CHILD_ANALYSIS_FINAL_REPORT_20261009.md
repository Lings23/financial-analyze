# 领域分析 Child 最终交付与实用价值评估（2026-10-09）

工程功能完成；两个既有案例的 Financial/Market 分析 Child 已完成真实业务闭环，A/B/C 最终结果与原完整 oracle 等价。没有证明有意义的自主检查选择或实用收益，继续保留显式实验模式，默认不改。

本报告结合原冻结窗口和用户另行明确授权的单案例补验。原窗口的正式评分、失败分母和全部付费证据不改：初始4/6通过，窗口内复验1/2通过，独立补验1/1通过；共9次实际运行6次通过，最终2案例×3路线覆盖6/6。不能将原窗口评分改写成6/6，也不能删除失败来计算效率。

## 工程与验证职责

- Financial Child 实际读取授权财务快照，运行 financial_snapshot/income_yoy，完成领域检查及独立 Fraction 局部验证；Market Child 实际读取冻结行情，运行价格/回撤及因子相关检查，完成独立局部验证。未绑定因子时保留合法缺口，没有合成复权数值。
- Child返回完整领域Fact、Evidence、缺口、反证、假设、源版本、输入Revision与真实调用回执。Runtime生成并重建可信执行凭据，模型自报verified不能取得可信消费资格。
- 两个C案例每例实际业务计算Tool2次、域算子4项、Child局部Fraction2次；Parent Join2次，重复生产0、Fraction重算0，保留来源及真实回执核验各2次。
- Parent仅组合及检验跨域/未委派结果，两个C案例均`produced_domains=[]`。每个最终接受的A/B/C报告都实际选择并成功执行原完整独立verification一次，然后由原finish规则确定completed或合法insufficient。
- 原完整性独立审计保留：每个成功报告19次，另计耗时，不与实际Final或Child局部审核混淆。迟到、取消、未知、权限/PIT、Revision变化、篡改、遗漏、原子预留及恢复契约保持。

没有新Runtime、Router、Provider、Dataset或第三领域。仍仅Financial/Market、depth=1、每域至多一个Child。Root16决策/18工具/96000记账Token、12000 UTF-8字节、no_progress_limit=2及所有旧身份/默认保持。两例C实际各13决策、11工具；每Child4决策、3工具，Parent5决策。AgentTool包装调用已计入Root。

## 真实结果与范围

| 案例 | A直接Tool | B确定性领域Tool | C分析Child | 完整结果 |
| --- | --- | --- | --- | --- |
| 603207正常同比 | completed | completed（首次复验） | completed | 7 Fact / 12 Evidence / 1假设 |
| 688184非正利润基数 | insufficient | insufficient（独立v4补验） | insufficient | 6 Fact / 12 Evidence / 1假设 |

每组完整canonical Fact/Evidence/缺口/反证/假设与原oracle完全一致，六个最终结果均通过完整来源绑定、权限拒绝及必需执行检查。非正利润基数未强算百分比、未用金额变化替代；不足是数据前提不足，执行检查已经完成。补验模型finish文本为completed，Runtime依据已验证结果仍正确报告insufficient，未让模型声明覆盖真实状态。

真实源只来自既有合法financial_income/market_daily快照；未新增金融采集。因子数值、交易日历、现金流、金额profile及其他任务选择没有合法输入覆盖，继续记为真实未验证。通过因子缺口处理不等于通过有因子数值计算。两个非盲案例不证明统计优势、Provider准确率或广泛收益。

## 失败、修复和授权边界

新主窗口19:32:18.454759冻结、20:12:18.454759截止（+08:00），保持2案例/6初始＋最多2有据复验/128决策/768000记账Token/2400秒。实际52请求、119491 Token，全部回执用量已知。两个初始B都连续选择非法parallel，按原2次无进展规则停止；v3说明移除B不适用的parallel语法后正常B通过，合法不足B又连续重选已完成Market Tool，原检查再次拒绝，复验槽2/2用完即停止付费。

用户随后明确授权仅688184/B一次独立复验，另冻结8决策/48000 Token/240秒/一次运行无重试。v4明确legal_next_actions是当前动作权威，control.plan是历史，不能重复领域Tool或跳过组合/假设/最终验证。19:53:09.690971冻结、19:57:09.690971截止；实际6决策、20074 Token，完整闭环通过。原8次费用全部保留，新补验独立记录，旧期限和余额不重用。

实际Parent输入修订为v2（A/C及初始B）、v3（窗口内B复验）、v4（独立补验）；除控制说明外，输入数值、源、授权、oracle、必需输出、Spec局部能力和评分方法不变。保留这些修订差异为实验限制，不能声称只有Agent数量一个变量改变。最高实际模型输入11849字节。

上一轮16:27:09–17:07:09窗口外发11次全部已知17900 Token，正常A通过，B非法动作失败，C入口错误地把另一Child在途预留当terminal unknown，Market在HTTP前被拒绝。修复区分在途与终止性未知，原Root4095预留和partial保留。此前拟执行的修复被自动审批usage limit拦下，行动未执行；没有把此事记作DeepSeek故障或付费请求。用户后续另授权新窗口，本轮已实际外发。

网络实例为同端点同模型direct-ipv4-prehttp/v2：最多两个合法DNS IPv4候选、每个TCP8秒，仅在TLS/HTTP前切换；一个paid意图只发一次HTTP，TLS/HTTP失败不重发，Host/SNI/默认CA及原解析、响应上限不变。系统/环境代理和默认配置不改。

## 资源与实用价值

主指标仍是事前冻结的全Parent＋全部Child已知Token，按同题路线求和并包含失败/复验/另授权补验。未更换为Parent Token或择优wall指标。

| 路线 | Parent Token | Child Token | 合计Token（含失败） | 完整测量wall合计 | Runtime wall合计 | 模型决策 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A直接 | 24841 | 0 | 24841 | 30.610秒 | 29.985秒 | 12 |
| B确定性领域Tool | 55656 | 0 | 55656 | 62.171秒 | 60.906秒 | 20 |
| C分析Child | 36488 | 22580 | 59068 | 68.063秒 | 67.156秒 | 26 |

C总Token比有效B（含全部失败/修正）高6.13%，比更强的有效A高137.78%；未达到对B和更强A/B减少10%的候选门槛。即使Parent Token下降也不足以证明收益，本批Parent Token本身也高于A。wall没有显示实用加速；小样本、请求顺序、缓存和服务时间均有影响，不报告P95或统计因果优势。

| C阶段实测 | 603207 | 688184 |
| --- | ---: | ---: |
| Child业务计算Tool / 算子 | 2 / 4 | 2 / 4 |
| Child局部Fraction / review耗时 | 2 / 31ms | 2 / 15ms |
| Join / Source与Receipt核对 | 2 / 各2 | 2 / 各2 |
| Join重复生产 / Fraction / 耗时 | 0 / 0 / 94ms | 0 / 0 / 94ms |
| Parent生产相同领域结果 | 0 | 0 |
| 实际完整Final | 1 | 1 |
| 保留的完整性审计 / 耗时 | 19 / 78ms | 19 / 123ms |
| Runtime / 完整测量wall | 31.578 / 32.016秒 | 35.578 / 36.047秒 |

部分纯算子/Final耗时四舍五入为0ms，这是时钟分辨率下的测量值，不表示无执行或无开销。完整IO、Tool、包装、Join与局部/完整验证spans均存于JSON；嵌套span不另加到wall。纯协调、授权与Checkpoint持久化未能独立拆分，保留null。缺少优化前的同任务真实CPU比较，不宣称减少Join Fraction带来了实测性能提升。

当前实际Child路径是read→calculation（完整必需算子）→review→finish。Trace证明合法动作、职责下放、并行及不足反馈，没有有意义的自主检查选择/调整；不能据此宣称Agent增量价值。未自动启用、改默认或进入其他阶段。

本领域Child实施goal的所有批次加独立探针：79次业务API请求＋1次14 Token探针，已知167555 Token；三个旧API未知预留22338，API保守记账189893。再含旧局部Root4095预留，总保守记账193988、保留预留26433。这个口径不包含仓库此前其他Phase的费用。实际本goal累计总Token/货币费用仍未知；旧请求不重发、不释放，不以新成功结算旧未知。

## 测试、回放与使用入口

完整项目回归已执行1159项：1143通过、16数据库项跳过、0失败/错误；16项又在专用隔离Postgres实例全部通过。当前src/scripts/tests哈希一致，未声称重跑完整测试。新增传输12项、独立窗口入口11项、B v3输入2项、v4候选2项、单案例入口2项离线验证通过；开发期fixture错误及日志全部保留，没有删除测试或放宽断言。

旧39份历史报告零模型/Provider/Checkpoint追加回放通过；上一轮3份报告、当前窗口8份报告及独立补验1份报告均只读一致。原先三个unknown partial回放证据保留。C恢复重新核验task/Spec/授权/PIT/版本/实际回执与ownership，不复制信任模型的verified状态。

业务CLI仍是README中的`--domain-analysis-mode direct|tool|child`、`--domain-analysis-execution serial|parallel`与独立profile入口。真实验收修订和复现需使用冻结入口，以保留原paid wire与版本。下列是本次验收的只读入口，不产生模型调用：

```powershell
$env:PYTHONPATH = 'src'
& .venv/Scripts/python.exe .runtime/domain-analysis-domain-tool-wire-repair-20261009.py replay
```

- [完整跨窗口判定、预算和Child阶段证据](../.artifacts/domain-analysis/verification-final-window-20261009/final-cross-scope-acceptance-20261009.json)
- [主窗口冻结](../.artifacts/domain-analysis/verification-final-window-20261009/plan.json)、[原评分及全部8次结果](../.artifacts/domain-analysis/verification-final-window-20261009/live/repair-2-summary.json)
- [单案例明确授权](../.runtime/domain-analysis-single-B-v4-authorization-20261009.json)、[独立冻结](../.artifacts/domain-analysis/single-B-v4-20261009/plan.json)、[完整真实结果](../.artifacts/domain-analysis/single-B-v4-20261009/live/summary.json)
- [主窗口8份只读回放](../.runtime/domain-analysis-verification-final-window-replay-20261009.json)、[补验只读回放](../.runtime/domain-analysis-single-B-v4-replay-20261009.json)、[上轮3份回放](../.runtime/domain-analysis-verification-retry-readonly-replay-20261009.json)
- [v4精确数据等价候选及测试](../.runtime/domain-analysis-domain-tool-wire-v4-gate-final-20261009.json)、[单案例入口安全门禁](../.runtime/domain-analysis-single-B-v4-entry-gate-20261009.json)
- [完整1159项回归门禁](../.runtime/domain-analysis-full-final-offline-gate-20261009.json)、[隔离数据库证据](../.runtime/domain-analysis-isolated-postgres-regressions-20261009.log)

最终四项判定：工程功能完成；受限真实业务闭环与最终六格覆盖通过；自主检查增量价值未证明；对强基线的实用收益未证明。交付真实结论并保留显式实验模式，原窗口失败评分和未知费用不改。
