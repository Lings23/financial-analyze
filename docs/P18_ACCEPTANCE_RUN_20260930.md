# P1.8 数据域扩展验收记录（2026-09-30）

历史记录：本文描述实现前的审查。后续已按用户确认的近期新闻范围完成接入与真实样本核验，最新结论见 [2026-10-01 实施与验收](P18_IMPLEMENTATION_AND_ACCEPTANCE_20261001.md)；本次失败证据不改写。

**判定：P1.8 未通过。**本轮核对了 `PLAN.md` 所列的交易日历、复权、指数、资产负债表、现金流量表、官方公告和新闻适配，并复跑现有测试。已有若干接口的单次可达样本和少量公告原文；这些对象尚未形成可在 `DataService` 中按来源授权、带时区 cutoff 和不可变快照读取的正式数据域。本轮没有重新调用上述候选来源，既有网络结果按其原始日期和范围陈列，不视为 2026-09-30 的新鲜度验证。

## 判定口径

按 `PLAN.md` 的 P1.8 范围和 `CONSTRAINTS.md` 的安全约束，每个数据域需有：明确的证券/指数标识、粒度、字段、单位和口径契约；可注入且有界的 Provider；对真实响应的校验和去密原始值留痕；不可变快照；每次读取的 scope、来源权限、时区感知 public/system PIT 检查；对应的合成机制测试和真实来源样本核查。单次 API 业务码 0、当前表中出现历史日期、或公告 PDF 可下载，只证明相应的较窄事实。

代码检查：[`Dataset`](../src/stock_research/models.py) 只有 `market_daily` 和 `financial_income`；[`TushareProvider`](../src/stock_research/providers/tushare.py) 仅分支到 `daily`/`income`；[`AkShareCaptureProvider`](../src/stock_research/providers/akshare.py) 只允许先前指定的七个观察时点接口；[CLI](../src/stock_research/__main__.py) 的 `ingest/query` 数据域取值也来自这两个 `Dataset`。P1.8 的候选接口没有正式 Provider 或统一查询入口。

## 分项验收

| P1.8 对象 | 已有来源证据 | 本次判定及关键缺口 |
| --- | --- | --- |
| 交易日历 | 此前 Tushare `trade_cal` 返回 30 行；AKShare `tool_trade_date_hist_sina` 返回 8797 行，含未来排期。 | **未通过。**无日历 Dataset、交易所范围/版本契约、Provider、快照和授权 PIT 读路径；未来排期不能倒填为历史已知日历。 |
| 复权和公司行动 | 此前 Tushare `adj_factor` 返回 19 行；AKShare 分红/股本变动返回样本，配股为空表。 | **未通过。**无前/后复权、调整基准、因子有效日与公告公开时间的统一契约；未入库，空配股不证明无配股。 |
| 指数点位与成分 | 此前 Tushare `index_daily` 19 行、`index_weight` 300 行；AKShare 指数样本/调样有表，`index_zh_a_hist` 两次 `ProxyError`。 | **未通过。**无指数标识、点位/收益、权重单位与成分生效/公开版本契约；未入库或做历史授权回放。 |
| 资产负债表 | 此前 Tushare `balancesheet` 返回 1 行；AKShare 当前历史表返回 105 行。 | **未通过。**无合并/母公司、累计/单期、单位、缺失、修订版本的正式映射。AKShare 样本有 22/105 行 `UPDATE_DATE > NOTICE_DATE`，不能把当前值按旧日期倒填。 |
| 现金流量表 | 此前 Tushare `cashflow` 返回 2 行；AKShare 当前历史表返回 92 行。 | **未通过。**同样缺正式映射、单位和历史版本；AKShare 样本有 49/92 行 `UPDATE_DATE > NOTICE_DATE`。 |
| 官方公告 | 既有 AKShare 巨潮索引样本 7 行；P1.7 已取得部分巨潮/交易所 PDF 原文及 SHA-256，并核查一组原版与更正版数值。 | **未通过。**无官方公告 Provider、系统化原文/修订链快照和可授权引用读取；巨潮索引给出的 00:00 日期归一值不能证明精确日内首次公开时刻。 |
| 新闻 | 此前 AKShare `stock_news_em` 返回当前最近 10 条；Tushare `news` 两次业务码 40203；CNINFO `p_info3030` 业务码 416、VIP 权限不足。 | **未通过。**无已授权且历史覆盖可验证的官方新闻来源、原文版本归档或历史 PIT 读路径。AKShare 近期列表只证明该次可达。 |

来源样本细节与采集限制见[AKShare 网络/PIT 验证](AKSHARE_VALIDATION.md)、[三源覆盖评估](SOURCE_COVERAGE_AND_PHASE1_ACCEPTANCE.md)和[P1.7 真实数据记录](P17_ACCEPTANCE_RUN_20260930.md)。这些旧探针只保存返回行数/字段等诊断信息；合成测试及单次探针都不构成 P1.8 真实财务数值准确率验证。

## 本次实际执行

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\scripts\test-postgres.ps1 -Image 57c72fd2a128
```

- 离线测试：75 项中 67 通过，8 项因没有专用 PostgreSQL 测试 DSN 按设计跳过；日志在被忽略的 [p18-unittest-20260930.log](../.runtime/p18-unittest-20260930.log)。
- 隔离 PostgreSQL 16.14 容器：75 项全部通过、0 跳过；日志在被忽略的 [p18-postgres-tests-20260930.log](../.runtime/p18-postgres-tests-20260930.log)。它不写入 P1.7 持久验收库。
- 现有测试只涵盖已实现的两类正式 Dataset 和先前七个 AKShare 捕获接口；**没有 P1.8 数据域的 Provider、持久化、PIT 或真实值验收测试**。因此测试全绿不改变本次 P1.8 判定。

## 达成验收所需结果

先固定每个新域的字段/单位/粒度/时间版本契约，再逐域接入有界 Provider、去密留痕、不可变快照和每次读的授权/PIT 检查；对实际可用的 Tushare、AKShare、CNINFO 来源分别验证，不默认跨源同口径。交易日历、复权/公司行动、指数及三表需要冻结样本、独立原文或交易所参考和 PostgreSQL 重放；公告需原文、可信公开时间及修订链；新闻需明确来源权限与历史范围。完成每域真实样本和对应测试后再复验 P1.8，不能把未实现域计为通过。
