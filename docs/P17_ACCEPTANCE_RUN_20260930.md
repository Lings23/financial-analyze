# P1.7 真实数据验收执行记录（2026-09-30）

后续增量见[2026-10-01 官方参考扩展](P17_REFERENCE_EXTENSION_20261001.md)：新增独立财务参考及 Provider v2 标准归档验证。本文保留原轮结果。

**判定：首轮真实小样本采集和对照通过；P1.7 整体未通过。**本次执行了预登记样本的真实 Tushare 入库、官方原文对照、PostgreSQL 重启回放及真实修订案例核查。数值抽检仅覆盖 35/666 个规范化字段单元，历史版本的准确日内公开时间和正式 `verified_release` 读路径仍未证实。35/35 不能解释为全量准确率达到 99.5%。

## 冻结范围与环境

- 预登记清单：[样本计划](../evaluation/p17_20260930_sample_plan.json)，采集前 SHA-256 `8adbc927102e6e82a5ef9c5736b92bc3757504475d3a1d5ff110f33daa268636`。沪、深、北 6 只证券，每只两个日线窗口（2024-09-18～09-30、2026-09-15～09-25）和 2024 年报至 2025 半年报的利润表窗口。智飞生物 300122 的更正链是**事后探索案例**，不纳入这 35 个预登记准确率比较单元。
- 项目 `.env` 提供 Tushare Token；没有在输出、请求清单或 Artifact 中保存 Token。专用 PostgreSQL 容器 `stock-research-p17` 只绑定 `127.0.0.1`，数据在命名卷 `stock-research-p17-data` 持久化；DSN 仅存被忽略的 `.runtime/p17-dsn.txt`。容器重启后随机映射端口改变，启动脚本已能更新本地 DSN。
- 采集 scope `p17-validation-20260930`；探索 scope `p17-revision-exploratory-20260930`。真实数据和去密响应位于被忽略的 [.artifacts/p17_20260930](../.artifacts/p17_20260930)，不进入源码发行包。完整执行机器命令见下文。

## 实际采集与质量

| 项目 | 实际结果 |
| --- | --- |
| Tushare 调用 | 18 次请求，18 次业务码 0，0 次失败或重试；2026-09-30 08:59:36～09:00:02 +08:00 约 26 秒完成。这一小批调用未触发限流，**未验证** 80 次/分钟持续配额。 |
| PostgreSQL 记录 | 最新不可变快照 `2b30fc0aa2d93ec968847e0092e78d3e6e64bdd3e151fc8731e8334df71c2e59` 含 120 条唯一记录：日线 102（6×17 个交易日），合并累计利润表 18（6×3 个报告期）。 |
| 字段与逻辑 | 666 个规范化指标单元无 null；无重复业务粒度、负成交量/额、OHLC 矛盾或记录时间顺序错误。真实上游 `income` 在 600000 的 2025H1 和 300750 的 2025Q1 各返回一组**完全相同**的重复行；规范化记录按内容 ID 去重，仍需在上游质量报告中保留这两组。 |
| 去密响应 | 每次调用保存了 API/参数、请求字段、业务码、实际上游字段及所有返回行的内容寻址 Artifact，未归档 token、`msg` 或敏感 HTTP 头。此功能目前位于验收脚本的传输包装层；常规 `ingest` 仍只归档筛选后的已知字段。 |

去密采集清单、所有请求及各快照 ID：[run.json](../.artifacts/p17_20260930/run.json)。上游两组重复与逐字段差异：[comparison.json](../.artifacts/p17_20260930/comparison.json)。

## 独立官方原文核对

PDF 通过固定官方 HTTPS URL 下载、检查 `%PDF` 与 Content-Type、保存 SHA-256，并提取文本、渲染表格页人工核对证券、期间、单位和列标题。参考值逐项转录在[真实原文值表](../evaluation/p17_20260930_reference_values.json)，SHA-256 为 `5e7d5d2709f55c7ae5dc66b3a02dd3fde508fd52befe4fc68d3a734e0f21274d`。原始 PDF、下载时间和文件哈希在[原文清单](../.artifacts/p17_20260930/references/manifest.json)。

| 官方托管原文 | PDF SHA-256 前 12 位 | 核对口径与结果 |
| --- | --- | --- |
| [上交所托管的 688590 发行文件，PDF 第 23 页](https://static.sse.com.cn/stock/disclosure/announcement/c/202508/688590_20250801_LOF8.pdf) | `42b311879a30` | 2024-09-18～09-30 九日的收盘价、成交量、成交额，共 **27/27** 精确一致。PDF 的股/元与 Tushare 手/千元规范化后相同；该 PDF 不提供开高低。 |
| [巨潮 600000 年报摘要，第 5 页](https://static.cninfo.com.cn/finalpage/2025-03-29/1222948223.PDF) | `3b536506c825` | 2024 营业收入与归母净利润，人民币百万元换算，共 **2/2**。 |
| [巨潮 000001 年报，第 16 页](https://static.cninfo.com.cn/finalpage/2025-03-15/1222806505.PDF) | `77d98b2636f3` | 2024 营业收入与归母净利润，人民币百万元换算，共 **2/2**。 |
| [巨潮 300750 年报摘要，第 4 页](https://static.cninfo.com.cn/finalpage/2025-03-15/1222806928.PDF) | `50849921257d` | 2024 营业收入与归母净利润，人民币千元换算，共 **2/2**。 |
| [巨潮 600519 年报摘要，第 4 页](https://static.cninfo.com.cn/finalpage/2025-04-03/1222993909.PDF) | `a7210a641289` | 2024 营业收入与归母净利润，人民币元，共 **2/2**。 |

合计 **35/35 个已取得独立原文且口径相同的比较单元一致**（本小样本观测匹配率 100%）；同批 **631/666 个指标单元缺独立原文对照**，包括其余证券/期间和日线开高低。不能以第三方聚合器互相比对来填补独立真值，也不能把未对照项算作正确。≥99.5% 是 `PLAN.md` 的建议目标，本次没有足够覆盖和独立抽样来正式确认它。

## PostgreSQL、PIT 与真实更正案例

- 数据库重启后，从首快照 `fbb10c631c51071b7f1778ac0a0b91ea866743fb016f664e92e9167d2da8d8bb` 重读仍为 9 条，末快照为 120 条，记录 ID/快照哈希均一致。首快照在实际捕获前的 public cutoff 可见 0 条，在入库后的 system cutoff 可见 9 条；未获 Tushare 权限的来源集合可见 0 条，错误 scope 被拒绝。真实回放结果见[replay.json](../.artifacts/p17_20260930/replay.json)。所有本批记录仍为 `observed_at`。
- 事后探索的 SZSE:300122 2024 年报：[原始年报摘要](https://static.cninfo.com.cn/finalpage/2025-04-22/1223198218.PDF) 载营业收入 26,069,711,361.44 元、归母净利润 2,018,478,513.91 元；[2026-04-28 更正公告](https://static.cninfo.com.cn/finalpage/2026-04-28/1225212850.PDF) 载更正后营业收入 26,048,900,498.27 元、归母净利润 2,005,803,553.96 元。当前 Tushare `report_type=1` 返回两条，`f_ann_date` 分别为 2025-04-22 和 2026-04-28；两版四个值与各自原文 **4/4 精确一致**，当前查询按 `revision_order=20260428` 选较新版。证据见[真实修订对照](../.artifacts/p17_20260930/revision/version_check.json)，不计入上述 35/35。
- [智飞生物 2025 年报摘要](https://static.cninfo.com.cn/finalpage/2026-04-28/1225212821.pdf) 又把 2024 年列为另一套“调整后”比较期数值。后续比较期与更正的 2024 年报数值不同，原因尚未独立核定，**未将差额误报为 Tushare 同版数值错误**。该现象说明仅凭报告期和 `ann_date` 无法判断版本。
- 巨潮公开索引可对应原始与更正公告 ID/PDF，但 `announcementTime` 对这些条目均折算为当地日期的 **00:00:00 +08:00**，不能据此认定原文实际在午夜发布。原始文件和更正公告的日期与内容版本已核实；**日内精确公开时间未核实**。Tushare 两版均在 2026-09-30 当前采集时被标为 `observed_at`，尚无真实 `verified_release` 的历史 cutoff 回放。索引与 PDF 哈希见[修订原文清单](../.artifacts/p17_20260930/revision/manifest.json)、[更正公告清单](../.artifacts/p17_20260930/revision/supplement.json)。

## 执行命令及测试

```powershell
.\scripts\start-p17-postgres.ps1
$env:PYTHONPATH = 'src'
.venv\Scripts\python.exe scripts/run_p17_pilot.py
docker restart stock-research-p17
.\scripts\start-p17-postgres.ps1  # 更新重启后的本地随机端口
.venv\Scripts\python.exe scripts/run_p17_pilot.py --replay-only
.venv\Scripts\python.exe scripts/fetch_p17_references.py
.venv\Scripts\python.exe scripts/check_p17_quality.py
.venv\Scripts\python.exe scripts/fetch_p17_revision.py
.venv\Scripts\python.exe scripts/fetch_p17_revision_supplement.py
.venv\Scripts\python.exe scripts/probe_p17_revision_tushare.py
.venv\Scripts\python.exe scripts/check_p17_revision.py
.venv\Scripts\python.exe -m unittest discover -s tests -v
.\scripts\test-postgres.ps1 -Image 57c72fd2a128
```

真实采集与 PDF 下载脚本对同名证据拒绝覆盖；重放检查可重新执行。离线测试实际 **75 项中 67 通过、8 项 PostgreSQL 按设计跳过**；独立临时 PostgreSQL 集成运行 **75 项全部通过、0 跳过**。测试日志分别见[离线日志](../.artifacts/p17_20260930/unittest.log)及[集成日志](../.artifacts/p17_20260930/postgres_tests.log)。合成测试只证明机制，不参与真实准确率。

对已有证据重新计算并核对时，运行 `scripts/check_p17_quality.py --verify-only` 和 `scripts/check_p17_revision.py --verify-only`；不会覆盖原始比较文件。

## 结论和剩余门槛

P1.7 的首轮可达性、去密留痕、真实入库、观察时点 PIT 与小样本独立数值核对有可重放证据。**P1.7 不通过整体验收**，原因是：独立真值只覆盖 35/666 个指标单元且未达到事先冻结的正式抽样规模；真实旧版与更正版虽已找到，但公开索引没有可采信的日内发布时间，且正式 Provider 仍只按当前捕获时刻可见；账号的持续配额、全市场/异常证券覆盖尚未验证。下一轮应增加交易所与公告原文覆盖，明确版本时间证据的保守粒度，再将去密完整响应归档纳入标准采集路径。P1.8/P1.9 和 Phase 1 整体验收也继续保持未通过状态。
