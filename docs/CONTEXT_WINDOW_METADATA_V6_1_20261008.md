# v6.1 窗口元数据精确去重与 Token 对照

日期：2026-10-08（Asia/Shanghai）。用户授权优化 v6 Token 开销、去重逻辑并检查 v5 元数据编码；本会话全部真实外发已有用户授权。本包只做显式最小版本与独立有界同案例验收，不进入 W3 或领域 Child 分析实施。

## 问题与版本边界

原 v6 两旧案例四运行质量通过，但实际整任务 Token 32118→38789，增加 20.77%；同状态十份完整 Parent 输入 86495→100561 bytes。实际 context_read 为 0，每 Parent 仍 5 次决策，Child input/output 相同；增量来自 Parent 窗口表示，不归因于新读页或额外 Child 调用。原结果与所有付费原件保留，详见[原 v6 记录](CONTEXT_WINDOW_V6_20261007.md)。

新增显式 `dynamic-parent-parallel-v6.1`，消息编码为 `dynamic-context-window/v2` / `exact_window_metadata/v1`。原 v6/window-v1 和 v5/disclosure-view-v2 均保留；默认仍原版。v6.1 的上下文读取仍只用 context_read，不与 disclose 混用；原 tool/parallel/finish 业务动作保持。旧 v6 原件保持；v6.1 沿用 descriptor、selection、cursor 的 schema、成员和绑定/coverage 规则，以新实际 render 生成自己的 dispatch/window/cursor 身份，短表索引不成为身份。完整 catalog、window_store、audit/brief、12000 UTF-8 bytes 和原 verifier 保持。

## v5 编码核查

只读检查 `dynamic_context_metadata.py`：v5 继承固定元数据槽位的符号表、重复完整列表表与固定列编码，并另加完整 revision digest 表。固定文本槽位可以用裸整数引用 `symbols`，列表引用为 `{"l":i}`，revision 引用为 `{"h":i}`；整数只在已知元数据位置解释，不改变金融 value 单元。symbols/list 条目需重复且有局部字节收益，list-table 方案与不使用列表表的 metadata 表示比较后选择；v5 没有整份 wrapper 对原 wire 的全局 literal fallback。完整 revision digest 表保留所有非 null revision，不受重复或收益门槛限制。排序、完整字符串、数组顺序、空/null、数值和原 schema 严格恢复，bool/越界/重复/乱序/未知字段/非 canonical 编码拒绝。

v6 的窗口 schema 与 v5 披露 schema 不同，原 v6 只复用了 revision 去重，没有完整应用上述元数据 codec。直接把 v5 decoder 套到 window-v1 会混淆字段与索引。本包保持旧 v5 文件和旧付费 wire 不变，给窗口建立独立、可精确回解的表示。

## 去重实现

纯 `context_window_metadata.py` 在当前消息内使用排序唯一 `symbols`、盈利的完整 `list_table` 和白名单 `layouts`。引用分别为 `{"s":i}`、`{"l":i}`、`{"r":layout_index,"v":[完整单元]}`；列名可在同一 symbols 内精确去重。采用显式标签以保留窗口中原整数索引/数量/路径的含义，所有索引拒绝 bool 和悬空引用。

只压缩精确重复元数据及重复记录字段名；Fact 金融 value 和完整 O/C/E/H scalar atom 值保持 literal。完整页 atom、成员、顺序、start/end、content_hash、next_cursor、selection、range、required checks 与所有身份精确恢复。decoder 先校验白名单和原 window-v1，再 canonical 重编码核对；不能授予权限、制造执行进度或满足 verification。收益不足时返回完整 literal window-v1，不强制发送更大的 wrapper。compiler-only 空页头部模式不能作为正式已付费窗口解码，正式窗口必须有 window_ref。

v6.1 使用独立短 system，完整保留 v6 的任务/授权/Child/工具依赖/原 finish 与实际 verification/工作集读取规则，并解释当前消息 codec。旧 v6 system 字节保持。

## 装载、身份和去重进度

窗口先按旧 v6 literal envelope 选择工作集，再发送精确编码 wire，避免压缩后的空余容量被自动填页吞掉节省。实际大小与旧 envelope 大小同时参与 12000 gate；实际 encoded render 仍生成 dispatch/window 身份、付费消息 SHA 和读取 cursor。只有类型化 minimum-view 超限才允许 compact-capacity fallback，不改变页事实或门槛，不用 telemetry 作路由或调参。

原成员 coverage 去重保留：读取精确成员与原对象版本绑定；相同页不算进展，不自动完成重复动作。业务去重、Provider 在途合并和 metadata 表去重分属原机制；本包不缓存授权、不跨消息复用表索引、不取消逻辑调用计账。完整 state 与页回执仍按原 Checkpoint 原子提交、恢复与撤权核对，未知已付费请求不重发。

## 验证与冻结

最终完整离线 **1036 项 / 1022 通过 / 14 数据库跳过，0 失败，1140.132 秒**。71 份代码和 86 份测试与运行开始 SHA 一致，gate `.runtime/context-v6.1-offline-gate-20261008.json` 绑定日志、源码、测试与独立 DB 结果。新增 codec17/协议16/Runtime14/harness7 共54项全部通过；首轮 Runtime14/14（94.624秒）、codec17+原window19合并36/36及最终harness7/7（49.983秒）日志分别保留。仅是合成机制测试，不作金融真实准确性或 live Provider 验证。

初始只读 probe 保留：十份同 raw wire 100561→98220 bytes，aggregate 降低但 before_sources/calculation 因 system 固定说明增长，不满足每阶段不增 gate。短 system 为 2589 bytes（旧 v6 为 2599），最终 probe 100561→94540 bytes，少 6021（5.99%），每阶段不增、同页选择且实际重编工作集无额外填页；字节不能冒充实际 Token。原同 raw codec-only 测量使用原 v6 system，100561→94620 bytes（少 5941，5.91%）；完整 context 53067→47126 bytes，before_sources literal fallback，其他阶段减少。这也不是新模型实测。

专用临时 PostgreSQL 的四项新机制 4/4、0 跳过（73.151 秒）通过，容器已停止并自动删除，日志 `.runtime/context-v6.1-postgres-20261008.log`。首次完整回归在报告语义复核发现继承旧 harness 的“新披露不可逆”标签不适用于本包 exact codec，主动中止并保留 `.runtime/context-v6.1-offline-interrupted-label-review-20261008.log`；修正标签并更新 SHA/probe 后重新从冻结代码执行完整回归，不把中止当通过。

已冻结两已有 case（603207、688184）各 v6 baseline / v6.1 candidate，四个新 run identity，Child 显式 v3；独立 64 父子决策 / 384000 记账 Token / 1800 秒 campaign，原局部与根预算保持。计划 SHA `62ad575421aa605e67449aac03719de603ee1a9437703640b464efa09cb92e08`。历史 **35/35** 零模型/Provider/Checkpoint 追加回放，旧 v6 原件全量哈希纳入历史保护。最终 freeze 使用上述独立离线 gate、当前 code/test SHA 与 `.runtime/context-v6.1-byte-probe-final2-20261008.json` 十份旧 v6 paid 状态精确回解 probe，每阶段同 raw 输入不增且 aggregate 降低；初始失败及修正标签前的 final probe 原件保留。

真实验收必须另核完整业务质量、全部实际工具检查、原全量 verification、权限/PIT/快照/源/血缘/根账本、真实 wire 与 Checkpoint、双 Child I/O 重叠及零追加恢复。只有全部质量通过且实际整任务 Parent+Child known/accounted Token 均降低才可声明本次 Token 收益；未知 usage、外部失败、额外调用及全部历史分母原样保留。不扩大样本、额度或自动重试。

真实 context_read/超限分页仍须实际模型读取证据；没有这类证据时保持原未验证限制。小样本非盲同案例结果不代表统计/P95/SLA/其他任务保证；单价与账单未知时金额保持未知。

## 真实对照与只读收口

本包真实 **4/4 质量通过、4/4 零追加回放一致**：603207 两版 completed、7 Facts/12 Evidence；688184 两版合法 insufficient、6 Facts/12 Evidence，原非正基数与假设不足保留。20 项必需业务检查全部实际满足，4 次 verification 实际执行，完整 Fact/Claim/Evidence/Hypothesis/缺口/血缘与同源 oracle 保持，双 Child 实际 I/O 重叠 4/4。独立实际审计 **12 条 run 链 / 360 Checkpoint 行 / 36 paid 状态 / 4 verification 回执**，源/权限/PIT/快照/账本和 immutable live SHA 均一致。

| 实测指标 | v6 baseline | v6.1 candidate | candidate − baseline |
|---|---:|---:|---:|
| 整任务 input Token | 38457 | 38030 | −427 |
| 整任务 output Token | 435 | 501 | +66 |
| 整任务 total/记账 Token | 38892 | 38531 | **−361（−0.9282%）** |
| Parent total Token | 32707 | 32346 | −361 |
| 两 Child total Token | 6185 | 6185 | 0 |
| Runtime wall ms | 43719 | 45985 | +2266 |
| 模型 I/O union ms | 19487 | 20147 | +660 |
| Checkpoint DB bytes | 13484032 | 13942784 | +458752 |

实际整任务包括 Parent 与两 Child；每 Parent 仍 5 次决策，Child input/output 逐域相同，Parent input 少427、output 多66。全 campaign **36 paid 决策 / 28 根工具 / 77423 known 与 accounted Token / unknown0 / 新金融 Provider 网络0**。累计 dispatch 预留288830、根累计预留364974与实际 Token 分列。只有本次限定样本总 Token 节省得到证据；没有证明延迟、存储或金额改善，不声明统计/P95优势。

候选十份实际 paid 状态同 raw v6 反事实完整 system+user **100834→94813 bytes，少6021（5.9712%）**，各阶段均减少、exact decode10/10、compiled page selections 全同。最高实际模型输入11753/12000（包含 baseline），完整 audit 留服务侧。与事前旧 v6 paid probe 的100561→94540分列，不用不同 run/plan 的字节投影充当实际 Token。元数据包的标签/表和编码说明本身也有 Token 开销，字节降幅与模型 Token 降幅不等；未对每个字符提供未经测量的 Token 归因。

实际 **context_read 回执0**，没有新合法真实超限材料，真实读取/超限分页恢复仍未验证；自动阶段窗口更新不冒称真实分页。四槽全部使用，独立新任务0、真实失败0、付费追加0，不扩大范围或额度。决定 `limited_explicit_exact_window_metadata_token_optimization_accepted`，只接受显式 v6.1 精确表示与本包小幅实际总 Token 节省；默认、旧v5/v6/12000/原限制保持，结束本包，不进入W3。

正式回放 `.runtime/context-v6.1-replay-20261008.json`，实际审计 `.runtime/context-v6.1-actual-audit-20261008.json`，独立指标 `.runtime/context-v6.1-metrics-20261008.json`。首次审计与同 run 回放并行被 RunLock 互斥拒绝，保留通用安全错误日志；诊断和正式顺序审计随后通过，零模型/Provider/Checkpoint追加，没有改冻结代码或付费原件。原 immutable live summary 的 pending 决定不回写，最终决定保存在独立 acceptance 索引。

独立直接只读收据复核 `.runtime/context-v6.1-independent-receipts-20261008.json` 再核36paid、12链/360行、全部角色实际usage与同源质量，无Runtime/RunLock/模型/追加。首次QA reader错误假设所有Child report都有domain，诊断保留后改从权威state.spec_version确定角色；只修改未冻结只读QA helper，不改业务代码或原件。

交付初检684文件：精确实际密钥匹配0、秘密文件混入0；71冻结代码/86测试及全部历史/live SHA保持。独立索引 `.artifacts/context-window-optimized/metadata-v6.1-20261008/acceptance-20261008.json` SHA `e51d731860497da1ad07d77327739442b9449b179bf88bbc37ccb02c8f8ab13d` 只引用原plan/Trace/gate/回放/audit/独立收据/metrics/完整性证据，不回写immutable summary。最终文档与索引完成后的只读复检另存 `.runtime/context-v6.1-closeout-integrity-20261008.json`。

## 可复现入口

`scripts/context_window_optimized_acceptance.py` 使用独立私有旧 harness 实例，复用原授权 envelope、冻结 source oracle、账本和 Trace 检查；旧脚本不修改。新目录为 `.artifacts/context-window-optimized/metadata-v6.1-20261008`。历史和新付费 wire/checkpoint 不改写，最终决定保存独立 acceptance 索引。

显式运行入口：`--parallel-domains --parallel-version dynamic-parent-parallel-v6.1 --child-protocol-version v3`。离线全套为 `PYTHONPATH=src python -m unittest discover -s tests -v`。最终事实与 [STATUS](STATUS.md) 同步。
