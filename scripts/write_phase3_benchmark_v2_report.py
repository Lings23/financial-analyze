"""Write a new durable report from frozen independent scores; never overwrite."""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.artifacts/phase3/benchmark-v2-20261004'


def read(name):
    return json.loads((OUT / name).read_bytes())


def show(value):
    return f"{value['numerator']}/{value['denominator']} = {100 * value['rate']:.2f}%" if value['rate'] is not None else 'not_assessable'


def new(name, value):
    with (OUT / name).open('x', encoding='utf8', newline='\n') as stream:
        stream.write(value)


def run():
    m, r, manifest, sem = read('metrics.json'), read('independent-review.json'), read('benchmark-manifest.json'), read('semantic-review.json')
    oracle = read('independent-oracle/deterministic-review.json')
    official = m['official_accuracy_coverage']
    task_rows = '\n'.join(f"| {t['task_id']} | {t['level']} | {'成功' if t['task_success'] else '失败'} | {len(t['units'])} | {', '.join(t['problem_classes']) or '无'} |" for t in r['tasks'])
    status = Counter(u['expected_hypothesis']['status'] for t in oracle['tasks'] for u in t['units'] if u['unit_type'] == 'hypothesis_state')
    semantic_lines = sum(t['line_count'] for t in sem['tasks'])
    added = sum(len(t['additional_claim_units']) for t in sem['tasks'])
    baseline = oracle['baseline_summary']
    manifest_sha = hashlib.sha256((OUT / 'benchmark-manifest.json').read_bytes()).hexdigest()
    outcome = '达到' if m['new_benchmark_thresholds_passed'] else '未达到'
    report = f'''# Phase 3 Benchmark v2 独立验收报告

日期：2026-10-04，Asia/Shanghai。新目录只追加结果；原 68 个任务及其评分不回写。

**本轮合法输入 Benchmark {outcome}预登记的五项质量门槛；Phase 3 完整、广泛能力认证仍未通过。** 本批是固定描述性目录、已知冻结材料上的 validation；没有独立 held-out test。官方准确性缺口、L5 单证券范围及程序预构建候选限制均保留，不能以本批成绩替代原端到端失败或开放式研究能力认证。

## 1. 新样本与输入契约

38 个新 Case：34 个 L3、4 个 L5，26 个证券。所有候选均保留，Contract Validity 为 **{show(m['benchmark_contract_validity'])}**；非法或未知输入不能部分冻结。新 Case ID、契约 v2、manifest 与原任务分离。未读取 Agent 结果决定输入合法性。

25 股预先排序后按固定九类研究主题轮转，另含六个已知非正基数的金额变化问题、两个缺去年同季度基数问题、四个原版/更正版 × public/system 事件问题、一个明确事件的 L3。包括支持、反证、冲突、合法不足、真实零行行情、版本修订、次日边界和接近 capture 的 cutoff。不是每个任务强制五类假设。

Gate 核对证券、Provider/Dataset 能力、原始附件、完整快照成员 SHA、可信 SourceGrant、scope/window、带时区 cutoff、public/system PIT、所需报告期、严格日期策略和事件/版本/真实两侧价格。授权负控 114/114：每 Case 的错误主体、错误快照及撤权均拒绝。合格零行响应必须有精确原查询及成功状态/行数/采集时间证明；不据空行情猜测停牌。

非正基数采用独立版本 `absolute_profit_change` / `profit-change/v1` 与 `single-research-v5`：本期累计合并归母净利润减上年同报告期，单位 CNY，大于零才 supported；保留负值符号，不等于百分比同比，不推断因果。原 positive-base YoY 规则和旧 v1–v4 请求/评分不改。CLI 仍默认 v4，v5 显式选择；程序默认 v3 保持兼容。

股票/基准使用冻结 exact-date only，禁止插值；因子逐日完整才计算。600301 的日期子样本不足在报告中保留，但本批没有一项必需 market_direction 检验专门测其不齐日期拒答，不能宣称覆盖了该真实压力。更广 calendar 完整性、事件类型、停牌、新上市等仍未由本批认证。

## 2. 实际执行与冻结

manifest SHA256：`{manifest_sha}`。精确 messages SHA256：`a0de0a53f361f12f009aaedbc1d6c5f5ba2e4ced430ac6d901aa14f761c52511`。前置评分协议见 `EVALUATION_PREREGISTRATION.json` 与 `SEMANTIC_JUDGE_PROTOCOL.md`，均在第一笔外发前固定。

用户明确批准这 38 次外发。模型固定 `deepseek-v4-flash-0731`、配置端点、v5 Spec、24,000 字节上下文和每任务 28,000 Token/120 秒上限；模型输出 512 Token。批次上限 38 调用、1,064,000 预留 Token、2,280 秒；实际 **38 调用、38 单次 verified、0 重试/替换、137,753 实测 Token、398,132 预留 Token、未知用量 0**。金融 Provider 新调用 0。38 原始响应、38 JSON、38 Markdown、intent/receipt/账本共 230 个文件已先冻结再评分。

冻结的原 runner 在模型运行前遇到 Tool 输出 status/warnings 缺失；新增执行适配器仅重建标准 Tool 结构。另一次 tuple/list 比较被规范化内容 SHA 替代。两次均无模型调用、无输入数值/Agent 代码改动，失败日志保留。自动审批首次拒绝未启动进程；用户随后明确批准精确清单，才执行模型调用。详情见 `EXECUTION_ADAPTER_LOG.json` 和 `MODEL_EXTERNAL_AUTHORIZATION.json`。

## 3. 独立数值及全文语义判定

独立 oracle 只读冻结原 Artifact/官方 PDF，使用标准库 Fraction 重新选取证券、字段、版本、PIT、窗口并计算，不导入 production calculation，不使用历史评分作真值。{oracle['summary']['units']} 单元包括 536 数值 Claim、47 假设状态及 5 必需锚点；1047 处 Evidence 引用逐项审计。Claim 原值、规范化、单位、期间、公式、源版本、完整输入和 cutoff 分别验证。

独立 Codex Judge 完整读取 **38 份 / {semantic_lines} 行 Markdown**，并对照原问题与原始来源核查重复展示、支持/反证、冲突/不足、样本范围、因果语言及漏项。新增可评分 Markdown Claim {added} 个；不能从 JSON 合法、completed 或 verified 自动判完成。详细判定及逐行覆盖见 `semantic-review.json` 与 `markdown-audit-inventory.json`。

Task Success 要求完整必需事实/检验、独立正确状态与支持/反证、合法预登记不足解释、全文语义正确和一次固定模型选择成功共同满足。五个检验依法 insufficient，不能提供实质数值结论；其理由分别来自合法空行情、两个非正同比基数、两个缺同期基数。另一个非正基数 Case 仍完成金额变化，但保留无行情限制。仅被预登记并由原始来源证明的缺口可作为正确响应；不是所有拒答都算成功。假设分布：supported {status['supported']}、unsupported {status['unsupported']}、conflicted {status['conflicted']}、insufficient {status['insufficient']}。

## 4. 五项门槛与必需检验

| 指标 | 实测 | 目标 | 判定 |
| --- | --- | --- | --- |
| L3 Contract-valid Task Success | {show(m['L3'])} | ≥85% | {'达到' if m['L3']['rate'] >= .85 else '未达到'} |
| L5 Contract-valid Task Success | {show(m['L5'])} | ≥85% | {'达到' if m['L5']['rate'] >= .85 else '未达到'} |
| ESR | {show(m['ESR'])} | ≥98% | {'达到' if m['ESR']['rate'] >= .98 else '未达到'} |
| Hallucination | {show(m['hallucination'])} | ≤1% | {'达到' if m['hallucination']['rate'] <= .01 else '未达到'} |
| Critical Anchor | {show(m['critical_anchor'])} | 100% | {'达到' if m['critical_anchor']['rate'] == 1 else '未达到'} |

Required-check Completion：**{show(m['required_check_completion'])}**；其中可得出实质检验结果的 decisive completion 为 **{show(m['decisive_required_check_completion'])}**，剩余 5 项是按原规则正确解释的不足。必需检验完成不是 Task Success 的替代。所有需要事件的任务都进入锚点分母，包括 4 个 L5 和 1 个 L3，不能只数已存在锚点。

ESR 按全部可评估的数值/假设/必需锚点及新增 Markdown 事实单元计分，同一登记 Claim 重复展示不重复加分；Evidence 输入展示仍核验来源。源支持 not_assessable 为 {m['not_assessable_count']}，官方参考未知另列。未知不能自动 pass 或 hallucination。

## 5. 官方准确性覆盖独立列报

536 数值 Claim occurrence 全部源支持；其中 **{official['independently_official_verified']}/536 = {official['rate']*100:.2f}%** 的全部数值输入获得对应版本官方独立核对，{official['not_assessable']} 个部分或全部 **not_assessable**。可评估子集内 {show(official['conditional_official_accuracy'])}，不能称 536 个金融事实全准确。

去重的 source-revision 字段为 **108/160 官方支持、0 矛盾、52 not_assessable**。未知原因：43 个旧期源版本未与后续比较列建立独立版本桥；2 个期间列未独立识别；3 个缺官方证券/期间/字段 locator；4 个完整标签行未唯一解析。即使供应商值等于后来重述比较值，也不能自动认定原版本准确。全部逐项源路径、字段、页面及 SHA 见 `independent-oracle/official-coverage.json`、`official-numeric-claim-coverage.json`。

这两个分母分别是 Claim occurrence 和去重官方字段，不可相加。ESR 衡量输出对合法冻结源的支持，不替代金融真值认证，也不认证独立交易所全行情准确率。

## 6. 事件研究

事件必须使用预先指定 record_id。300122 原年度摘要是 CNINFO 1223198218、披露日 2025-04-22；更正公告是 1225212850、披露日 2026-04-28。原事件 before 为 04-18..04-21、after 为 04-23..04-24；更正 before 为 04-24..04-27、after 为 04-29..04-30。版本、PDF/索引、证券及实际两侧收盘独立核对。

披露只有日期精度，published_at 未知；使用次日零点 +08:00 保守可见边界并排除披露日收盘。共同 cutoff `2026-10-02T12:38:33.220503+00:00` 为最后实际 capture 后 1 微秒；价格此前已产生，system 入库时间也已合法。接近 cutoff 的是实际采集边界，不是接近公告发生时点，不虚构日内首发时间。结果仅描述两侧观察收盘变化，不归因于公告，不自行替换事件。

## 7. 四层归因与未完成条件

| 类别 | 有该问题的 Case | 导致本批 Task Failure |
| --- | ---: | ---: |
| A Research Agent Implementation Defect | {m['failure_taxonomy']['research_agent_implementation_defect']['problem_case_count']} | {m['failure_taxonomy']['research_agent_implementation_defect']['failed_task_count']} |
| B Benchmark / StudyRequest Contract Defect | {m['failure_taxonomy']['benchmark_or_request_contract_defect']['problem_case_count']} | {m['failure_taxonomy']['benchmark_or_request_contract_defect']['failed_task_count']} |
| C Data / Evidence Insufficiency | {m['failure_taxonomy']['data_or_evidence_insufficiency']['problem_case_count']} | {m['failure_taxonomy']['data_or_evidence_insufficiency']['failed_task_count']} |
| D Intrinsic Precondition / Temporal Limitation | {m['failure_taxonomy']['intrinsic_precondition_or_temporal_impossibility']['problem_case_count']} | {m['failure_taxonomy']['intrinsic_precondition_or_temporal_impossibility']['failed_task_count']} |

C 为两份 000016 合法空行情和两个缺同期基数任务；D 为两个旧正基数同比前提不成立的任务。每项按预登记回答，不自动判失败。underspecified request 0、时间上绝对不可完成 0。这些输入条件计数不等于官方真值缺口计数：后者 394 个 Claim occurrence/52 个字段仍不能评。

**Phase 3 完整验收仍未通过。** 最小剩余质量认证条件是：预先独立封存此前未用于代码/Prompt/评分器调试的 test 集及其可信真值，具有足够的 L3 问题变化、多证券/多事件 L5 和明确合法不足/日期压力；在相应金融准确性主张范围补齐对应源版本官方参考，然后固定 Agent/规则/预算做一次独立测试。开放式问答、原文自主 Claim 提取、因果影响和自由规划没有在本批测到，若产品要宣称这些能力，须另定任务和成功标准。详见新 `REMEDIATION_RECOMMENDATIONS.md`；此处是质量认证条件，不改变当前 PLAN 的动态 M1 开发优先级。

## 8. 独立性与 QA 修正透明记录

本轮没有真正盲样：38 个全部标记 validation，independent test 0，底层金融材料曾用于开发和 QA。Case/questions 与 pre-dispatch oracle 在 Agent 结果前冻结；Judge 不参与 Agent 生成，但知晓输入契约且不是外部匿名专家。300269 roster/nonpositive 两项的编译请求/messages 相同；原 38 分母保留，实际独立消息身份仅 37，不能当作两个独立复现样本。4 个 L5 仅一个证券、两个事件、public/system 各两份。

原严格 oracle 基线永久保留：来源支持 **{baseline['supported_units']}/588**、正确必需检验 **{baseline['correct_required_checks']}/47**、可判定检验 **{baseline['decisive_correct_checks']}/42**、确定性成功候选 **{baseline['deterministic_success_candidates']}/38**。差异不是 Agent 新计算失败，而是独立 QA 误把两份全字段完全相同的原始行判为版本歧义；源-only preflight 在不读 Agent 报告时即发现，25 处 Evidence/9 Case 的完整行 revision SHA 及全部字段均同一，既无不同版本也无数值差异。

另存 `ORACLE_CORRECTION_PROTOCOL.json` 和独立补充脚本，只有≥1 个真实全行 revision 匹配且所有匹配行完全相同、字段与其他原检查都通过才接受；不同值/哈希/元数据仍失败。688184/920489 四个旧期字段使用外发前已有的官方更正/重述桥定位脚本再次独立抽取；原 parser 的换行/列标题缺陷保留，官方支持由104/160变108/160，其他52未知不变。所有588单元身份、Fraction输入/公式/期望值、Hypothesis规则/状态/反证、阈值、38任务和Agent原输出不变。原严格 QA 文件不覆盖，补充结果与最终分数分开留存；不把这个来源判定修正包装成“原 oracle 首次全通过”。

## 9. 可复现与保存检查

当前完整离线 unittest **335 项：322 通过、13 PostgreSQL skip**，新增53项为机制测试，不能当金融真值。数据库 schema 未改，本轮未新跑真实 PostgreSQL；前轮集成结果不冒称本轮结果。compileall/pip check 与 CLI v4/v5帮助检查记录独立保留。

另进程从同一原始字节重算严格 oracle：两输出逐字节一致。补充官方核对/重复行 proof/协议也逐字节一致；补充 deterministic 输出仅 fresh baseline 路径及其 lineage key 不同，38 Task、588单元、全部判断内容一致。聚合可从已封存并绑定全文 SHA 的人工语义注释重算；这不是自动重新进行语义 Judge。

最终 `verification-final.json` 核对原 4502 文件 SHA、原 manifest/报告/Review Pack、原68/952分母、所有输入/源hash、冻结生产实现/Prompt/预算、38单次调用/raw response、全Task判定和 not_assessable 未自动pass。`BENCHMARK_REVIEW_FREEZE.json` 封存本批评审文件与新增脚本版本。没有追加当前金融信息回填旧 cutoff，没有任意挑替代公告，没有按结果删任务/Claim或重试模型。

可离线重复聚合（新目录必须不存在）：

```powershell
.\\.venv\\Scripts\\python.exe scripts/phase3_benchmark_v2_review_replay.py .artifacts/phase3/benchmark-v2-20261004/replay-new-name
.\\.venv\\Scripts\\python.exe scripts/verify_phase3_benchmark_v2.py --output .artifacts/phase3/benchmark-v2-20261004/verification-new-name.json
```

官方 PDF 的重新抽取需要 pdfplumber；本轮使用已配置的 bundled Python，不依赖金融网络。严格和补充 oracle CLI 参数为 manifest、新输出目录；补充还需严格基线目录。不得重新执行 `--live`，本次38调用授权已用完。新目录路径变化可复算结果，不覆盖已封存文件。

## 10. 原冻结端到端结果保持

| 原指标 | 冻结值 |
| --- | --- |
| 合并 L3 | 12/62 |
| 原真实模型 L3 | 12/37 |
| 新 cutoff 组 | 0/25 |
| L5 | 2/6 |
| ESR | 952/952 |
| Hallucination | 0/952 |
| Critical Anchor | 2/56 |

这些是历史 Frozen End-to-End Request Success；本批是新 Case 的 Contract-valid Agent Task Success。没有合并分母、重评分旧 Case 或用新成功覆盖旧失败。

## 11. 逐任务索引

| Case ID | Level | 完整任务 | 支持检查单元 | 输入条件（不是自动失败） |
| --- | --- | --- | ---: | --- |
{task_rows}

逐单元 assessable/supported/hallucination/anchor_valid/task_success、Evidence/Source 引用及可审计判定依据见 `independent-review.json`；精确分子分母见 `metrics.json`。
'''
    remediation = '''# Benchmark v2 后续建议（独立评审后冻结）

2026-10-04。本文件是新 Benchmark 的建议，不覆盖用户修改过的原 REMEDIATION_RECOMMENDATIONS.md，不在本批直接修复或重评分。优先级针对完整质量认证；当前 PLAN 的动态 M1 开发顺序保持。

## blocker

- 在生成/调试 Agent 和评分器之外构建并封存独立 test 集，事前冻结题目、成功规则、来源版本/时刻和预算。现38题全为已知材料 validation，不能声称盲样或全局 ≥85%。原68任务和本批38个结果继续不可变。
- 对要认证的金融事实补齐对应版本官方依据。现536数值Claim只有142个全部输入可评；394个部分/全部未知，涉及52个去重字段。先解决43个旧期版本桥，再处理期间列/完整标签/独立locator；数值相等不能替代版本证据。

## high

- 新独立L5样本覆盖多个证券及事件类型，保留真实版本、日期精度和两侧已产生/可见收盘；本批只有300122的两个事件。事件原意必须明确，不能为通过率临时选公告。
- 在新批次预先加入股票/基准真实日期不齐的必需 exact-date 检验，以及合法空行情、非正基数、缺同期、冲突和关键反证。合理不足按预定行为评分，不删困难任务，也不将全部拒答记成功。
- 若需要开放式Research能力，另定自然语言解析/原文事实提取/多步证据研究的任务与判据。本批程序编译问题并预先保证候选覆盖、模型仅选ID，不能为自由研究或因果影响能力提供验收依据。

## medium

- 下一版独立oracle在看Agent前明确逻辑版本去重与物理重复的区别；保留完整行SHA、重复数及不同版本的拒绝测试。增强官方PDF完整标签、换行、期间列及更正前/后算术检查。保持本次严格基线、透明补充协议和所有历史分数。
- 独立测试增加真实权限/PIT边界和失败路径，清楚区分输入Gate拒绝与Agent读权限测试；机制fixture只能证明机制，不能扩大成金融数据准确率。
- 后续对观察价格窗口和交易日历完整性明确范围；未持有对应日历与停牌依据时只声明可见样本，不能宣称完整事件收益或停牌原因。

## low

- 下批去除重复编译问题对“独立样本数”的误导：仍保存原两项，本批报38 Case/37不同消息身份；新独立集在封存前记录重合度。
- 使用本批可重复聚合与来源重算脚本审查封存结果；保留环境缺依赖、执行适配失败及oracle初次缺陷，禁止覆盖为看似一次性全通过。
'''
    new('PHASE3_BENCHMARK_V2_REPORT.md', report)
    new('REMEDIATION_RECOMMENDATIONS.md', remediation)
    return {'report': 'PHASE3_BENCHMARK_V2_REPORT.md', 'case_count': len(r['tasks']), 'thresholds_passed': m['new_benchmark_thresholds_passed']}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False))
