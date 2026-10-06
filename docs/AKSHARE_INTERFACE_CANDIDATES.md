# AKShare 数据接口候选清单

检索日期：2026-09-28。本清单使用本机 AKShare 1.18.97 的 `list_categories()`、`search(..., documented_only=True)` 和 `interface_info(name)` 检索，并对照 [AKShare 股票数据](https://akshare.akfamily.xyz/data/stock/stock.html)、[指数数据](https://akshare.akfamily.xyz/data/index/index.html)及[交易日历](https://akshare.akfamily.xyz/data/tool/tool.html)文档。检索层列出 27 个类别，其中 `stock` 388 个、`index` 94 个、`tool` 1 个接口。目录收录和有文档不等于网络可用、口径正确或历史版本可验证。随后对其中 15 个候选做了有界真实调用；逐项结果与历史 PIT 边界见 [AKShare 网络与 PIT 验证](AKSHARE_VALIDATION.md)。

项目的业务域为 Market、Financial、Benchmark、Announcement、News、Calculation。现有七接口只提供交易所总貌、当前行情快照及两项热度指标，尚不支撑完整业务 Tool；当前 AKShare 捕获快照也尚未映射为 `DataService` 可查询的规范化记录。

| 优先级 | 数据对象 / 业务域 | 候选接口（已用 `interface_info` 核对） | 所需参数与用途 | 接入前关键检查 |
| --- | --- | --- | --- | --- |
| P0 | 个股历史日线 / Market | `stock_zh_a_hist` | `symbol, period, start_date, end_date, adjust, timeout`；首版只取 `period="daily", adjust=""`，规范化 OHLCV、成交额和单位。`stock_zh_a_hist_tx` 仅作待验证的另一来源候选。 | 区间与上市状态、停牌、重复行、单位、全量/分页与每行实际可得时间；前后复权值不得混入未复权口径。 |
| P0 | 交易日历 / Market | `tool_trade_date_hist_sina` | 无参数，输出 `trade_date`；用于区分无交易日与缺失。 | 元数据的日期范围与文档示例不完全一致，必须核验 2026 年覆盖，且用交易所日历交叉检查。 |
| P0 | 公司行动 / Market、Calculation | `stock_dividend_cninfo`、`stock_share_change_cninfo`、`stock_allotment_cninfo` | 分红接口按 `symbol`；股本/配股接口支持证券及日期窗口。记录公告、登记、除权、支付及股本变动。 | 比例单位、拆送配、修订、实施日期与披露日期分别建模；总收益和复权价格须由可追溯输入确定性计算。 |
| P0 | 三大财务报表 / Financial | `stock_profit_sheet_by_report_em`、`stock_balance_sheet_by_report_em`、`stock_cash_flow_sheet_by_report_em` | 均按带交易所前缀的 `symbol` 返回报告期表。需要单季口径时另评估 `stock_profit_sheet_by_quarterly_em`、`stock_cash_flow_sheet_by_quarterly_em`。 | 合并/母公司、累计/单季、币种单位、空值和重复报告期；当前历史表不能证明旧版本在历史 cutoff 前公开。 |
| P0 | 原始公告索引 / Announcement、Financial | `stock_zh_a_disclosure_report_cninfo` | `symbol, market, keyword, category, start_date, end_date`；返回代码、标题、**公告时间**和链接。 | 以官方原文补齐 PDF/HTML、发布时间精度、哈希与修订版本；索引行本身不能代替披露原文。东方财富 `stock_individual_notice_report` 仅作待核对的次级目录。 |
| P1 | 指数日线 / Benchmark | `index_zh_a_hist` 或 `stock_zh_index_daily_em` | 前者按指数代码、频率和日期窗口；后者还支持交易所前缀代码。 | 明确基准、代码体系、成分口径、交易日与点位/总收益区别；两个来源不能无校验混用。 |
| P1 | 历史指数成分 / Benchmark | `index_detail_hist_cni`、`index_detail_hist_adjust_cni` | 按指数代码，分别返回带日期的历史样本/权重和调样记录。 | 样本生效日不等于当时公告公开时点；当前返回的历史表仍需版本证据。`index_stock_cons_csindex` 可作中证指数目录候选。 |
| P1 | 证券主数据 / Market | `stock_info_a_code_name`、`stock_info_sh_delist`、`stock_info_sz_delist` | 当前代码简称及沪深退市名单。 | 当前名单不可回填为历史股票池；维护证券 ID、交易所、上市退市与名称变更的有效期。 |
| P1 | 历史行业归属 / Market、Benchmark | `stock_industry_change_cninfo` 或 `stock_industry_clf_hist_sw` | 前者按证券及日期窗口返回行业变更日期；后者返回个股行业分类历史。 | 分类体系、变更生效日、披露/抓取时点和版本分别保存，避免用今日行业解释历史。 |
| P2 | 个股新闻 / News | `stock_news_em` | 按 `symbol` 返回标题、内容、发布时间、来源和链接；文档称最近 100 条。 | 覆盖不完整；需保存当次正文与来源，核验时间和修订，不能凭当前抓取重建任意历史新闻集。 |

## 接入顺序与验收边界

1. 先验证 `stock_zh_a_hist(adjust="")`、交易日历和公司行动，建立可靠的单证券日期窗口与收益计算输入。实时行情三接口的代理连接故障仍需独立排查；快照不替代历史日线。
2. 再验证三大报表与巨潮公告索引/原文，按报告期和实际披露版本建立 PIT；不得用当前历史表的行内日期倒填 `available_at`。
3. 补指数日线、历史样本、证券/行业有效期，再扩展 Benchmark 和市场对照。
4. 新闻最后接入；Calculation 由确定性代码读取已验证数据，不另找“计算结果”来源。

每个候选接口需单独记录真实调用状态、完整字段和单位、数据粒度、覆盖/截断、上游地址和协议、原文/版本证据、授权范围、捕获时间与不可变快照。通过目录检索或合成测试不能记作真实 Provider 验收。
