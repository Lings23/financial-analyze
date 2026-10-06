# Phase 5 有界路线评估（2026-10-06，Asia/Shanghai）

用户明确请求推进 Phase 5，批准本会话必要的外部模型请求。本轮只评估既有 DynamicRuntime 的直接工具、串行 Financial/Market Child、并行 Financial/Market Child 路线，生成不可变评估 Trace 目录和有范围的启用决定。Phase 6、阈值调优、新金融 Provider/Dataset/Agent、交易及自动路由不在范围内。

**本轮实现与有界评估已完成，扩大并行启用范围的门槛未通过。** 真实运行8/9：direct 3/3、serial 3/3、parallel 2/3；688184并行Parent在verification前连续两次提前finish，原检查拒绝后partial/no_progress。全部九份报告只读回放一致，77次真实决策、157821已知暨记账Token、未知0，775/775隔离回归通过。保留失败，不修改冻结计划或重跑覆盖；默认、12000字节及Phase6边界保持。

后续最小Parent v2同案例修复复验已另行冻结并**1/1通过**，794/794隔离回归及新报告零模型回放通过。原8/9与原启用决定保持，复验独立新任务0；其余case未验证v2。实际修复与范围见本文末节。

## 事前冻结的设计

三个新 Dynamic validation 任务复用已知 Phase 3 合法不可变输入；不是盲样或独立金融真值。三个业务任务各运行三条路线，共九个运行，独立任务分母为三。路线顺序轮换，但没有随机化或缓存清理：输入源预检和逐轮授权读取使本轮属于已知本地归档、预热条件，不能推断线上冷缓存延迟或持续 SLA。

| 案例 | 源输入/PIT | oracle 预期 | 必须保留的结果 |
|---|---|---|---|
| 603207 | 已有财务/行情快照，system | completed；财务下降假设 unsupported | 7 Fact / 12 Evidence、两项正基数同比、原来源/时间/缺口 |
| 920110 | 已有北交所财务/行情快照，public | completed；财务方向 conflicted | 7 Fact / 12 Evidence、反证与方向冲突 |
| 688184 | 已有财务/行情快照，public | insufficient；净利润同比非正基数 | 6 Fact / 12 Evidence、合法 revenue_yoy、原净利润金额和 nonpositive_base 缺口；无 net_income_parent_yoy |

同项各路线证券、窗口、cutoff、PIT、不可变快照、source grants、hypotheses、确定性 oracle 及必需检查一致。五项执行检查必须 passed；第六项假设检查在第三题保持 insufficient，其余 passed。合法不足表示本题受控检查如实完成，不表示取得完整财务结论，更不能消除缺口来增加成功率。

直接路线使用既有 `dynamic-parent-domains-v2` 的受限普通工具集，保留 P4.4 的无损 Context Builder。串行路线使用既有领域 Parent v2；并行路线使用既有 ParallelParent；Child 显式 v3，默认仍 v1。三者共享模型、受控业务工具、数据层及验证。Spec identity、可见工具集和附加路线指令有差异，因此这是同 Runtime 的实际路线评估，不是原生 Single Spec 的隔离因果实验。并行两个源后的 calculation→hypotheses→verification 仍由原 DAG/Runtime 强制。

独立新 campaign 最大 **120 次父子模型决策 / 720000 记账 Token / 2400 秒绝对时限**。直接运行局部 8/12/48000/240 秒；串行/并行 Parent 局部相同，根 16/18/96000；每 Child 3 决策/1 source 工具/18000 Token/120 秒；固定 12000 UTF-8 字节。逐次 intent 先持久化；未知付费结果不重发、预留不释放。所有失败留在原分母，不提高预算，不事后改题或更换模型。

本轮只使用 `test_api.txt` 的配置端点和指定模型；密钥不输出、不复制、不进入 Artifact 或发行包。Financial Provider 网络请求为零：真实之处是配置端点的模型决策、已有合法真实源的授权读取、实际调度与闭环回执，不是重新联调供应商。

## 评分与启用规则

每个运行核对完整 oracle 事实/Claim/Evidence/假设/缺口、全部必需检查及合法结束状态；PIT、授权、快照与血缘依据原受控读取和精确源绑定验证，不将其升级为金融准确率认证。完整父子根账本已知 Token、记账 Token、累计派发预留、未知调用、未结算 Child 分开；wall latency 和 parallel section 分开，配对差值保留失败，不把 section/sum 比例冒称相对 direct 的加速。

只有九个运行都符合事前 oracle/必需检查、安全和资源约束，未知/未结算为零，九份零模型回放完全一致，三个并行运行均有实际 Child 模型 I/O 重叠，才支持已有双独立必要来源范围的显式 v3 opt-in。其他结果不扩大启用范围。任何情况下都不修改默认 Child 协议，不自动路由，不宣称广泛质量或统计性能优势，不开展 Phase 6。

评估目录索引完整报告、Trace、paid message/receipt、Checkpoint 和输入/计划哈希。旧 600500 原失败 0/1、v2 修复 0/1、v3 同案例复验 1/1以及历史上下文失败/修复单列诊断集；新独立任务计数为零，不合并到新三项分母。合成机制测试只验证评估器/预算/回放契约。

## 实施与实际执行

新增 `src/stock_research/research/trace_evaluation.py` 和 `scripts/phase5_evaluate.py`，只做确定性评估与真实运行封装；运行核心、模型协议默认及全部旧paid身份保持。新增23个评估器、6个harness机制测试；九条合成动作路径不计真实模型任务，也不计金融真值。

事前 `--prepare` 没有模型/Provider调用；计划SHA为 `bae9f7aea9c4fb8764df60e4f4e106d21cc6ecd1da266ae0b418693828be5869`。随后原计划一次 `--live`，当地00:38:02–00:42:39实际模型派发/回执，配置模型 `deepseek-v4-flash-0731`，零重试/替换/金融Provider采集。每次wire、receipt、Context Telemetry和完整根账本交叉核验；当前生产源码仍与freeze匹配。

| 任务 | direct状态/成功；Token；wall秒 | serial状态/成功；Token；wall秒 | parallel状态/成功；Token；wall秒 |
|---|---|---|---|
| 603207 | completed/是；14722；107.703 | completed/是；18502；25.828 | completed/是；21098；21.469 |
| 920110 | completed/是；14654；14.625 | completed/是；18428；26.813 | completed/是；21020；23.891 |
| 688184 | insufficient/是；14212；13.719 | insufficient/是；17951；24.937 | partial/否；17234；18.813 |

Token均含完整父子已知回执。direct共43588、serial54881、parallel59352；总77决策/157821已知暨记账Token。派发累计预留610803，包含组额度的根累计预留725019；后者不是720000的campaign记账用量，不能把累计预留、可释放已知未用额度和实际计账混算。未知调用/未结算Child均0，根与局部预算全部通过。

三次parallel都有真实Financial/Market模型I/O重叠，section分别5.294/6.854/5.465秒。两个完成研究的parallel运行比同题serial分别短4.359/2.922秒，Token却多2596/2592。688184的6.124秒差值带失败和缺少verification，不能计作同质量加速。每路线仅三项，第一项direct107.703秒是明显长耗时，端点响应/顺序/缓存影响未隔离；median和nearest-rank P95仅是本批描述，不能宣称统计性能优势。没有观察到Multi质量增益，当前数据不支持扩张。

九运行PIT/授权/不可变输入/血缘/数值检查均通过，45项执行检查44项passed；direct/serial各15/15，parallel14/15。688184三路线的假设均保持真实insufficient，source-bound6Facts/12Evidence一致，未伪造净利润同比；其他两题7/12一致。parallel失败时完整数值报告的独立核对仍verified，但不代替模型应执行的verification工具检查。

失败run `8ce6a716b831484daebccf0002e60662`：Parent依次parallel→calculation→hypotheses，第4/5轮重复合法finish(insufficient)。两次均被typed `required_checks_pending` 拒绝，pending为verification；原no_progress规则诚实停止，全部六项检查ID保留，verification=not_completed。两Child均completed，源/额度/格式/12000 cap均不是此次阻塞，不能将它归为外部条件豁免或合法不足成功。报告及paid wire原样冻结，本轮没有改Prompt/Spec或追加付费复验。未来若修Parent推进反馈，须另版本化并冻结新独立额度，原8/9保持。

全部真实Context测量完整，direct最高10400、serial10792、parallel11341/12000字节；overflow、超限派发和cap差异均0。没有LLM摘要、有损裁剪或阈值调整。

新九份报告在原权限下 `--replay` **9/9完全一致**，模型/Provider/Checkpoint追加0。历史P45/v2/v3仍0/1、0/1、1/1；额外历史审计九报告、10/10回放、479个原文件和SQLite内容/SHA保持。Trace Dataset包含9新运行及3份P45历史/复验完整行，另绑定九份历史诊断索引（其中三份重合），历史/合成不进入新分母。新Dynamic validation任务按case计三，独立盲test为零。

Trace Dataset SHA `7d251dcb29cf9fecf0cf93d3ffdbd58cb3e98cb70a322aaa9a649aff330f1c6e`。机器证据在 `.artifacts/phase5/targeted-20261006/{plan.json,live/summary.json,live/trace-dataset.json}`；只读决定在 `.runtime/phase5-replay.json`，历史审计在 `.runtime/phase5-historical-audit.json`，独立审查在 `.runtime/phase5-independent-review.json`。

**启用决定：`bounded_opt_in_not_supported`。** 本轮既有路线评估已完成，事前9/9功能门槛未达到；不扩大并行启用范围。保留既有显式试验入口与历史v3成功，不改默认Child v1，不自动路由。Phase6未启动，12000保持；Provider金融准确性、历史发布准确性、独立盲样、冷缓存和长期SLA均未认证。

## 回归与交付检查

| 实际执行 | 结果 |
|---|---|
| 系统Python基线：`PYTHONPATH=src python -m unittest discover -s tests -v` | 746项731通过/15跳过（14数据库、1可选AKShare SDK），`.runtime/phase5-baseline-offline.log` |
| 项目.venv最终纯离线，同unittest命令 | 775项761通过/14数据库跳过，`.runtime/phase5-final-offline.log` |
| `scripts/test-postgres.ps1 -Image 57c72fd2a128`，专用隔离容器 | 775/775通过、0跳过，容器回收；`.runtime/phase5-final-postgres.log` |
| compileall / pip check / CLI --help | 全部通过 |
| setuptools源码发行包及密钥精确扫描 | 64文件，新模块齐全，源码/新Artifact/日志/包内匹配0，禁入文件0；没有发布，wheel未验证 |

发行包位于 `.runtime/phase5-distribution/stock-research-data-0.1.0.tar.gz`。上述验证均为实际执行；最终交付完整性检查另存 `.runtime/phase5-delivery-integrity.json`，不覆盖冻结live材料。

## 后续最小修复与同案例复验（独立记录）

用户随后明确要求验收失败时设计最小修改并尝试重新验收。原9/9门槛仍未达、原8/9和`bounded_opt_in_not_supported`保留。最小修改新增显式`dynamic-parent-parallel-v2`，默认仍v1；Runtime原revision检查确定性生成`control.execution`的pending_checks/can_finish/next_action，分离执行进度与假设证据不足。候选只使用既有授权工具的精确动作，不执行工具或授予权限，不改变finish/no_progress/DAG/预算/Child v3/12000上限。旧协议wire和身份保持。

付费复验前已复制原冻结62文件并逐SHA匹配；原九报告在修复代码上9/9零模型回放、旧六份P4.3/P4.4报告6/6回放相同，原文件/Checkpoint不追加。原688184五轮paid状态经SQLite只读hashchain检查，v2重构6393/7777/9807/11411/11614字节；原question/plan/rejection、目录/源/Claim/Evidence和委派结果完全相同。最后两轮都显示verification待执行及精确候选。该预检不是新真实模型结果，证据`.runtime/phase5-parent-repair-wire-preflight.json`。

新复验只取原688184并行同请求、源、PIT/cutoff/grants、oracle和指定端点/模型；仅Parent协议和run ID变更。独立事前冻结16父子决策/96000记账Token/480秒，Parent局部8/12/48000/240秒、Child v3仍3/1/18000/120秒。必需执行检查、完整6Facts/12Evidence、合法hypothesis insufficient、根/付费/未知用量、PIT/权限/快照/血缘、真实模型I/O重叠与零模型回放都须通过。复验独立新任务0，不能补回原9/9或称其他case已验证v2；如失败保留再诊断，不盲重跑或提高预算。

### 实际复验结果

单项真实复验**1/1通过**，根run `78989fe805654ee6871fe713435e5d08`。两Child独立并行模型I/O重叠，Parent按下表实际选择动作，Runtime没有替模型执行候选：

| Parent paid轮 | 实际输入字节 | 可信待执行状态/候选 | 指定模型实际动作 |
|---|---:|---|---|
| 1 | 6393 | read与calculation/hypotheses/verification待执行；候选null，不强制路由 | parallel Financial/Market Child |
| 2 | 7777 | calculation/hypotheses/verification待执行；候选calculation | tool calculation refs=[financial,market] |
| 3 | 9673 | hypotheses/verification待执行；候选hypotheses | tool hypotheses refs=[calculation] |
| 4 | 11318 | verification待执行，can_finish=false；精确候选verification | tool verification refs=[hypotheses] |
| 5 | 10368 | pending=[]、can_finish=true、候选null | finish reason=completed |

五项必需执行检查全部passed，第六项`hypothesis:financial_deterioration`仍insufficient。Runtime按原证据规则报告**insufficient / evidence_insufficient**，不能因为模型请求completed就把非正基数变成支持；6Facts/12Evidence、原营收同比/价格变化/回撤与缺口逐项匹配oracle。第4轮实际执行verification，不能用独立报告验数代替；本次没有提前finish拒绝，拒绝后纠正另由合成机制测试覆盖。

Parent5决策/13846Token，Financial2/1580，Market2/1511；根**9决策/7工具/16937已知暨记账Token/unknown0/未结算0/金融Provider网络0**。派发累计预留68893、根累计预留87929分列，均不冒充记账成本；wall19422ms、parallel section6273ms、两分支执行和10580ms。新一项是已知源同案例非盲修复，时段与模型输出不同，不以本次延迟或Token与旧失败比较宣称性能优势。

PIT/权限/不可变快照/血缘/数值五安全项全部passed，九paid回执逐wire/遥测/根账本核对。完整新报告1/1零模型/Provider/Checkpoint追加回放一致；原九报告仍9/9一致、原8/9不改，原及v2/v3 P45历史失败/复验不改。Trace manifest冻结report/summary/dataset/dispatch/SQLite，原618campaign文件与62源码副本SHA保持。修复接受范围为`single_case_parent_v2_parallel_closed_loop_only`；原`bounded_opt_in_not_supported`和原9/9未达保持，不能说其余case已验证v2或扩大默认启用。

新计划SHA `695fb5f6633e9989b015314d8bfe526486daa250ad848034204e00435e238731`；新修复Trace SHA `e6449f61c5b287a2afca435c3d76c28fea902899d87336b951c267687e10ce15`。实际证据`.artifacts/phase5/parent-progress-v2-20261006`，只读回放`.runtime/phase5-parent-repair-replay.json`，五源码独立审查`.runtime/phase5-parent-repair-code-review.json`。修复代码完整纯离线790项776通过/14数据库跳过，随后新增harness4/4机制通过；最终隔离PostgreSQL **794/794通过、0跳过**并回收容器。新增19项均合成机制，compileall/pip check/CLI帮助通过；日志`.runtime/phase5-parent-repair-{offline,postgres,live}.log`。默认v1、Child默认v1、12000字节与Phase6边界保持。

修复发行包`.runtime/phase5-parent-repair-distribution/stock-research-data-0.1.0.tar.gz`含64文件，SHA `42d8332becdba1730b8a4a0f5b4d5ddce4cf35816a000738ae8225ca7f8e7518`。首次完整交付扫描318源码/文档、778Phase5产物/日志、64包内文件的真实密钥精确匹配均0、禁入文件0，新Runtime模块齐备；旧62源码副本和新修复code freeze均匹配。证据`.runtime/phase5-parent-repair-final-integrity.json`；没有发布，wheel未验证。新旧Trace指针及各自SHA独立固定于`.artifacts/phase5/trace-index-20261006.json`，原评分/分母保持。

独立实际只读审查进一步从三run SQLite paid状态逐字节重构新九wire，验证intent/receipt/遥测/Root事件账本、实际verification及冻结oracle；618原campaign文件、62原源码副本和63修复源码逐SHA匹配、前后不变，模型/Provider/Checkpoint追加0。记录`.runtime/phase5-parent-repair-independent-real-review.json`（SHA `89a74d56fb5ae62c21d430edf57d34aeb296b36c2c8fd78e4461cc89b0704fbc`）；最终文档与新增审查的完整扫描另存`.runtime/phase5-parent-repair-delivery-integrity.json`。结论只覆盖本单项修复，原启用门槛与独立样本边界保持。
