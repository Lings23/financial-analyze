# P1.7 北交所旧代码身份与财务参考

2026-10-01。**11个原缺失财务期全部取得18份CNINFO PDF，33个独立字段全部在原文精度内一致。扩大样本累计218/225财务字段一致、7项未验证，Phase 1仍未通过。** 原批次失败、空响应及各阶段比较文件保留。

## 官方身份依据

网页检索及直接读取先前失败。此次浏览器第一次创建/绑定读取超时后，检查确认同一页实际存在，继续读取该页成功；没有将超时当作成功或重复创建页面。通过实际DOM读取以下四组表格行：

| 公司 | 旧代码 | 当前代码 | 新代码生效日期 |
| --- | --- | --- | --- |
| 雷特科技 | 832110 | 920110 | 2025-10-09 |
| 丰光精密 | 430510 | 920510 | 2025-10-09 |
| 佳先股份 | 430489 | 920489 | 2025-05-06 |
| 东方碳素 | 832175 | 920175 | 2025-10-09 |

身份来自[官方对照表](https://www.bse.cn/service/code_mapping.html)，日期分别由[统一切换通知](https://www.bse.cn/important_news/200026735.html)、[六公司试点名单](https://www.bse.cn/important_news/200025487.html)及[试点上线通知](https://www.bse.cn/important_news/200025603.html)核实。不是从代码尾数或相同orgId推断身份。

实际DOM观测时间为UTC11:14:50、11:17:34、11:20:06、11:21:46；表头/四行及三个关键原文句封存在`evaluation/p17_20261001_bse_code_table_dom.json`和`p17_20261001_bse_switch_dom.json`。这是实际渲染页面的限定投影，**不是原HTTP响应字节、完整表归档或全市场历史代码数据库**。248条公司行之外的注释也在页面表格中，不将观察到的249个表格行当作249家公司。交易所仅作独立身份QA依据；金融公告Provider仍是CNINFO。

## 明确配置的身份边界

`QualifiedCNInfoIdentity`加载可信应用独立审核的SHA固定清单；不接受模型自报别名。资格SHA为`913a3a7fbd1c6889c61c1fb8c300e790d2e2422a75451af4c409d3256b8849f8`。

- 仅scope `p17-bse-qualified-reference-20261001`、四家公司、11个指定日期窗口/标题请求；orgId与实际目录映射核对。所有旧码公告必须在对应新码生效日期之前。
- 默认CNINFO Provider继续拒绝不同证券代码。显式配置后的版本为`p18-identity-1`；旧记录/默认版本不改写，无全市场自动别名或source fallback。
- 原始索引保留真实旧`secCode`。索引Artifact内附审核清单原始UTF-8及SHA、官方投影来源/观测时刻；可见记录的索引与PDF均受相同来源、scope、PIT和附件归属检查。
- 资格只建立明确证券身份关系，不证明公告历史公开版本。所有新公告保持observed_at，捕获时刻不得早于资格证据观测时刻。

## 真实采集与数值核对

冻结11项计划SHA为`1d83a1661b5bc2acb9f9b32a87dbb43d84cb6ed3cc581bfb4a060509b9bf8650`，当地19:30:14～19:30:42共11逻辑调用/11 Provider尝试、0重试/缓存，11/11非空、18份PDF。每逻辑调用包含目录、索引及PDF等多个HTTP请求，不能说11次HTTP。原始证据在`.artifacts/p17_20261001/formal/bse_qualified_references/`。

原表独立候选32项，另东方碳素年报第64页营业收入因附注换行、数值位于文本标签上方而单独抄录核实。原32项候选未覆盖；补充33项在读Tushare数值前固定。逐项审核合并利润表、元单位、年度/1–3月/1–6月累计期间、当前年度第一数值列、独立营业收入/总收入行与归母属性；附注数字不作为金额。四个代表页渲染目视：东方碳素年报64、丰光一季报14负利润、雷特半年报39、佳先年报78。渲染出现字体提示，实际页面的字段/金额/列对齐可读并已检查，不声称所有页面人工目视。

33项资格SHA为`f2a140187aff573367c72a8b3e995af42d07e3763de78bd66511cbb4f018c5cf`，新候选SHA为`45bafe750c2f9fae4f3c227434a86985452a7b470e051b5da059a439c744ab9e`。比较在`formal/financial_values/bse-qualified-reviewed/comparison.json`：33/33精度内一致，合并此前185项为218/225，按SSE/SZSE/BSE为101/72/45，按营业收入/归母/营业总收入为74/75/69。剩余7项缺独立对应印刷口径；取得PDF本身不计数值真值通过。全75个冻结财务期已有原文参考，共134份PDF（原113+瑞丰1+康佳2+本次18），代表财务页累计目视16页。

## 执行验证

- 新增四项身份安全测试；离线123项112通过/11数据库跳过，隔离PostgreSQL **123/123通过、0跳过**，含11实际数据库集成。合成身份/PDF fixture不当真实金融验证。
- 真实11组18PDF重放：旧码/官方资格清单字节/哈希、日期窗口、采集前不可见、错误来源/scope索引及PDF正文拒绝通过。
- 原180项比较在新QA脚本下重算保持；原113PDF回放及瑞丰/康佳补充结果保持。新机制未改变原DataRecord/DomainRecord序列化契约，无数据库迁移。
- 专用数据库`stock-research-p17`的命名卷`stock-research-p17-data`实际重启后，新11组18PDF及218项比较回放通过；25股75组/149源Artifact/488事实、旧113PDF与180/182/185阶段、P1.8十六组/375事实及日期案例四边界两版本全部保持。日志与重启证明见STATUS。
- 本轮源码compileall、pip check与源码发行包构建执行通过；源码包内容和凭据扫描结果见STATUS。

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/check_p17_bse_qualified_references.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_formal_financial_values.py --review evaluation/p17_20261001_bse_financial_values_review.json --verify-only
```

P1.7广泛行情独立参考、剩余财务口径、三表跨日，以及P1.9三个完整实时表仍未完成；本次身份配置不能替代这些门槛。
