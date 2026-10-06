# Phase 2 任务质量进一步验收（2026-10-02）

## 当前结果

**固定 Single 的本轮任务质量代理规则验收通过：真实模型原始任务 24/25（96%），达到 ≥95%；重复重点展示修复后 25/25。** 用户随后明确回复“批准”，本轮已按原冻结内容完成恰好25次指定模型调用。不是专家盲评、全局任务成功率或供应商准确率认证；不改变固定 Single/描述性概览边界，不进入因果研究、假设、Multi 或交易。

## 用户批准后的实际结果

清单文件 SHA-256 与批准内容保持 `8f1ac80782745a13bfe60a30105b0b1421d8356a5bc1b005ecfa6959e9fd17d7`；发送前 Transport 逐字比较 messages/模型/输出上限并核对配置端点。**25 次派发、0 重试、0 模型替换、0 新金融 Provider 调用**；25/25 返回指定 `deepseek-v4-flash-0731`、stop、完整合法用量和严格 ID 选择，全部格式 verified。输入 **7075**、输出 **525**、合计 **7600 Token**，无未知用量；全批保留 Token 预留 **37155**，低于批准上限60000。

| 本轮实际检查 | 结果/证据 |
|---|---|
| 原始模型任务质量，保留全部分母 | **24/25 = 96%**；`.artifacts/phase2/task-quality-20261002/live-approved/result.json`，`.runtime/phase2-task-quality-live-approved.log` |
| 25份真实回答的独立 Fraction 及血缘复核 | **123/123 数值 Claim、263 Evidence**；`live-approved-replay/result.json` |
| 新进程恢复，Transport 禁止派发 | **25/25 报告完全一致、模型派发0、金融 Provider调用0**；`.runtime/phase2-task-quality-live-replay.log` |
| 展示层修复与已保存真实回答复测 | **25/25**，不改模型原始失败评分；修复版Markdown在 `live-approved-replay/` |
| 最终 .venv 离线回归 | **172项：160通过、12 PostgreSQL跳过**；`.runtime/phase2-task-quality-approved-offline.log` |
| 最终隔离 PostgreSQL 回归 | **172/172、0跳过**；`.runtime/phase2-task-quality-approved-postgres.log` |
| 本轮修复后的编译/依赖/发行排除 | compileall、pip check、sdist通过；46包内文件包含全部8个research模块，秘密/.runtime/.artifacts排除，源码/本轮证据与包内精确秘密匹配0；`approved-distribution-secret-check.json`及`.runtime/phase2-task-quality-approved-distribution.log`，wheel未验证 |

唯一原始质量失败是 **000016-2026-09-15**：没有可见行情，仅财务事实，模型选择归母净利润、营业收入、营业总收入；后两项同值/同期间/同单位，违反冻结的非冗余规则。请求按证据不足继续 partial，这不是错误填数或错误证券；原始失败记录不删除、不改为通过。

修复 `research/report.py`：仅在模型重点展示中合并同值/同期间/同单位的收入配对，保留第一个原始重点，显式说明“展示已合并”；不合并不同时期/不同值，也不合并恰好同值的利润或其他指标。原JSON三个选择、全部源指标和证据链不变，不产生新选择/数值，不把展示修复冒充模型进步。新增两项回归证明合并透明、原失败评分仍失败、其他不同信息保留；没有为这项修复追加模型调用。

本次适配器调用延迟最小718ms、中位1125ms、P95（nearest-rank）1360ms、最大1687ms；只属于该25次采样，不是持续SLA。主质量率为原始24/25，不把25份无网络回放或修复版渲染加入分母；满足最小代理规则不证明专家研究判断、其他域、自然语言或任意历史窗口的任务质量。

此前 50/50 固定 Runtime 检查主要证明算术与执行机制，不能回答“报告是否好读、重点是否有用”。此轮将产品表达、重点相关性与数值正确性分别计分。下述规则为透明的最低任务质量代理指标，不是专家盲评或投研判断质量认证。

## 本地质量与修复

首轮检查 50 个真实冻结报告：没有简洁概览，比例以长小数显示，金额直接以元显示，缺口以英文代码列出。按本轮要求，**0/50** 满足报告表达检查，失败逐项留存。

修复 `research/report.py` 后：新增完全由既有 Claim 生成的中文概览，明确实际观察窗口与本次窗口内最新可见报告期；比例显示百分比、金额显示元/万元/亿元；缺失行情不显示零，缺基数明确“无法计算同比”；中文解释后保留原缺口代码。每条概览引用 Claim ID，原 JSON、精确值、计算公式、原始证据及 Checkpoint 不变。展示值保留两位并明确四舍五入。

本地检查 **50/50** 通过：简洁概览、实际价格窗口、比例显示、财务期及人民币单位、缺行情不当零、缺同比说明、覆盖未认证、Claim 引用和精确 JSON 保留。使用本机原冻结 source/corpus/hash，通过当前授权 DataService 重读验证输入后渲染，不重新采集数据。

| 实际执行 | 结果/证据 |
|---|---|
| 修复前产品表达 | **0/50**；`.artifacts/phase2/task-quality-20261002/before/result.json`、逐报告 Markdown；`.runtime/phase2-task-quality-before.log` |
| 修复后产品表达 | **50/50**；`.artifacts/phase2/task-quality-20261002/after/result.json`、逐报告 Markdown；`.runtime/phase2-task-quality-after.log` |
| 新增回归 | 8 项：百分比/金额/负数展示、原报告不变、缺行情不填零、同比缺口中文、单域重点拒评分通过、重复收入检测、缺市场时允许财务重点、未知/未 verified 选择拒绝 |
| 项目 .venv 离线全量 | **170 项，158 通过、12 PostgreSQL 跳过**；`.runtime/phase2-task-quality-offline.log` |
| 隔离 PostgreSQL 全量 | **170/170 通过、0 跳过**；`.runtime/phase2-task-quality-postgres.log`，仅创建与清理 localhost 临时测试容器 |
| 最终表达与回归复测 | 明确 ROUND_HALF_UP 四舍五入、补充正负中点案例并区分显示值/原始单位后，`after-final/result.json` **50/50**；最终离线 **158 通过/12 跳过**，隔离 **170/170**；日志 `phase2-task-quality-after-final.log`、`phase2-task-quality-offline-final.log`、`phase2-task-quality-postgres-final.log` |
| 编译/依赖/发行与秘密排除 | compileall、pip check、sdist 构建通过，全部8个research模块齐备，本地凭据/.runtime/.artifacts排除，源码/新证据与包内精确秘密匹配0；证据 `.artifacts/phase2/task-quality-20261002/distribution-secret-check.json`；wheel本轮未验证 |

数值与输入仍沿用前轮 248/248 的真实固定算术核对，本轮没有重新宣称供应商准确率。评分校准专门覆盖“格式 verified 但只选行情”的答案：格式可以通过，任务相关性必须失败；收入/营业总收入同值、同单位、同期间不能重复占用两个重点。

## 冻结的真实模型验收方案

固定原 25 股全部近期行情窗口，包含银行、新上市、停牌候选、低成交量及五板块样本；没有按模型表现筛样。每个任务沿用原行情/利润快照、system cutoff 和请求；没有行情的 000016 允许只有财务重点，同时报告继续 partial。

每任务真实模型最多一次调用，只选最多三个既有 ID。冻结规则要求：

1. 指定模型严格 verified；ID 有效且不重复，没有自由正文/数字/工具请求。
2. 同时存在市场与财务事实时，重点至少各覆盖一类；缺市场不强求市场重点。
3. 同值/同期间/同单位的营业收入与营业总收入不重复占用重点。
4. 原确定性 facts 哈希保持、展示规则通过、没有新金融 Provider 调用。

“有用”仅指上述最小覆盖与非冗余规则，不把该评分称为专家金融判断。阈值沿用 ≥95%，25 例至少 24 例成功；失败/未知调用不剔除。这是已有来源的冻结透明评测，不是盲样持出集或长期 SLA。

完整拟发送 messages 与请求/事实哈希已冻结在 `.artifacts/phase2/task-quality-20261002/proposed-model-campaign.json`，文件 SHA-256 `8f1ac80782745a13bfe60a30105b0b1421d8356a5bc1b005ecfa6959e9fd17d7`。只向 `test_api.txt` 配置 HTTPS 端点使用 `deepseek-v4-flash-0731`；最多 **25 次**、全批 Token 预留上限 **60000**、每次输出上限 **384**，每次最多 30 秒网络等待，无重试/模型替换。只发送事实名称、值、单位和窗口；请求中的股票/scope/快照 ID、公告正文/标题及凭据不进入 messages。

Transport 派发前核对完整 messages、端点与模型、批次预算；Runtime 和批次两级先持久化 intent，输出目录存在即拒绝重跑。未知 Token 用量保留 None 与预留，不记为 0。

首次请求被工具自动审批在进程启动前拒绝：认为“进一步验收任务质量”不足以授权这批具体财务事实外发至配置端点。当时没有绕过拒绝、没有模型调用；随后用户明确批准此25次批次，才执行上文实际结果。此前五条事实的一次模型批准没有被自行扩大。

## 复现

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/accept_phase2_quality.py --output .artifacts/phase2/new-quality-audit
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
& ./scripts/test-postgres.ps1 -Image 57c72fd2a128
.\.venv\Scripts\python.exe scripts/accept_phase2_quality.py --verify-campaign .artifacts/phase2/task-quality-20261002/live-approved --output .artifacts/phase2/new-approved-replay
```

原数据库、源附件与 corpus 必须存在；输出目录必须不存在。本地 audit/verify-campaign 不触发模型/金融 Provider 网络。`--live` 的此25次批准已执行完毕，后续不得当成未限定重复批次授权；准备命令 `--prepare` 已执行，默认 manifest 存在时拒绝覆盖。

本轮真实批准批次及结果已完成；未来新外发仍需遵循实际批准范围。不得用本地50/50、fixture、回放或展示合并冒充新增真实模型成功。
