# W1b Parent v5：去重与按阶段披露实施

日期：2026-10-07（Asia/Shanghai）。**显式实现与限定验收完成：真实4/4、零追加回放4/4，默认保持。**

用户“阅读方案后，执行v5”授权落实[整合方案](CONTEXT_CONTINUATION_DESIGN_20261006.md)与[去重设计](CONTEXT_DISCLOSURE_DEDUP_DESIGN_20261007.md)的 W1b。仅新增显式 Parent v5/disclosure-view/v2；默认、v1–v4、旧付费原件/恢复身份、12000 UTF-8 字节和原局部/根限制保持，Child 显式 v3。不实施 v6/context_read/分页或 W3。

完整 audit 留程序側，真正就绪时才附准确的 verification_brief。每轮仍带完整当前任务、范围、checks、事实/假设/缺口/反证和精确 revision；当前消息 digest 表严格可逆。保留 v4 完整源集合、真实工具执行凭据、权限/PIT/快照/血缘及付费恢复核对，全量 verifier 不改。

先离线、安全/恢复和历史零追加回放，再独立冻结最多两旧案例/四运行 v4 baseline/v5 candidate：64 父子决策、384000 记账 Token、1800 秒，原局部/根上限不变。新预算不复用历史额度。完成后补录实际结果；没有合法当前超限材料时明确真实超限恢复未验证，不把合成数据当金融真值或字节当 Token/延迟收益。

## 已执行离线检查与冻结

最终项目虚拟环境912项898通过/14数据库跳过、0失败（643.020秒）；PostgreSQL未验证。新增codec10/10、Runtime34/34、harness7/7、合成80行补充1/1通过，扩量机制保留7 Facts/85 Evidence并实际verification/finish，最高10685字节；合成不算金融真值。历史27/27零模型/Provider/Checkpoint追加回放一致，5667历史哈希条目保持。

只读十份实际v4 paid状态完整system+user同状态94979→87345字节，少7634（约8.04%），每阶段减少，v5最高10237/12000。这只是新实现的同状态字节测量，实际Token/延迟待真实回执，不沿用设计样例10.05%或推算金额。

首次完整系统Python回归保留912项/1失败/15跳过：唯一失败为旧支持版本枚举仅列v1–v4，修正测试期望后13/13复测及上述最终全套通过。最初定向测试有一次测试自身的canonical payload hash断言错误，改正后34/34通过；生产值/算法未因此修改。首个被后续测试增补中断的日志、全部失败及诊断保留，不计真实分母。

离线gate `.runtime/context-v5-offline-gate-20261007.json`；只读预检 `.runtime/context-v5-readonly-preflight-20261007.json`；历史回放 `.runtime/context-v5-historical-replays.json`。冻结 `.artifacts/context-disclosure/phase-gated-v5-20261007/plan.json` SHA `efdd5558953cb52f04b6a8dd492eff02edfdeebcefccd6787c1d7bb33e2ad021`，四槽、两已知非盲case、独立新任务0、修复槽0；不复用历史预算。

首次启动外发遭自动审批拒绝（授权未具体列载荷/接收地址），未创建live目录/paid intent。外发范围/原消息SHA和配置端点核对写入 `.runtime/context-v5-egress-review-20261007.json`；用户追加批准本会话所有真实外发后，使用同一冻结计划、指定模型及配置阿里云端点执行，无替代模型或新金融Provider采集。

## 真实验收、回放与审计

| 旧案例 | Parent版本 | 状态/质量 | Fact/Evidence | 整任务Token | Runtime ms |
| --- | --- | --- | --- | ---: | ---: |
| 603207 | v4 baseline | completed/通过 | 7/12 | 18213 | 22235 |
| 603207 | v5 candidate | completed/通过 | 7/12 | 16208 | 21922 |
| 688184 | v5 candidate | 合法insufficient/通过 | 6/12 | 15942 | 23500 |
| 688184 | v4 baseline | 合法insufficient/通过 | 6/12 | 18073 | 21906 |

四运行4/4质量通过、零模型/Provider/Checkpoint追加回放4/4完全一致；原Fact/Claim/Evidence/假设/不足/反证/血缘与完整源oracle逐字段核对，688184非正基数缺口不被删除或改为同比成功。20项必需执行检查passed，四次verification均模型实际选择并成功执行；引用、brief、audit、Child完成和报告自动重验证不能替代该动作。每Parent均parallel→calculation→hypotheses→verification→finish五决策，Financial/Market Child各两决策，真实I/O重叠4/4。独立审计12 run链/360 Checkpoint行/36 paid状态与回执，原完整计算/源与执行凭据保持。

累计真实36父子决策/28工具、68436已知暨记账Token、未知0、新金融Provider网络0。累计派发预留275197、根累计预留351341分别报告，不等于实际Token或金额。最高实际system+user11057/12000字节，v5最高10108；新64/384000/1800与原Parent8/12/48000/240、Child3/1/18000/120、root16/18/96000及授权/PIT/快照/取消/未知结果/no_progress限制均保持。四槽已用、真实失败0、追加重试0、独立新任务0；历史失败/分母/paid原件保持。

本次候选实际paid状态回编同状态v4仅作本地字节比较：完整十份system+user **94648→87014 bytes，少7634（8.07%）**，每阶段减少。两case每阶段省728（取源前）、729（calculation前）、789（hypotheses前）、664（verification前）、907（finish前）字节；仅两份真正就绪输入带brief，验证前Evidence正文仍0，完整每run12 Evidence保留。它与事前v4旧paid状态94979→87345不同，因为本次plan/control逐字保留；都不能反推Token。

| 两案例合计 | v4 input/output/total Token | v5 input/output/total Token |
| --- | ---: | ---: |
| Parent | 29695 / 406 / 30101 | 25583 / 382 / 25965 |
| Financial Child | 3075 / 88 / 3163 | 3075 / 88 / 3163 |
| Market Child | 2934 / 88 / 3022 | 2934 / 88 / 3022 |
| 整任务 | 35704 / 582 / 36286 | 31592 / 558 / 32150 |

真实父子总Token少4136（**11.40%**），为原端点实际回执，不由字节推算。Runtime **44141→45422ms**，多1281（2.90%）；整体harness wall44905→47766ms，模型I/O interval union20112→20305ms，均按原真实区间报告，不用回放耗时替代，也不重复加重叠Child。详细各角色/工具/分支/queue/join span在immutable Trace dataset，模型服务端处理与网络无法进一步拆分，未证实延迟改善。缺端点价格/账单，金额未知；两旧非盲案例/非随机顺序、plan与时段混杂，不声明P95/统计优势或未来平均收益。

正式决定 **`limited_explicit_phase_gated_disclosure_accepted`**。接受显式v5的阶段披露与精确去重，保留所有默认/旧wire/Spec/paid身份/Checkpoint/12000及原预算。无合法当前真实超限材料，**真实超限恢复尚未验证**；v5不等于W2/v6通用分页/context_read或无限续跑，不启动W3、下一包或额外campaign。

## 复验与证据

正式计划及immutable live原件位于 `.artifacts/context-disclosure/phase-gated-v5-20261007`。只读结果 `.runtime/context-v5-replay-20261007.json`、实际审计 `.runtime/context-v5-actual-audit-20261007.json`、完整指标 `.runtime/context-v5-metrics-20261007.json`；交付初检509文件与独立索引完成后复核511文件，密钥精确匹配/秘密文件禁入均0，源码freeze/历史SHA保持，证据 `.runtime/context-v5-{delivery-integrity,final-delivery-integrity}-20261007.json`。旧live summary原来的pending标记不回写，独立acceptance索引 SHA `9373ded39164d3e1764a20aa4ffa7eebc460fe0c28f50caaeaf36d8f3c078093` 引用实际回放决定。

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/context_disclosure_acceptance.py --replay `
  --plan-sha256 efdd5558953cb52f04b6a8dd492eff02edfdeebcefccd6787c1d7bb33e2ad021 `
  --output .runtime/context-v5-replay-new-readonly.json
```

输出路径必须新建；只读回放不调用模型/Provider、不追加Checkpoint。新显式入口为 `--workflow dynamic --parallel-domains --parallel-version dynamic-parent-parallel-v5 --child-protocol-version v3`，旧入口与原版本显式恢复保持。四槽已用，不能重跑live或复用旧余额。
