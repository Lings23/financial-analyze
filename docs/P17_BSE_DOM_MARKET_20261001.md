# P1.7 北交所官方日K参考补充

2026-10-01。**丰光精密原登记近期窗口8日/48字段全部在预登记精度内一致。25股行情当前合并为1944一致/72差异/462缺参考，72预期停牌缺行另列；P1.7及Phase 1仍未通过。**

## 官方路径与实际采集

实际浏览北交所[股票行情页](https://www.bse.cn/nq/quotation.html)，按丰光精密证券链接进入[官方个股页](https://www.bse.cn/products/neeq_listed_companies/company_time_sharing.html?companyCode=920510&typename=G)，页面明确公司名/代码、日K线及量额单位。选日K后，实际点击图中日期读取可见提示文本，逐日核实日期和开盘/最高/最低/收盘、成交量（万股）、成交额（万元）。没有读取图表内部JavaScript状态或猜接口参数。

页面资源目录实际列出`company_time_share.min.js`，有界公开GET初次非200，另一次User-Agent兼容试验返回302；各1尝试、0重试，无重定向跟随。两次失败清单保持，不能据此判定北交所没有历史数据。浏览器首次AX读取超时后，检查同一个已打开页面并用支持的DOM读取及图表点击；工具超时不等于供应商HTTP次数或数据为空。

本次成功证据是**限定的实际渲染提示投影**，不是原HTTP响应、全表或全市场覆盖。页面截图曾实际目视确认日K及近期时间轴；证券/date/标签/单位/提示值文本作为UTF-8投影留存。没有将当前代码下的2024图表身份当成已验证历史映射；本批仅2026窗口。

## 预登记、封存和比较

[参考计划](../evaluation/p17_20261001_bse_dom_reference_plan.json)固定原5只北交所股票、两个窗口85证券日/510字段，SHA `6a233c99345232c2adc59b8208b8f9daed7e527447c57fdc7e47bd6ba4927b7c`。本批来源是其中920510的2026-09-15、16、17、18、21、22、23、24，原样本分母不缩。9月15提示值在计划冻结前已见，明确记为发现样本，不声称盲样统计保证。

- 价格容差0.005元，量额各乘10000后容差50股/50元。规则在Tushare逐值比较前冻结；印刷末位半步不证明交易所采用四舍五入，未根据差异放大容差。
- 当地21:06:39～21:15:20逐日实际读取8条提示；每条证券/date及带时区观测时间保留。封存前投影只追加观测行，封存后固定字节、SHA和比较代码哈希，没有覆盖旧金融快照或失败记录。
- 当地21:17:32在读取Tushare比较值前封存，[投影](../evaluation/p17_20261001_bse_dom_920510_recent_projection.json)SHA与Artifact ID均为`5e632a3120bec09fe9b0ba4573877f8d5d802e629e3b93ce60a3f3dd81e80cd1`。独立scope为`p17-bse-dom-reference-20261001`。
- 从原持久库、原scope/来源授权、原固定快照和带时区cutoff通过DataService读取；每条源附件按记录归属读取并校验哈希。参考投影日期/证券唯一、8日完整、单位及价格逻辑检查通过。

| 分母 | 一致 | 差异 | 缺参考 | 已资格停牌缺行 |
| --- | ---: | ---: | ---: | ---: |
| 原登记BSE 510字段 | 48 | 0 | 462 | 0 |
| 原登记25股2550行情字段，合并归档与本次补充 | 1944 | 72 | 462 | 72 |

财务225字段仍218一致/7缺独立口径；原六股666分母仍531一致/27差异/108未验证，不能合并成全市场准确率。原1536、归档1896及BSE缺510历史报告保留。当前比较在`.artifacts/p17_20261001/bse_dom_reference/920510_recent/comparison.json`；其退出0仅代表本批48个可比较项没有超容差差异，不能代表510全部通过、整项P1.7通过或任意历史PIT覆盖。

所有Runtime来源仍AKShare/Tushare/CNINFO。官方页面仅独立QA参考；捕获时间不反填历史available_at，本轮未修改生产模块/数据值/容差，也未扩大P1.8新闻范围。

## 已执行验证与后续

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/check_p17_bse_dom_reference.py --verify-only
.\.venv\Scripts\python.exe scripts/discover_p17_bse_quotes.py --verify-only
.\.venv\Scripts\python.exe scripts/discover_p17_bse_quotes.py --browser-header --verify-only
```

数值/固定字节/授权源附件回放保持，失败清单复核保持，三QA脚本py_compile通过；本轮生产模块未变，未重跑全套unittest。此前123项隔离PostgreSQL为已执行机制基线。

下一步仍按原计划补其余4股近期窗口及5股2024窗口，共77证券日/462字段；旧窗口须核对当时证券身份。深市99量额差异（其中新增25股72）、7财务独立口径、三表跨日配额、920016上市原文及P1.9三项实时完整表等门槛保持。
