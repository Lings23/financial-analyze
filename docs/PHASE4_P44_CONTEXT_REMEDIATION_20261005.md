# P4.4 Context Remediation（2026-10-05）

本轮属于用户明确要求的P4.4阻塞修复，**原002363完整混合路径定点真实复测1/1通过**。没有启动完整Phase 6、P4.5、独立Router、并行、新Provider或广泛质量实验。旧P4.4原功能1/2、定点0/1及全部失败、分母、报告和25决策/38188Token账本保留，见[原验收记录](PHASE4_P44_IMPLEMENTATION_20261005.md)。新结果独立登记，不把原分数改为2/2。

## 修复范围

原`refined-mixed`运行在hypotheses后、verification前构造出system2970/user9355、合计12325 UTF-8字节，超过原12000上限325字节。此次保持原冻结Request和744字节question、输入证券/窗口/带时区cutoff/PIT/snapshot/Provider及目标，不以缩短问题或清空计划换取通过。

- 独立`dynamic-parent-domains-v2`和配置身份，程序默认`DomainParentSpec()`仍为v1；CLI `--domain-agents`新运行默认v2，原运行显式`--domain-version dynamic-parent-domains-v1`恢复。旧Single/P4.3/Child消息和身份保持。
- `dynamic_context.py`提供可逆catalog/arena/view：完整原请求、类型化Observation、Claim/Evidence保存在既有授权Checkpoint；共享scope、列定义、重复metadata、缺口代码只存一次，精确字符串表可无损展开。金融数值和引用ID保持字面值，无金额舍入、事实删减或模型摘要。
- `C:/E:/H:/O:`目录保留全部对象。模型每轮接收全部Fact/Hypothesis值和引用，历史Observation只放状态、哈希及目录关联。question/最近plan/schema控制文本只出现一次。
- 默认按当前首个未执行检查披露必要Evidence闭包：hypotheses/finish取声明假设输入，verification取所有Claim输入。模型仍选择每个业务动作；没有先执行固定工作流。可用严格`disclose`请求当前目录的1–16个已有引用，展开完整授权闭包；成功业务工具后清除额外选择。
- 披露计入原决策、工具、本地/根Token、绝对deadline/cancel与重复无进展限制；不产生业务Observation、不满足必需检查、不扩大权限。读前后及恢复重核Registry/SourceGrant、原附件和计算；目录绑定scope/run/request，历史目录只追加，恢复重建每次paid messages并核对intent/action/result。未知付费或工具结果不重发，Child旧协议不能访问父目录或spawn。

12000 UTF-8字节、本地8决策/12工具/48000记账Token/240秒、root16/18/96000及Child3/1/18000/120秒均保持。无跨运行授权缓存、LLM摘要、滑窗裁剪、向量库或Phase 6成本/P95优化目标。

## 单元与回归

最终全离线**606项：593通过、13专用PostgreSQL项跳过**；专用临时PostgreSQL完整**606/606通过、0跳过**，临时实例仅127.0.0.1并已回收。较旧542项增加64项：codec26、Context CLI5、Runtime16、动作Schema3、QA14，均为合成安全/机制检查，不充当金融真值或真实Provider验收。最终日志`.runtime/phase4-context-{offline,postgres}-complete.log`；compileall、pip check和CLI帮助检查通过。

覆盖可逆编解码、符号/缺口表/目录篡改、跨scope/run/旧哈希/未知引用、原数值/PIT/版本/权限、披露本地与根计账、重复无进展、leaf禁止披露、撤权后的读取与完成复用、cancel/deadline、历史paid wire和回执防篡改、未知结果保留预留且零重放、披露不冒充计算/假设/验证完成。

另用原真实公开冻结输入、744字节question和合成SequenceModel动作通过8-call混合闭环，全部7 Facts/12 Evidence与原语义相同，最大10238字节、完成恢复模型0调用。记录`.runtime/phase4-p44-context-synthetic-diagnostic.json`；其960合成Token不计下述真实账本/分数。

## 独立冻结与真实定点复测

正式目录`.artifacts/phase4/p44-context-20261005/`；新计划SHA：

`7abf18c9935fb07676f4bce250de0e3fe30ba7e20d10c2e85030b4c5d0b85871`

`phase4_p44_context_demo.py`在首笔外发前固定新代码、Spec/Child身份、原请求及原Evidence语义oracle、源附件/envelope、权限和首轮精确messages。每次外发重建目录及每个wire值并对照冻结源；未知结果保留预留、不自动重试。只有这一项002363混合任务；新独立campaign上限16父子决策/96000记账Token/480秒，不续用旧过期账本或延长旧deadline。Parent原局部240秒不变。

原cutoff `2026-10-04T00:00:00+08:00`、public PIT；财务2024-06-30至2025-06-30、行情2026-09-16至2026-09-24，Provider tushare，原snapshot `c6807de19b1a1b232001bae1d35ea99c1dc3ce8a22db0e265c5ddc397eb10d9c`。新输入内容ref `41b71c555bce763c3330635f6bc08b9c22b5f03a675f130b3b8725124464a496`，与原冻结内容相同，无新采集。

同一指定`deepseek-v4-flash-0731`及用户本地配置端点实际运行：Parent先financial_child，Child financial→finish，Parent market直接→calculation→hypotheses→verification→finish，最终**completed**，六项必需检查均passed。财务假设仍为`conflicted/mixed_financial_directions`；没有把原方向冲突改为支持或因果。

| 全局尝试 | 角色/动作 | 消息UTF-8字节 | 视图Facts / Evidence目录 / Evidence明细 |
|---|---|---:|---|
| 1 | Parent financial_child | 5194 | 0 / 0 / 0 |
| 2 | Child financial | 1573 | Child旧只读协议 |
| 3 | Child finish | 2128 | Child旧只读协议 |
| 4 | Parent market | 5911 | 0 / 0 / 0 |
| 5 | Parent calculation | 6348 | 0 / 0 / 0 |
| 6 | Parent hypotheses | 8636 | 7 / 12 / 4 |
| 7 | Parent verification | **10247** | **7 / 12 / 12** |
| 8 | Parent finish | 9510 | 7 / 12 / 4 |

最终报告保留原**7 Facts / 12 Evidence**：原值、单位、窗口、公式、可见时间、record/provider/version/snapshot/Artifact与假设/反证逐项一致。新run的工具调用UUID不同，仅按实际域/直读或Child来源规范化比较调用身份，并额外核验新实际父子调用与Evidence links；不放宽其他字段，不将哈希相同当作金融真值认证。最高10247低于12000，余1753字节，未删任何对象。

Parent6决策/14618实测Token，Financial Child2/990；父子共**8决策/6工具/15608实测暨记账Token/59787累计派发预留/unknown0/未结算Child0**。根完整分配预留71526另列（含Child完整18000分配），不混淆实际派发预留与记账用量。新金融Provider调用0、模型替换0、自动网络重试0。八份完整ChatResult均经共享验证器及独立campaign账本核对。此次模型无需额外disclose或typed premature finish修正，不声称真实触发了这些分支；相关边界由合成测试证明。

新report/summary另进程无网络回放**1/1完全相同**，模型/Provider0；回放同时重新核对冻结输入、权限、目录、Evidence与账本。复现（网络运行是已完成的独立一次性目录，不能重复paid run）：

```powershell
$env:PYTHONPATH='src'
.venv/Scripts/python.exe scripts/phase4_p44_context_demo.py --replay --plan-sha256 7abf18c9935fb07676f4bce250de0e3fe30ba7e20d10c2e85030b4c5d0b85871
```

实际明细见新`live/report.json`、`live/report.md`、`live/summary.json`及`.runtime/phase4-context-live-diagnostic.json`。该结果为一项非盲功能复测，不是广泛模型质量、官方财务真值、Provider历史发布准确性或成本统计认证。

## 兼容、发行与边界

旧P4.3两份、旧P4.4原两份及定点一份报告在当前Runtime保留原Spec/请求/权限回放**5/5完全相同**，首轮messages亦与原freeze/paid intent一致；模型/Provider/Checkpoint追加0、244份原/绑定文件SHA及三个SQLite行数保持。旧Domain v1缺省/显式身份与原plan一致；原completed/insufficient/partial/上下文超限状态原样保留，见`.runtime/phase4-context-legacy-replay.json`。不调用旧frozen harness.checked：当前新代码按设计不等于旧源码freeze，产品身份/恢复兼容与旧源码冻结门分开。

本地新sdist61文件，构建时源码/旧证据3321文件、包内密钥精确匹配0、禁入文件0。最终源码/文档/AGENTS共3323文件、新增Artifact/日志98文件及包内全量再次扫描匹配0，全部新Context/Runtime模块齐全；原P4.4固定SHA、代码freeze、完整8回执与7/12语义一致再次核对通过，见新目录`final-integrity.json`。密钥仅在内存受控比对、从不打印，不将本地密钥/运行目录打包。wheel未验证、未外部发布。

本轮P4.4上下文阻塞修复及原混合路径限定闭环验收通过；旧原1/2与定点0/1始终保留。P4.5和完整Phase 6未启动，不据单一原调试任务宣布广泛质量认证或自动推进下一阶段。
