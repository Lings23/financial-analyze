# P1.7 行情参考与持续调用验证（2026-10-01）

**本轮取得新增证据，P1.7/Phase 1 整体仍未通过。** 原六股、两个行情窗口、三个财报期及 666 个指标单元保持；未删除缺失层、重写旧快照或引入第四个运行时数据 Provider。交易所网页/API只作独立验收参考。

## 三表持续调用

[预登记计划](../evaluation/p17_20261001_quota_plan.json) SHA-256 `9cf72da8dbc4b97c7f9564b32695e4767300b0c7dbf01f9267d4822081045458`，调用前封存六股×三表×三轮共 54 请求、2024 年报期间、五个执行/Provider 核心文件的代码哈希、首个失败停止及有限预算。利润表与扩展三表适配器使用两个 Registry、同一个 Executor，共享 tushare 限流，不分别发满配额。

- 2026-10-01 02:34:04～02:36:20 +08:00，54/54 请求取得非空事实；income/balancesheet/cashflow 各 18 次。包括 920118 的两张扩展报表，证明该样本权限和返回，不证明任意北交所证券覆盖。
- 调用起点跨度 **132.515 秒**，最小间隔 **2.5 秒**，任意 60 秒内最多 **24 次**。54 尝试、零重试、零缓存命中，业务码全部为 0。
- 54 个固定快照、事实记录 ID 和原响应哈希回放通过；采集前不可见，未授权来源不可见。每轮相同历史报告仍按各自当前捕获时刻可见。
- **只证明本次 24 次/分钟配置速率能持续工作**，不证明账号最高 80 次/分钟、多进程共享限额、长期 SLA 或三表跨日稳定性。普通 Executor/CLI 原默认速率没有由这次结果自动获得认证；使用本批验证的速率需显式配置 `ExecutionPolicy(min_interval=2.5)`。

证据：`.artifacts/p17_20261001/quota/run.json`、`replay.json`；脚本 `scripts/run_p17_quota.py --verify-only` 无网络重算。跨日三表仍列未验证，不下调原规程。

## 行情独立参考的来源与单位

从[上交所股票历史行情页](https://www.sse.com.cn/star/market/stocklist/info/index/index.shtml?COMPANY_CODE=688002)及其直接引用的[历史渲染脚本](https://www.sse.com.cn/xhtml/star/js/draw-hq.js)确认官方 `sh1/dayk` 字段：date/open/high/low/close/volume/amount。网页将原始 volume 除以 10000 显示万股、amount 除以 1 亿显示亿元，因此原 API 数值分别按股、元比较；价格保持元/股。

[深交所行情页](https://www.szse.cn/market/index.html)及[官网压缩脚本](https://res.szse.cn/modules/marketdata/index/js/index.min.js)确认日线请求 marketId=1、cycleType=32，使用官方 getHistoryData。原始 picupdata 价格顺序为开盘/收盘/最低/最高；与 picdowndata 的日期/成交量一一核验。[图表脚本](https://www.szse.cn/modules/marketdata/trend/js/kMap.min.js)的英文 Volume 单位使用 100 股，日线成交量为整数手；金额按元比较。

官网 HTML、直接引用脚本和初次发现响应保存在 `.artifacts/p17_20261001/exchange_discovery/`，每批参考请求前归档 URL、参数、有限请求数和源脚本哈希。发现接口后再冻结扩展参考清单，属于原样本的事后独立参考扩展，不能称盲样。

## 实际数值结果

| 分层 | 预登记原单元 | 已比较 | 来源精度内一致 | 缺失 |
| --- | ---: | ---: | ---: | ---: |
| 沪市三股、两个日线窗口 | 306 | 306 | 306 | 0 |
| 深市两股、两个日线窗口 | 204 | 96 | 96 | 108 |
| 北交所一股、两个日线窗口 | 102 | 0 | 0 | 102 |
| 六股三个财报期 | 54 | 48 | 48 | 6 |
| **去重汇总** | **666** | **450** | **450** | **216** |

- SSE 600000/688590/600519 各 17 个交易日，每日六字段，共 **306/306**；收盘、开盘、最高、最低容差 0.005 元/股，量/额各 0.5 股/元。源每股返回 599 行，但仅原计划窗口的字段计入比较。
- SZSE 000001/300750 默认参考只返回 2025-12-04～2026-09-30 的 201 行，原近期窗口各八个交易日，共 **96/96**，2024 窗口的 108 单元保持缺失；没有改日期、换股票或把缺失说成停牌。
- 深市首次规则把成交量参考精度错误设为股，结果 **80/96 一致，16 项不符**。整数手参考无法表达 Tushare 的零股余数。保留原规则/失败文件，另封存[来源精度修正规则](../evaluation/p17_20261001_szse_precision_rule.json)，成交量按原规程“半个来源末位单位”设 **50 股**容差；其他字段不变。重新授权读取旧 Tushare 快照、原始参考并核验后，96 项精度内一致，**66 项完全相等**。这是采集后修正规则，不是预先盲样认证或逐股精度真值。
- 48 项财务比较沿用[官方原文扩展](P17_REFERENCE_EXTENSION_20261001.md)；六项银行营业总收入仍无独立口径。原 27 项行情与新的沪市 306 项重合，去重汇总不再另加 27；旧轮 35、75 单元的结果保留原证据和日期。

汇总按原 record_id+metric 名去重，为 **402/612 行情、48/54 财务**。全字段汇总 SSE/SZSE/BSE 为 **330/111/9**；字段分母及未核对项见 `.artifacts/p17_20261001/combined-quality.json`。初次汇总把证券字符串误标为交易所分组，保留 `combined-quality-initial.json` 后修正分类；比较数量与数值没有变化。

## 封存与无网络复核

- [SSE 参考计划](../evaluation/p17_20261001_sse_reference_plan.json) SHA `9924c0f53d782e38d7a40dfcf45811009cb6b2a3dea4d5dc53e66f4d8ffd3067`；证据在 `sse_market/collection.json`、`comparison.json`。
- [SZSE 参考计划](../evaluation/p17_20261001_szse_reference_plan.json) SHA `8c69468ddf7a42e27d255ecb96fb2bd89bade68ca7137b8542a8a09346138c18`；原失败比较和精度复核分别在 `szse_market/comparison.json`、`comparison-precision.json`。精度规则 Artifact `586d4a7195a189882fa7ca793353f0d65b65d704684299ee254c5dd93cd62ff5`。
- 原快照仍为 `2b30fc0aa2d93ec968847e0092e78d3e6e64bdd3e151fc8731e8334df71c2e59`，未改任何金融记录或历史 available_at。

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe scripts/run_p17_quota.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_sse_market.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_szse_market.py --verify-only
# 上行应重现首次规则失败，退出码 2；不是当前精度复核通过的入口。
.\.venv\Scripts\python.exe scripts/check_p17_szse_precision.py
.\.venv\Scripts\python.exe scripts/check_p17_reference_extension.py --verify-only
.\.venv\Scripts\python.exe scripts/check_p17_combined_quality.py
```

本轮这些回放及 compileall 实际通过；SZSE 原规则按预期重现失败。没有改动生产模块，机制回归基线仍为上一轮隔离 PostgreSQL 104/104；没有把未重新执行的全套回归记成本轮新结果。原文及运行证据保留在忽略目录。

参考采集完成后增加 `scripts/exchange_http.py`：后续 SSE/SZSE 采集使用独立子进程，16 秒硬截止、3 MB 响应上限、固定官方 HTTPS 端点，不重定向。初轮实际使用 12 秒 socket 超时，不改写当时源码哈希或声称其已有进程硬截止。新增封装实际取得一条 SSE 参考，并在联网前拒绝三条不合规 URL；这条不计入 450 个独立比较。源字节/计划保存在 `exchange_http_check/`。

## 后续历史归档扩展

[历史归档与量额差异](P17_SZSE_ARCHIVE_20261001.md)另冻结原两股及新增八股90证券日，89成功/1失败；540字段436一致、98量额差异、6缺参考。原六股666分母累计526一致、26差异、114未验证；原450及默认日线图清单保留，不扩大容差或更改历史快照。

## 原450阶段剩余门槛

剩余 216 项不是零误差或合法空数据；还需北交所、深市较早窗口及新上市/停牌等正式抽检层。450/450 是已有参考、指定容差内的结果，不证明全市场 99.5% 或统计置信下界。真实可信公开时间与 verified_release、跨日持续配额、P1.9 三类完整实时表仍缺，因此 Phase 1 保持未通过。
