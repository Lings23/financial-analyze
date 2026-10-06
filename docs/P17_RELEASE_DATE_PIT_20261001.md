# P1.7 真实报告版本的日期精度 PIT

执行日期：2026-10-01，Asia/Shanghai。**本组真实历史版本案例通过；P1.7 和 Phase 1 整体仍未通过。** 原验收规程允许仅有发布日期时保守处理；本次实现单独的 `verified_release_date`，不把日期零点写成精确发布时间。

## 来源与资格

仅核对智飞生物 `SZSE:300122` 的 2024 年年度合并利润口径。原版为[年度报告摘要](https://static.cninfo.com.cn/finalpage/2025-04-22/1223198218.PDF)，更正版金额取自[前期会计差错及报告更正公告](https://static.cninfo.com.cn/finalpage/2026-04-28/1225212850.PDF)。两份 PDF 与官方索引完整归档来自已授权 P1.8 冻结快照，资格准备及本次导入均无新增网络调用。

| 版本 | 官方索引日期 | 字段及元金额 | PDF 页码 |
| --- | --- | --- | --- |
| 原摘要 1223198218 | 2025-04-22 | 营业收入 26,069,711,361.44；归母净利润 2,018,478,513.91 | 均第 8 页，2024 年列 |
| 更正公告 1225212850 | 2026-04-28 | 营业收入 26,048,900,498.27；归母净利润 2,005,803,553.96 | 第 8 页及第 9 页，2024 年合并利润表“调整后金额”列 |

更正表“披露金额”与原摘要两值相同，形成具体版本对应；母公司利润表及 2025 年年报中的后续比较数不混入。营业总收入缺少独立合格字段，保持 NULL。本次重新核对原 PDF，纠正了早期探索值清单将更正归母净利润也标为第 8 页的引用错误：真实位置为第 9 页，旧探索证据保留。

索引 `announcementTime` 是日期零点，只用于发布日期。CNINFO 的日期、公告 ID、证券代码、附件 URL 与精确 PDF 哈希共同绑定版本；当前索引抓取时间不是历史发布时间。资格为显式人工核对的两份文件，不自动授予其他报告历史资格，不证明文件从首次发布起从未被原址替换。

资格清单 SHA-256：`48e81cd276c874f14270ed66c24dbc2a08ce660048a40818174c3882540f41e4`。

预登记 PIT 计划 SHA-256：`50864574806bd5e2c6ef7977593b9d4fd350fd1db2949ad5e805af9ff6106fc9`。资格资料位于 `.artifacts/p17_20261001/release_date`，计划位于 `evaluation/p17_20261001_release_date_plan.json`，均在新导入前冻结。

## 实现与实际读路径

`QualifiedCNInfoIncomeProvider` 从可信应用传入的资格哈希加载文件；每次导入重新检查清单/PDF/索引哈希、证券、期间、公告 ID、日期与附件 URL。限定路径、文件大小、版本数量和执行时间；这是独立的离线合格文件导入器，普通公告 Provider 和 Tushare 仍为 `observed_at`。

新字段包括 `release_date`、`release_evidence_artifact_id`、`supporting_artifact_ids`。`published_at` 必须为 NULL，`available_at` 最早为披露日次日 `00:00:00+08:00`，`retrieved_at/ingested_at` 为本次实际导入/入库时刻。资格清单、索引和 PDF 均属于记录附件；DataService 每次读取重新检查权限、可见记录及全部附件哈希。旧记录没有新字段时，序列化与 ID 保持原样；PostgreSQL JSONB 无需重写旧 payload。

本次当地 15:22:21–15:22:22，两次 DataService 导入、零重试，产生原版单独快照及含新捕获两版的追加快照，3 条物理记录对应 2 个文档版本。

| public cutoff（+08:00） | 实际结果 | 同 cutoff 的 system |
| --- | --- | --- |
| 2025-04-22 23:59:59.999999 | 0 条 | 0 条 |
| 2025-04-23 00:00:00 | 原版 | 0 条 |
| 2026-04-28 23:59:59.999999 | 原版 | 0 条 |
| 2026-04-29 00:00:00 | 更正版 | 0 条 |

全部四组通过；两份文件四字段按各自 PDF 页重查通过。未授权来源返回 0，错误 scope 拒绝，非可见/非选中版本的附件拒绝；入库前 system 不可见，入库后可见。追加后旧快照仍仅原版，精确日内首次公开时间仍未知。

原版快照：`9adbfae5c5215546ff9c382aa27eddc5a3edbbdae92ad22a00d5a1fbd2af2e71`。

追加快照：`c2716e80c4dfe082203f4f19ccaffa61622642fc75fc53e27e369bfe199ab55a`。

## 持久化与回归

- 实际重启持久容器 `stock-research-p17`，命名卷 `stock-research-p17-data`；重新连接后上述四组及哈希/授权回放通过。去密重启时间/卷名保存在 `postgres-restart.txt`。
- 原 P1.7 首/末快照 9/120 条及原 ID 保持；P1.8 attempt2 十六组回放通过，375 可见事实及观察时点限制保持。
- 最终离线 unittest：111 项，100 通过、11 PostgreSQL 项跳过；最终隔离 PostgreSQL：111 全通过，0 跳过。日志为 `.runtime/p17-release-date-final-offline.log` 和 `p17-release-date-final-postgres.log`。合成测试不计为真实金融真值。

无需网络的重放命令（先启动原持久验收库）：

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/run_p17_release_date.py --verify-only
.\.venv\Scripts\python.exe scripts/run_p17_pilot.py --replay-only
.\.venv\Scripts\python.exe scripts/run_p18_acceptance.py --label attempt2 --replay-only
```

## 未完成门槛

此结果支持明确两份文件的日期精度历史案例；不证明任意历史报告、精确日内 cutoff 或全市场版本完整性。原质量分母仍为 666 项，其中 450 在来源精度内一致、216 无独立参考；本组四字段不重复加分。北交所官方分时页本轮单次访问 HTTP 403，归档为 `.artifacts/p17_20261001/bse_discovery/page-manifest.json`，没有取得行情参考。广泛/特殊层准确率、三表跨日配额及 P1.9 三项实时全表继续验收，不能因本案例通过而宣布 Phase 1 完成。
