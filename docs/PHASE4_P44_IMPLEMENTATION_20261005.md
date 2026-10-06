# P4.4 实现与实际验收（2026-10-05）

**Financial/Market 串行领域委派已实现，工程与安全回归通过；完整真实功能验收未全部通过。** 原冻结两任务功能1/2、路由2/2、根预算2/2；一次明确动作格式的混合路径新运行仍因上下文上限返回partial。不能把两种路由均出现或数值verified表述为两任务功能均通过。P4.5未开始。

## 交付范围

- 新`DomainParentSpec`/`dynamic-parent-domains-v1`：同一个Parent通过现有JSON动作选择普通`financial`/`market`或AgentTool；每域最多一个Child、总最多两个、严格串行。
- 新`MarketRequest`/`MarketChildSpec`/`market-child-v1`只读父原绑定的行情、交易日历及复权因子；Financial Child保留原有身份。两个Child均复用DynamicRuntime/Registry/Evidence/Checkpoint，不能spawn、调用另一域或执行研究计算。
- 权限取父有效工具、可信委派工具/数据、各ChildSpec及实际Provider/SourceGrant交集，继承原证券、窗口、带时区cutoff/PIT和不可变快照。读、缓存、活动Child和恢复继续重授权。
- `root-budget/v2`支持至多两个串行预留/结算，活动Child期间不派发Parent或另一Child。默认根16决策/18工具/96000记账Token；Parent局部8/12/48000/240秒、每Child3/1/18000/120秒，启动前完整持久预留。unknown部分不释放，恢复不重新付费，deadline/cancel向下传播。
- Child结构化来源结果经父重新核验后导入普通域Observation；Parent继续计算、假设检验和独立Fraction验证。`delegation_results`最多两项，只含固定tool/domain/status/result_ref，不携带自由数值或授权。报告记录direct/delegated routes及父子Evidence关联。
- CLI增加`--domain-agents`，仅dynamic/v2、与`--financial-child`互斥。预览不读源/配置/模型/Checkpoint；输入仍为可信manifest和一致的question，没有新增自由自然语言请求编译或交互UI。
- 原Dynamic v1/v2及P4.3的Spec、消息、单Child账本和报告行为保留；没有独立Router模型、并行、新Provider或交易功能。

源码集中于`src/stock_research/research/{dynamic_contracts,dynamic_protocol,dynamic,root_budget,cli,report}.py`。本轮审查发现并修复本地直接读的跨域Evidence归因缺口：现在Evidence的record_id所属于的源域须与实际tool_call_id的域一致；Child引用也须同时匹配域、记录和实际读取调用。

## 实际工程检查

在`PYTHONPATH=src`环境下执行`python -m unittest discover -s tests -v`，最终**542项：529通过、13专用PostgreSQL项跳过**。使用本机既有postgres16镜像、127.0.0.1随机端口临时隔离容器执行相同完整回归，**542/542通过、0跳过**，容器已清理。

最终日志：`.runtime/phase4-p44-offline-complete.log`、`.runtime/phase4-p44-postgres-complete.log`。此前528项离线及534项隔离回归保留，不替代最终数字。compileall、pip check、实际`python -m stock_research research --help`通过。此前对research子包直接使用`-m`的帮助命令错误已纠正，不算通过。

相对P4.3新增70项：协议13、根预算15、Runtime领域19、CLI9、主QA9、定点QA5。覆盖两域顺序及直接/委派组合、每域唯一Child、完整根额度不足、第二Child崩溃/未知结果、部分失败与重新选择、撤权/cancel/迟到、域/来源/报告篡改、completed零模型回放，以及出站数字/自由委派字段注入与冻结任务截断。这些是合成机制测试，不能当作金融真值或实时Provider认证。

额外使用当前Runtime回放P4.3的两份实际历史报告，**2/2完全一致**，模型/Provider/Checkpoint追加均0；旧计划、报告及SQLite字节SHA未变。没有调用旧frozen harness的`checked()`：新源码应使其旧代码哈希门按设计拒绝；产品身份兼容和冻结旧源码相同是两个不同检查。证据`.runtime/phase4-p44-p43-compatibility.json`。

## 新冻结真实批次

仅复用既有002363和601009公开合法快照，无新金融采集。两项输入契约通过、源成员/权限/PIT/envelope及首轮消息在派发前固定；同一指定`deepseek-v4-flash-0731`及本地配置端点、零网络重试/模型替换。独立campaign上限28决策/168000记账Token/720秒；首份无付费预检计划在补齐任务列表/预览一一对应和外部计划SHA后保留，未覆盖。正式目录`.artifacts/phase4/p44-20261005-v2/`。

正式计划SHA：`20ac60e47c17cfca291a27de61b7a930cd2604a5dfe081b664fcc782f72d67a7`。原绝对截止为`2026-10-05T05:33:36.604991+00:00`。派发脚本`phase4_p44_demo.py`逐次重建typed messages、检查公开数值/envelope与秘密反射，先持久intent后调用，完整已知回执才替换预留。

| 原预登记任务 | 实际结果 | 父/子调用与Token | 功能判定 |
|---|---|---|---|
| 002363混合路径：financial_child、market直接 | 两路取数及calculation完成；模型先返回`action=calculation`，修正后又连续返回`action=hypotheses`，Runtime按非法动作/连续无进展停止；hypotheses/verification执行检查未完成 | Parent6决策/11796Token；Financial Child2/990；根8/12786 | **失败：partial/no_progress**；路由与预算通过，数值verified不等于执行完成 |
| 601009双Child：financial_child、market_child | 两Child串行完成；父完整执行计算/假设/验证；缺2024Q1同期证据按原规则保留 | Parent7/15145；Financial Child2/983、Market Child2/999；根11/17127 | **通过：insufficient**；没有猜测同比或替换报告期 |

原两任务**功能1/2、路由2/2、预算2/2**；19决策/29913实测暨记账Token/131194累计派发预留/unknown0。所有原始response、非法动作、partial、报告、评分及计划保留。独立只读核对22条Evidence、15条父子links、3个串行Child与19/19完整ChatResult回执合法，未改变旧证据SHA；见`.runtime/phase4-p44-review.json`。主脚本新进程无网络回放两份报告完全一致。

## 定点新运行与未通过项

没有修改Agent/Prompt/评分或原题报告。对原混合任务的问题补充既有动作Schema的明确示例：calculation/hypotheses/verification是tool名，每次工具调用的action必须为`tool`。证券、财务目标、输入快照及成功条件保持；新scope/新run单独预登记，标明已用于控制问题调试、非盲样。计划SHA `f2aa680d7233df75544ae1fe00b3c2f660face5137262d3e7c1cd8485eeb3549`，目录`refined-mixed/`。

脚本`phase4_p44_refine.py`先核对原19笔已知intent/回执与报告，继承原账本、28/168000上限和上述截止，续编号20起，不重试未知结果或重置旧预算。原回执完整合法性另由独立审查使用共享`validate_model_result`确认19/19；该冻结一次性脚本不是未来批次的通用续跑接口。

新运行Parent4决策/7285Token、Financial Child2/990，**根6决策/8275Token**。动作字段全部合法、完成hypotheses，但下一轮typed上下文超出既定**12000 UTF-8字节**，在模型派发前停止：`partial/dynamic_context_budget_exceeded`，verification执行检查未完成，**定点功能0/1**。报告计算与假设由程序验证，不以其数值verified覆盖该失败。此报告无网络回放亦完全一致。

独立只读重建下一轮消息为system2970字节/user9355字节，**共12325字节、超325字节**；包含完整7事实/12Evidence。仅清空计划仍超限；缩短可信question/计划的离线控制文本实验可以容纳当前状态，但没有付费模型或真实verification/finish动作，不能当作新真实成功。前四轮消息逐字/hash重现；见`.runtime/phase4-p44-context-diagnostic.json`。追加审核确认原19+新6回执全部由共享`validate_model_result`校验合法、原19intent及deadline完全保持；见`.runtime/phase4-p44-refinement-review.json`。

额外离线机制检查使用同一002363真实冻结输入、独立scope、短可信question及合成SequenceModel动作，同默认12000字节Spec完成父6/子2动作，全部必需检查passed，最高消息11963字节；保留全部7事实/12Evidence，事实dict与原定点报告逐项完全相同，源记录ID一致，completed回放无新模型。这里只证明短控制文本下的完整机制，不是付费模型能力或新Provider认证，合成120Token/回执不计真实账本或分数。记录`.runtime/phase4-p44-public-scripted.json`；诊断中一次把run_id误作resume的调用被身份护栏拒绝，未新增模型/读源，后续正确resume验证完成。

本轮合计**25决策/38188实测暨记账Token/169502累计派发预留/unknown0/0新金融Provider调用**。累计派发预留169502另列，不能称其小于168000；当前预算记账38188在168000上限内。剩余3决策不足以从首轮重新完成混合父子任务，未继续付费、扩大预算、延长deadline或删除Evidence换取完成。原1/2及定点0/1分开保留，不能改记为2/2。

## 验收结论与下一边界

P4.4代码、两种路由、父子权限/PIT/预算/恢复和证据机制通过工程检查；真实双Child缺证据闭环通过。**完整财务混合路径的真实闭环仍未通过，P4.4完整功能验收暂不通过，不进入P4.5。** 最小剩余为新版本下明确的动作纠错反馈与能容纳该合法任务完整typed证据的上下文配置/控制文本方案，并在新的事前冻结额度内验证完成路径；不能删事实/Claim、修改旧Spec或原失败、改分母或复用过期账本。没有开展广泛质量认证、比较实验、Phase6通用压缩或新数据采集。

旧P4.3、M1及Phase3的成绩和失败记录保持。发行与本轮秘密扫描结果见STATUS及本目录`distribution/check.json`/`final-integrity.json`；未外部发布，wheel未验证。

发行实查：源码/旧证据3314文件、sdist60文件精确密钥匹配均0，禁入文件0，六个Phase4实现模块齐全；另本轮Artifact/日志精确密钥匹配0。没有将本地配置、运行目录或输入证据打入发行包。
