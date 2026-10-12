# W2 Parent v6：有界分页与工作集替换

实施日期：2026-10-07；收口日期：2026-10-08（Asia/Shanghai）。用户要求阅读[整合方案](CONTEXT_CONTINUATION_DESIGN_20261006.md)后执行 v6，并明确批准本会话一切真实外发，随后要求继续按计划收尾。本文记录独立实施与验收，不改写 v4/v5、Phase 6 或其他历史结果。

**结论：显式 v6 已完成限定机制与已有真实案例验收。** 最终982离线968通过/14数据库跳过、另行隔离PostgreSQL17/17；历史31及新真实4份报告均零追加回放一致，真实质量4/4。实际context_read页回执为0、真实超限分页恢复仍未验证，实测Token增加20.77%，不宣称成本或延迟收益。默认/12000/原预算/Child v3/历史原件保持，四槽已用，不启动W3或后续阶段。

## 实施与冻结边界

显式 `dynamic-parent-parallel-v6` / `dynamic-context-window/v1` / `bound_exact_pages/v1` 复用同一 DynamicRuntime、完整 immutable catalog、Registry/Executor、Evidence、Trace、Checkpoint 与 root ledger。默认仍为旧版，Child 显式 v3；12000 UTF-8 字节及 Parent 8/12/48000/240 秒、根 16/18/96000、Child 3/1/18000/120 秒均保持。

新增严格 `context_read` 两互斥形态：当前 catalog + 已登记 refs（1–16）+ 原 plan，或当前 catalog + 已签发 cursor + 原 plan。只接受当前付费窗口中的 refs/cursors，拒绝隐藏 ID、任意路径/URL/查询、跨 run/scope/catalog 和陈旧对象。v1–v5 的动作、disclose、wire、Spec、默认、恢复身份不变；v6 使用新页契约，不把片段冒充旧完整 disclose。

目录、Fact 投影、假设、periods 与完整 C/E/H/O 对象按确定性顺序分页。Fact 投影保留全部 name/value/unit/formula/window/available_at，inputs 用精确 count/hash/path 入口。对象页用完整 JSON scalar 和显式容器标记，保存原顺序、重复和空容器；不使用模型摘要、相似度筛选、数值裁剪或标量分割。全部原对象及原 full verifier 输入保持。

窗口按实际 system+user 的完整字节编译，包含当前原任务、plan、全部 checks、授权范围、权威 revision、DAG 执行反馈与真实预算。`dispatch_ref` 绑定实际 system/control/turn/plan/budget/error，窗口核心排除 window_ref、cursor 和 actual message SHA，避免循环；实际 SHA 与付费 intent 一同持久化。新 run 使用独立 `dynamic-window-state/v1` 和 `dynamic-window-store/v1`，原物理追加哈希链与 Run 锁不变。

读取先保留必需 source/derived/finish 决策与工具余量，再消耗原工具额度、持久 tool_started、重授权、按下一轮已计账真实头部预编译片段、读取后重授权，最后在同一追加中提交完整页回执及精确选择。已提交 end 不能因后续头部变大而默默缩短，最小必要头部/原子项超限返回 `partial/context_minimum_view_exceeded`。coverage 按对象完整内容版本与成员路径核对，O 内 C/E/H 与直接对象读取归一；新组合/顺序/游标不把旧成员当新进展，两次 no_progress 保持。

恢复重新授权所有完整源、工具和 Child，重建每个 paid wire、descriptor、范围/content hash、读取 provenance、selection 与 coverage。未知模型/页工具结果不重发、不释放未知预留。分页、引用、audit/brief、自动重验证和 Child 完成均不满足业务 checks；模型仍须实际选择成功执行完整 verification。

## 实际验收

最终完整离线 **982项968通过/14数据库跳过、0失败，986.300秒**；代码/测试/日志绑定新offline gate。核心19/协议14/Runtime18/安全11/harness8共70新增项全部通过。另行专用隔离PostgreSQL **17/17、0跳过**，包含原14数据库项和v6三项分页/撤权/三路径恢复机制，44.799秒，容器已回收。compileall、pip check、CLI帮助和diff检查通过，历史31/31零模型/Provider/Checkpoint追加回放一致；全部合成机制与真实结果分列。

事前冻结计划 SHA `745e384daab1541e9cdc229c2b0fd578330cdc8dd9a60b8169634ed89a181879`，四新run、两旧case、v5 baseline/v6 candidate、Child显式v3；新64父子决策/384000记账Token/1800秒，原父子/根限额不变。计划及全部live原件位于 `.artifacts/context-window/bounded-v6-20261007`。Trace dataset SHA `f8de7455790993aad3865855dbd96f0edcda90ee05f770c2b355e21a17584308`；不修改immutable summary中的pending标记，正式回放决定保存在独立索引。

| 旧case | Parent | 状态/质量 | Fact/Evidence | 整任务实测Token | Runtime ms |
| --- | --- | --- | --- | ---: | ---: |
| 603207 | v5 baseline | completed/通过 | 7/12 | 16168 | 22984 |
| 603207 | v6 candidate | completed/通过 | 7/12 | 19367 | 22125 |
| 688184 | v6 candidate | 合法insufficient/通过 | 6/12 | 19422 | 25407 |
| 688184 | v5 baseline | 合法insufficient/通过 | 6/12 | 15950 | 24750 |

真实质量 **4/4**、只读回放 **4/4完全一致**，模型/Provider/Checkpoint追加0；20必需业务执行检查passed、4次verification实际执行、双Child真实I/O重叠4/4。完整Facts/Evidence/假设/不足/反证/血缘及原source oracle等价，688184非正基数缺口和原假设不足保持。独立审计12 run链/360 Checkpoint行/36 paid状态及回执，完整权限/PIT/快照/授权源和实际工具凭据保持。

累计 **36父子模型决策/28工具/70907已知暨记账Token/unknown0/金融Provider网络0**；每Parent5决策，每Child2决策。四槽全用，真实失败0、付费追加0、独立新任务0，不复用旧额度。累计dispatch预留280820、根累计预留356964分别保留，不能当成实际Token或金额。最高实际system+user11753/12000字节。

| 两case合计 | v5 baseline | v6 candidate | candidate−baseline |
| --- | ---: | ---: | ---: |
| 实测input Token | 31596 | 38348 | +6752 |
| 实测output Token | 522 | 441 | −81 |
| 实测total/记账 Token | 32118 | 38789 | +6671（+20.77%） |
| Runtime ms | 47734 | 47532 | −202 |
| 模型I/O interval union ms | 21458 | 23161 | +1703 |
| 整体harness wall ms | 48406 | 50359 | +1953 |
| 完成后Checkpoint DB bytes | 11837440 | 13496320 | +1658880 |

候选十份真实paid状态同状态回编v5，仅作本地字节比较：**86495→100561 bytes，增加14066（16.26%）**。它与事前v5旧paid状态87014→101080不同，因为实际plan逐字保留；不把两类字节与实测Token混用。Claim投影/精确页描述/计数/游标与预算头部在这些小案例增加开销，实测总Token增加；两旧非盲case、非随机顺序、服务端时间和plan有混杂，−202ms的Runtime差不能证明延迟改善，不声明P95或统计优势。价格/账单未提供，金额未知；编译与历史重建的独立耗时未从nested Runtime分离，模型I/O与工具span见Trace，不重复相加。

正式决定 **`limited_explicit_bounded_window_accepted_real_pagination_unverified`**。仅接受显式窗口机制与已执行真实case闭环。真实模型没有选择context_read（页回执0），当前没有合法v5真实超限材料，**真实模型读页/超限分页恢复仍未验证**；自动阶段窗口变化不能充当真实context_read验收。单Claim长inputs、多目录/期间/完整Evidence分页及至少两次工作集替换的证明目前来自合成机制，不是金融真值或真实超限成功。本包停止，不启动W3、不改默认/12000/原预算，不扩大金融数据或并行范围。

只读结果 `.runtime/context-v6-replay-20261008.json`、实际审计 `context-v6-actual-audit-20261008.json`、指标 `context-v6-metrics-20261008.json`；旧日期提取器生成的原campaign指标`context-v6-metrics-20261007.json`逐字保留，新副本仅登记正确收口client_date/campaign_date与原副本SHA，实际指标相同。最终offline gate `context-v6-offline-gate-20261007.json`绑定日志`context-v6-offline-final-20261007.log`。交付密钥/历史/原件完整性扫描与独立acceptance索引另存，不回写旧paid/live原件。

交付初检`.runtime/context-v6-delivery-integrity-20261008.json`（676文件）和包含正式索引的`context-v6-final-delivery-integrity-20261008.json`（678文件）均通过：实际密钥精确匹配0、秘密文件禁入0；69份冻结代码/82份测试/历史原件/live原件SHA保持，12运行链/360行再次核验，46 Markdown/267本地链接/围栏和diff通过。正式索引 `.artifacts/context-window/bounded-v6-20261007/acceptance-20261008.json` SHA `793ddcb8c51a7b6e94f0d63f18705852a8ba983e5cebc2eca560a3d947caf2d8`引用实际plan、Trace、offline gate、回放、审计、指标与完整性证据；最终文档落盘后的完整性证据另存`.runtime/context-v6-closeout-integrity-20261008.json`，不再修改paid/live原件。

### 实施过程、预检和中间失败（保留）

以下为最终执行前的过程记录。核心19项、新协议14项、旧协议43项、Telemetry8项及v5 Runtime34项定向通过；harness7项及两页边界复算机制1项通过，两次工作集替换仍成功执行全量verification/finish，完成后零追加恢复。全部为合成机制，不算金融真值或真实分页。

历史31/31报告零模型/Provider/Checkpoint追加回放一致，旧失败与所有历史哈希保持。真实旧v5十个paid状态的授权/oracle只读预检通过，v5 87014→v6投影101080字节（增加16.17%，最高11842/12000）；不能推算Token收益。没有合法当前v5超限材料，真实超限恢复/模型context_read尚未验证。证据 `.runtime/context-v6-historical-replays-20261007.json`、`context-v6-preflight-20261007.json`。

初次Runtime测试暴露新schema未接旧ledger恢复校验，修复独立版本分支；其他测试自身字段/披露入口/工具计账期望错误也已修正，中间日志完整保留。独立安全审查实证发现三项：删window引发IndexError；故障在页回执提交而未nextpaid时，协调重哈希修改end/范围/hash/coverage可被接受；瞬态read意图伪造tools_used可绕过末态账本校验。分别用类型化IntegrityError、从真实tool_started checkpoint重编下一窗口严格核selection、对每个paid/read intent核完整账本修复。新11项安全组与完整离线gate共同收口，不把首次失败删出记录。

Docker daemon探测不可连接，数据库仅允许专用隔离实例，未替换DSN；本轮PostgreSQL集成尚未验证。compileall、pip check、CLI帮助与diff检查已通过。用户后续明确批准本会话一切真实外发，仍按先离线、再冻结/执行顺序和四槽上限。

用户重新启动Docker后追加专用隔离验证：现有镜像`57c72fd2a128`，仅127.0.0.1随机端口，原14数据库项与新增v6分页/撤权/三路径恢复3项 **17/17通过、0跳过，44.799秒**；容器已回收。没有使用原持久库，没有模型/金融Provider网络调用；合成检查不算金融真值。日志`.runtime/context-v6-postgres-20261007.log`，脚本`.runtime/context-v6-postgres-check.{py,ps1}`。

首次完整回归982项：967通过、1旧P4.5合成失败、14数据库跳过，1038.690秒；新v6 70项全通过。旧Child v2夹具瞬时返回使严格UTC I/O区间不重叠，独立3次诊断中1次失败，完整业务/原oracle/预算/worker重叠均通过，只是actual_child_model_dispatch_overlap=false。参考历史Child v3夹具只在首轮Barrier后增加20ms有界合成停留，原动作/断言/真实wire/评分/预算不变，3/3稳定通过（11.685秒）。最终完整回归重新执行，首轮失败不删、不算真实金融功能分母。证据`.runtime/context-v6-offline-20261007.log`、`context-v6-p45-fixture-{diagnosis,repair}-20261007.{json,log}`（repair只有log）。

验收只含两旧 case × v5 baseline/v6 candidate、最多四运行；新 campaign 上限 64 父子决策/384000 记账 Token/1800 秒，不复用历史额度。完整事实/证据/不足/实际验证质量、逐轮字节、整任务实际 Token、额外页决策/工具、耗时和 Checkpoint 体积分列；不要求字节收益，不由字节推算 Token 或声称 P95/统计优势/金额收益。

## 可复现命令

```powershell
$env:PYTHONPATH='src'
& .venv\Scripts\python.exe -m unittest discover -s tests -v
& .venv\Scripts\python.exe scripts/context_window_acceptance.py --historical-replay --output .runtime/context-v6-my-historical-replays.json
& .venv\Scripts\python.exe scripts/context_window_acceptance.py --preflight --output .runtime/context-v6-my-preflight.json
& .venv\Scripts\python.exe scripts/context_window_acceptance.py --replay --plan-sha256 745e384daab1541e9cdc229c2b0fd578330cdc8dd9a60b8169634ed89a181879 --output .runtime/context-v6-my-readonly-replay.json
```

显式 CLI 选择 `--parallel-domains --parallel-version dynamic-parent-parallel-v6 --child-protocol-version v3`。本包完成后停止；W3、LLM 摘要、新 Provider/Dataset/领域 Agent/模型/端点/Runtime、更大上下文或预算、无限续跑及下一阶段均不实施。
