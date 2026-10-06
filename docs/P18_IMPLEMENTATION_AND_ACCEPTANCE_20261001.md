# P1.8 首版实施与验收

日期：2026-10-01（Asia/Shanghai）。结论：**按用户确认的近期新闻范围，P1.8 首版通过本次冻结样本验收；Phase 1 整体验收仍未通过。** 上轮 [2026-09-30 审查](P18_ACCEPTANCE_RUN_20260930.md)保留为实现前的失败记录。

## 范围与实现

用户确认新闻只要求实际采集后可见的近期新闻，历史新闻后续扩展；来源仍为 Tushare、AKShare、CNINFO。新增 `domains.py`、`providers/tushare_domains.py`、`providers/documents.py`、`domain_cli.py`，沿用统一 DataService/Executor/Repository。`schema_v2.sql` 追加类型字段，不重写旧快照。API 原始请求参数与去密响应、公告 PDF 字节、新闻索引和原文 HTML 均内容寻址保存。AKShare 索引是解析后表，未声称保存其内部 HTTP 原响应。

新闻主体过滤发现原始关键字搜索含其他公司“600000 股”的数量匹配。新版用当前证券名称或正确交易所后缀的证券代码核对文章主体，排除侧栏匹配。v1 原始证据保留，但未确认公司归属的旧新闻不作为合格股票新闻返回。索引片段为 snippet，全文证据为原始 HTML；非排他公司提及，不能用于推断因果。

## 冻结计划与真实执行

计划：`evaluation/p18_20261001_sample_plan.json`，SHA-256：`e9019dfa93ec415a4b30932f981708d3e858b8cf2343d612090651bf1d74c77c`，先归档计划后取数。主证据：`.artifacts/p18_20261001/attempt2.json`，开始/结束为当地 2026-10-01 00:32:33–00:33:19；16 个逻辑请求、16 次尝试、0 重试，全部非空。一次小批成功不证明长期服务可用性或 80 次/分钟配额。

| 数据域 | 来源接口/路径 | 本次持久记录 | 授权 PIT 查询可见事实 |
| --- | --- | ---: | ---: |
| 交易日历 | Tushare `trade_cal`，SSE/SZSE | 24 | 24 |
| 复权因子 | Tushare `adj_factor`，600000/300750 | 17 | 17 |
| 指数日线 | Tushare `index_daily`，000300.SH | 9 | 9 |
| 月度成分权重 | Tushare `index_weight`，399300.SZ | 300 | 300 |
| 合并资产负债核心字段 | Tushare `balancesheet`，三公司 2024 年末 | 3 | 3 |
| 合并累计现金流核心字段 | Tushare `cashflow`，同上 | 6 | 3 |
| 公告原文 | CNINFO 公开索引及 PDF，000001/300122 | 13 | 13 |
| 近期新闻原文 | AKShare `stock_news_em`、当前名称表、对应原文 HTML | 6 | 6 |
| 合计 | 三源 | **378** | **375** |

三只股票各有现金流两行，指标完全相同且只差 `update_flag=0/1`。两行均不可变保存，查询按事实等价返回一行；不同金额或其他元数据仍报冲突，不猜测哪一标记代表历史新旧顺序。

末快照：`3fde25f0bf6f95182f83edb4c757230510b36ecafdacccef33b449126ef236e5`。公告包括原年度摘要及更正文件，但未凭标题自动拼接历史修订链。

## 核验结果

- PostgreSQL 持久卷 `stock-research-p17-data` 重启后，16 组请求的快照成员/哈希保持；每组采集前可见数 0、未授权来源可见数 0、错误 scope 拒绝，关联原始响应/PDF/HTML 字节哈希保持。证据 `attempt2-replay.json`。
- 三家公司 **16/16 个财务指标**与已锁定官方 PDF 一致。平安银行原文 PDF 页 122/123/134/135，浦发银行摘要页 3，宁德时代摘要页 4；人工转录并查看渲染页面，按百万元/千元转为元。参考值 `evaluation/p18_20261001_reference_values.json`，SHA-256 `9278f4196f38c4c60b48f0b0591f61a891e48079e726280e049f0a6e11455519`。参考字段在采集后选取，属于独立原文核验，不是盲样统计准确率认证。
- 日历 24 个开市标记与[上交所公告](https://www.sse.com.cn/disclosure/announcement/general/c/c_20260915_10832273.shtml)及[深交所通知](https://www.szse.cn/www/disclosure/notice/general/t20260917_622911.html)一致，通知原文另存哈希用于 QA；这些参考页未作为第四个 Runtime Provider。
- 404 个可见指标单元的归档响应映射/单位核对、资产负债及现金变动恒等式、300 成分粒度/权重和、13 PDF 与 6 HTML 证据检查全部通过。原始接口响应映射一致不等于独立金融真值一致；16 个独立财务字段之外未宣称准确率验证。证据 `attempt2-quality.json`。
- 真实 CLI 授权公告查询返回 2 条，采集前返回 0 条；不具 CNINFO 权限的正文导出被拒绝；合法 PDF 导出 SHA 与官方文件一致，已有导出禁止覆盖。证据 `attempt2-cli.json`。
- 旧 P1.7 首/末快照仍为 9/120 条，原哈希未变；新增迁移与三源数据未破坏原有记录。
- 源码发行包包含新增契约/Provider/CLI/schema_v2.sql，不包含凭据、运行目录和真实采集 Artifact；120 个源文件/文档/P1.8 证据对项目 Token 与验收库密码精确扫描，匹配 0。

## 测试与复现

最终离线回归：102 项，92 通过、10 项 PostgreSQL 测试因无测试 DSN 跳过。隔离 PostgreSQL 最终回归 **102 项全部通过、0 跳过**，含 10 项真实 PostgreSQL 集成测试；合成 fixtures 只证明机制。`compileall`、`pip check` 和 CLI `--help` 已执行。

```powershell
$env:PYTHONPATH='src'
.\scripts\start-p17-postgres.ps1
.\.venv\Scripts\python.exe scripts/run_p18_acceptance.py --label attempt2 --replay-only
.\.venv\Scripts\python.exe scripts/check_p18_quality.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p18_cli.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\scripts\test-postgres.ps1 -Image 57c72fd2a128
```

回放不重新抓取外部接口。重新采集可用新 `--label`，会使用真实配额并保留新一轮证据；已有运行文件禁止覆盖。

## 保留边界

所有真实扩展记录均为 `observed_at`，未来日历只表示已知安排。未建立 `verified_release`；采集早于报告期/交易日的历史 cutoff 无可见数据是预期保护。复权因子不直接构成总收益、月度权重不构成每日历史成员证明。首版只含财报核心字段，不等于完整报表每个附注字段；窗口覆盖仍 `not_verified`。仅验证沪深日历及当前样本证券，北交所日历/历史证券别名另需契约与真实检验。近期列表不保证整个请求窗口新闻齐全。

**P1.7 的广泛独立准确率、可信历史公开时间、持续配额，以及 P1.9 三项实时行情网络失败仍保留为 Phase 1 未完成项。** 不用本轮 P1.8 通过替代这些门槛，不启动完整 Agent Runtime。
