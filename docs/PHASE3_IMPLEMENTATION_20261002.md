# Phase 3 有界 Single Research 实施与验证

日期：2026-10-02，Asia/Shanghai。用户本轮明确要求“阅读plan和status，执行phase3”。本轮交付可运行的固定目录研究首版；原 Phase 1/2 范围、源质量缺口和历史失败保留。没有启动 Phase 4–6、Multi 或交易。

## 实际交付

新增 `research/study_contracts.py`、`study.py`、`hypotheses.py`、`verification.py` 和 `context.py`，复用既有固定 Single Runtime、Registry/Executor、PIT DataService 与追加哈希链 checkpoint。读取前保存研究计划，之后固定读取→计算→检验→综合→验证；Trace 保存检验与验证回执。无数据库迁移或自动采集。

五类假设为端点复权因子影响、同日期基准方向、同报告期收入/利润同比均下降、同报告期正利润负经营现金流和合格披露锚点前后收盘观察。每项输出明确规则、所需证据、Claim/反证、supported/unsupported/conflicted/insufficient 及缺口；supported 仅表示描述性规则成立。未把缺信息当反证，也不作唯一原因、舞弊、偿债或买卖结论。

事件来源必须是当前授权/PIT 可见的显式记录。普通 observed_at 公告/新闻缺合格首次公开时间，不能据捕获、标题或 source_time 升级。合格 verified_release 精确时点按中国市场15:00日频收盘划分；verified_release_date 使用次日保守边界并排除披露日事前收盘。缺任一侧实际有效价格时不生成事件价格 Claim；派生可用时点不早于所有价格与事件锚点。这个观察统计不是因果事件影响估计。

独立 Fraction 校验器不调用生产 Decimal 算子。它从授权固定输入核对完整预期 Claim 集、数值容差（身份值要求精确相等）、单位、公式、窗口、血缘、原始/规范化值、版本、来源、快照和 public/system 时间边界。即使伪造者重新计算 Claim 哈希，错误数值或遗漏仍拒绝。最终发布和完成报告回放都校验，恢复仍验证附件、来源/工具权限和原预算。

模型只返回已有事实/假设 ID，不能修改检验状态。上下文保留显式证券/cutoff/PIT和精确数值/单位/口径/时间，以及本地 Evidence 和源版本哈希引用；源标题/正文与来源控制的标识字符串不成为指令。超过无损字节预算时不派发模型、不丢 Claim。默认8工具/120秒/16000 Token保守预留/512输出/12000字节上下文，最多一次指定模型请求，失败/未知结果不重发。

CLI 新增 `research --workflow research` 和 `--preview-model`。后者只在本地写精确 outbound messages，和 `--with-model` 互斥。Markdown 前置检验和中文缺口，JSON保留全部精确值与证据。执行完成且所选检验证据齐备可为 completed；证据不足为 partial，并保留 research_status，CLI返回2。

## 已执行验证

| 范围 | 实际结果 | 证据和限制 |
|---|---|---|
| 最新完整离线 unittest | 196项，183通过、13专用数据库项跳过 | `.runtime/phase3-offline-final3.log`；跳过不是通过 |
| 最新隔离 PostgreSQL 完整回归 | **196/196通过，0跳过** | `.runtime/phase3-postgres-final.log`；使用已有镜像57c72fd2a128、新建127.0.0.1临时隔离容器，测试后回收；含实际研究日期锚点跨Repository持久回放 |
| 预写合成L3/L5 | 22/22；L3 16/16、L5 6/6；44个预写数值检查、197 Evidence、22状态检查、22精确回放 | `evaluation/phase3_cases.json` SHA c61d54940192401f80aac5c383d0968e9d15cc493e38cf56406d651986c37b67；`.artifacts/phase3/synthetic-final/result.json`；fixture模型，不能计金融真值或真实模型质量 |
| 真实既有行情/利润快照 | 50/50离线复核；248 Claim、563 Evidence、250假设状态；回放/撤权/采集前不可见通过 | `evaluation/phase3_real_cases_20261002.json` SHA 6b3bbe510f9fc6c10ff01be45b49061b8ffc354ed289baef8c91a3ebc8cb46a8；`.artifacts/phase3/real-initial/result.json`；五类检验均缺必需扩展输入，250次证据不足不计实质研究成功 |
| 真实合格历史日期锚点 | 6/6边界复核、4次合格锚点、8 Claim/12 Evidence；原版/更正、public/system、撤权及回放通过 | `evaluation/phase3_event_cases_20261002.json` SHA 6d8463dde66511841b840361efdddaa0f3f42f63f139955636dc1612f03d3fb2；`.artifacts/phase3/event-initial/result.json`；无对应行情，事件价格统计未生成 |

新增24项测试覆盖请求与权限、时间锚点/15:00边界/日期精度、方向冲突/现金流期间不匹配、无损上下文超限、文档注入隔离、非法模型ID/文字/重复键、独立重算拒绝、完成恢复撤权/附件篡改、未知付费结果、过期恢复不发布缓存事实、空报告不算成功、CLI预览/重复键/禁止覆盖及专用PostgreSQL持久回放。早期19项新增测试中2项在清理阶段因测试自身SQLite连接未关闭失败；业务断言通过，显式关闭连接后回归通过，初始日志保留。复权判定使用源因子的精确值，防止两个派生比例四舍五入相等掩盖端点因子变化。

本轮模型网络调用0、金融Provider网络调用0。真实数据只读原持久验收库；没有变更快照、原始响应、资格文件、源准确率分母或Phase2已批准的模型结果。PostgreSQL隔离测试只使用本机临时容器与合成fixture，不算真实供应商联调。

实际CLI `--workflow research --preview-model` 已执行，输出`.artifacts/phase3/cli-example/report.md`与`report.json`、`model-messages.json`；模型disabled、3次本地工具、0模型尝试/0Token预留/0金融Provider网络调用。证据不足状态partial，实际退出2，日志`.runtime/phase3-cli-example.log`。compileall、pip check和CLI帮助通过。

sdist构建及内容检查通过：51包内文件、5个新增Phase3模块齐备、本地密钥及运行目录排除；当次源码/证据468文件与包内精确模型Key/Tushare Token/验收库密码匹配0。证据`.artifacts/phase3/distribution-final/check.json`和`.runtime/phase3-distribution-final.log`；wheel未验证。最终文档与CLI输出后再扫描472文件，匹配0，证据`.runtime/phase3-final-secret-scan.json`。扫描不输出秘密内容。

## 可运行示例

- 当前真实CLI单股部分研究：`.artifacts/phase3/cli-example/report.md`，对应精确JSON同目录同名。原50任务首次展示`.artifacts/phase3/real-initial/601009-2024-09-18.md`保留，不覆盖旧运行证据。
- 真实历史更正披露锚点：`.artifacts/phase3/event-initial/public-boundary-4.md`，清楚显示缺行情及日期精度。
- 精确模型预览：`.artifacts/phase3/real-initial/example-model-messages.json`。只保存在本机，未外发。

复现命令见README。所有实验输出选新目录，拒绝覆盖已有证据。

## 未认证范围

本轮可验证固定 Single Research 首版运行、安全机制与缺证据边界；广泛Phase3的L3/L5 Success≥85%、ESR≥98%、Hallucination≤1%、关键金融事实/事件锚点全覆盖仍没有独立真实专家任务集认证。不用零自由生成、合成通过或保守拒答替代这些指标。

待扩展包括真实对齐行情的事件研究质量、公告/新闻正文事实提取和原文位置、自由自然语言/假设提出、行业/估值/流动性等目录、真实指定模型质量批次、盲评与统计覆盖。不会在本轮自行扩大付费外发批次或启动Multi；原Phase1量额差异/历史覆盖与Phase2广泛质量缺口继续有效。
