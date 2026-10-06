from html import escape
from decimal import Decimal, localcontext, ROUND_HALF_UP
import json


LABELS = {
    "observed_price_change": "观察区间未复权价格变化",
    "observed_max_drawdown": "已观察收盘价最大回撤（未复权）",
    "factor_adjusted_price_change": "因子调整价格变化（非总收益）",
    "benchmark_price_change": "同日期基准价格变化",
    "price_change_difference": "未复权价格变化与基准之差（非 Alpha）",
    "event_observed_price_change": "合格披露锚点前后观察价格变化（非因果影响）",
    "revenue_yoy": "同报告期营业收入同比",
    "net_income_parent_yoy": "同报告期归母净利润同比",
    "financial_income.revenue": "最新可见报告期营业收入（累计）",
    "financial_income.total_revenue": "最新可见报告期营业总收入（累计）",
    "financial_income.net_income_parent": "最新可见报告期归母净利润（累计）",
    "financial_income.absolute_profit_change": "同报告期归母净利润金额变化（非百分比同比）",
    "financial_balance.total_assets": "最新可见报告期总资产",
    "financial_balance.total_liabilities": "最新可见报告期总负债",
    "financial_balance.total_equity": "最新可见报告期所有者权益",
    "financial_balance.equity_parent": "最新可见报告期归母权益",
    "financial_balance.monetary_funds": "最新可见报告期货币资金",
    "financial_cashflow.operating_cashflow": "最新可见报告期经营现金流净额（累计）",
    "financial_cashflow.investing_cashflow": "最新可见报告期投资现金流净额（累计）",
    "financial_cashflow.financing_cashflow": "最新可见报告期筹资现金流净额（累计）",
    "financial_cashflow.cash_net_change": "最新可见报告期现金净增加额（累计）",
    "financial_cashflow.cash_begin": "最新可见报告期现金期初余额",
    "financial_cashflow.cash_end": "最新可见报告期现金期末余额",
}

DATA_LABELS = {"market_daily": "股票日线", "financial_income": "利润表", "financial_balance": "资产负债表",
               "financial_cashflow": "现金流量表", "index_daily": "基准日线", "adjustment_factor": "复权因子",
               "trade_calendar": "交易日历", "announcement": "公告", "news_recent": "近期新闻",
               "revenue": "营业收入", "net_income_parent": "归母净利润"}
GAP_LABELS = {"coverage_not_verified": "数据覆盖尚未认证", "historical_release_not_verified": "采集时刻可见，未证明历史版本的公开时间",
              "calendar_not_supplied": "未提供交易日历，无法核实窗口内交易日是否齐全",
              "requested_boundary_not_observed": "请求窗口边界没有观察值，价格统计仅使用实际可见的首末日期",
              "yoy_prior_year_period_not_visible": "缺少上年同报告期基数，无法计算同比",
              "yoy_missing_or_nonpositive_base": "同比输入缺失或基数非正，无法计算同比",
              "at_least_two_visible_closes_required": "可见收盘价不足两条，无法计算价格变化或回撤",
              "missing_or_nonpositive_close": "收盘价缺失或非正，无法计算价格变化或回撤",
              "no_visible_financial_period": "没有可见财务报告期", "no_visible_data": "没有可见数据",
              "empty_response_coverage_unknown": "源响应为空，覆盖未知",
              "exact_trading_date_alignment_required": "基准与股票交易日期未完全对齐，未计算基准比较",
              "missing_or_invalid_aligned_factor": "对齐的复权因子缺失或无效，未计算因子调整变化",
              "calendar_alignment_not_verified": "日历与观察行情未能对齐，覆盖尚未认证",
              "calculation_not_completed": "计算尚未完成"}


def display_value(fact):
    """Presentation only: exact normalized Claim values remain in JSON/evidence."""
    value = Decimal(fact['value'])
    with localcontext() as ctx:
        ctx.prec = max(34, len(value.as_tuple().digits) + abs(value.adjusted()) + 8)
        ctx.rounding = ROUND_HALF_UP
        if fact['unit'] == 'ratio':
            return f"{value * 100:.2f}%"
        if fact['unit'] == 'CNY':
            divisor, unit = (Decimal('100000000'), '亿元') if abs(value) >= 100000000 else (
                (Decimal('10000'), '万元') if abs(value) >= 10000 else (Decimal(1), '元'))
            return f"{value / divisor:,.2f} {unit}"
    return fact['value'] + ' ' + fact['unit']


def gap_text(gap):
    parts = gap.split(':')
    domain, reason = (parts[0], ':'.join(parts[1:])) if len(parts) > 1 else ('', gap)
    if reason.startswith('missing:'):
        description = '字段缺失：' + reason.split(':', 1)[1] + '，未填零'
    else:
        description = GAP_LABELS.get(reason, '来源提示：' + reason)
    return (DATA_LABELS.get(domain, domain) + '：' if domain else '') + description


def overview(report):
    facts = {f['name']: f for f in report['facts']}
    lines = ['## 概览', '', '数据覆盖尚未认证；以下结论只针对本次请求的可见数据。显示值四舍五入到两位，精确值及口径保留在 JSON 和证据表。', '']
    price = facts.get('observed_price_change')
    if price:
        lines.append(f"- 实际观察区间 {price['window'][0]} → {price['window'][-1]}，未复权价格变化 {display_value(price)}；引用 `{price['id']}`。")
        drawdown = facts.get('observed_max_drawdown')
        if drawdown:
            lines.append(f"- 同一观察样本的最大收盘回撤 {display_value(drawdown)}；引用 `{drawdown['id']}`。")
    else:
        lines.append('- 可见有效收盘价不足，无法计算价格变化；没有将缺失行情当作零。')
    for name in ('financial_income.revenue', 'financial_income.net_income_parent'):
        fact = facts.get(name)
        if fact:
            label = LABELS[name].removeprefix('最新可见报告期')
            lines.append(f"- 本次窗口内最新可见财报（{fact['window'][-1]}）：{label} {display_value(fact)}；引用 `{fact['id']}`。")
    for gap in report['gaps']:
        if 'requested_boundary_not_observed' in gap or 'yoy_' in gap:
            lines.append('- ' + gap_text(gap) + '。')
    return lines + ['']


def displayed_highlights(report):
    """Merge only equal income aliases in presentation; retain raw model choice in JSON."""
    facts = {f['id']: f for f in report['facts']}
    shown, merged = [], False
    revenue_names = {'financial_income.revenue', 'financial_income.total_revenue'}
    for fid in report['model'].get('highlights', []):
        fact = facts[fid]
        redundant = any({fact['name'], prior['name']} == revenue_names
                        and Decimal(fact['value']) == Decimal(prior['value'])
                        and fact['unit'] == prior['unit'] and fact['window'] == prior['window'] for prior in shown)
        if redundant:
            merged = True
        else:
            shown.append(fact)
    return shown, merged


def study_supplements(report):
    """Publish omitted existing claims separately, without changing model selections."""
    if (report.get('schema') != 'single-research/v1' or report['model']['status'] != 'verified'
            or report['verification']['status'] != 'verified'):
        return []
    facts = {f['id']: f for f in report['facts']}
    shown, _ = displayed_highlights(report)
    selected = {f['id'] for f in shown}
    added = []
    def add(fid):
        if fid not in selected:
            added.append(facts[fid])
            selected.add(fid)
    # Keep both the supporting and contradicting inputs of each chosen decisive test.
    for h in report['hypotheses']:
        if h['id'] in report['model'].get('hypotheses', []) and h['status'] != 'insufficient':
            for fid in h['claim_ids']:
                add(fid)
    market = lambda n: n.startswith('observed_') or n in {
        'factor_adjusted_price_change', 'benchmark_price_change', 'price_change_difference', 'event_observed_price_change'}
    financial = lambda n: n.startswith('financial_') or n.endswith('_yoy')
    present = shown + added
    if not any(market(f['name']) for f in present):
        candidates = [f for f in report['facts'] if market(f['name'])]
        if candidates:
            add(candidates[0]['id'])
    if not any(financial(f['name']) for f in present):
        by_name = {f['name']: f for f in report['facts']}
        current = [by_name[n] for n in ('financial_income.revenue', 'financial_income.net_income_parent') if n in by_name]
        for fact in current or [f for f in report['facts'] if financial(f['name'])][:2]:
            add(fact['id'])
    return added


def text(value):
    return escape(str(value)).replace("|", "&#124;").replace("\n", " ").replace("\r", " ").replace("`", "&#96;").replace("[", "&#91;").replace("]", "&#93;")


def markdown(report):
    request = report["request"]
    dynamic = report.get("schema") == "dynamic-research/v1"
    heading = "动态单股研究" if dynamic else (
        "单股假设研究" if report.get("schema") == "single-research/v1" else "单股研究概览")
    lines = [f"# {heading}：{text(request['exchange'])}:{text(request['symbol'])}", "",
             f"运行 `{report['run_id']}`；状态 **{report['status']}**；覆盖 **not_verified**。",
             f"截止时点：{text(request['as_of'])}；PIT：{text(request['mode'])}。", "",
             "基于冻结快照的描述性研究。价格统计仅针对实际可见的首末日期与已观察样本；"
             "不是总收益、完整窗口认证或投资建议。财务报告期与信息可用时间分别保留。", "",
             *overview(report)]
    if dynamic:
        lines += dynamic_sections(report)
        lines += financial_child_sections(report)
    if report.get("schema") in {"single-research/v1", "dynamic-research/v1"}:
        lines += study_sections(report)
    lines += ["## 请求与冻结快照", "", "| 数据 | 请求窗口 | 来源 | 快照 |", "|---|---|---|---|"]
    for b in request["bindings"]:
        lines.append(f"| {text(DATA_LABELS.get(b['dataset'], b['dataset']))} | {b['start']} → {b['end']} | {text(b['provider'])} | `{b['snapshot']}` |")
    lines += ["", "## 可核查数值", "", "ratio 原值为比例，显示为百分比；CNY 原值为人民币元，显示为元/万元/亿元。显示值保留两位，精确数值见 JSON 与证据。", "",
              "| 指标 | 显示值 | 原始单位 | 实际窗口/报告期 | Claim |", "|---|---:|---|---|---|"]
    for f in report["facts"]:
        lines.append(f"| {text(LABELS.get(f['name'], f['name']))} | {display_value(f)} | {f['unit']} | "
                     f"{' → '.join(f['window'])} | `{f['id']}` |")
    if not report["facts"]:
        lines += ["", "证据不足，没有可发布的数值结论。"]
    lines += ["", "## 模型执行状态" if dynamic else "## 模型重点选择", "", f"模型状态：**{report['model']['status']}**。"]
    highlights, merged = displayed_highlights(report)
    if merged:
        lines += ['', '原始模型选择包含同期间、同单位的等额收入重复项，展示已合并；原始选择及全部指标保留在 JSON。']
    for f in highlights:
        lines += ["", f"- {text(LABELS.get(f['name'], f['name']))}：{display_value(f)}，窗口 {' → '.join(f['window'])}，引用 `{f['id']}`。"]
    model_boundary = ("模型选择合法工具动作及已有引用；数值、检验规则和假设状态由确定性工具产生。"
                      "计划更新是控制信息，不作为金融事实、自由归因或买卖建议。" if dynamic else
                      "模型仅选择已有 Claim，不生成事实、自由归因或买卖建议。")
    lines += ["", model_boundary, ""]
    supplements = study_supplements(report)
    if supplements:
        # The separate label prevents system coverage repair from becoming a model success claim.
        lines += ["## 系统核对重点", "",
                  "原始模型选择未覆盖下列核对依据，系统从已校验 Claim 补充。这些是系统补充，不是模型选择；原始回答及质量评分保持。", ""]
        for f in supplements:
            lines += [f"- {text(LABELS.get(f['name'], f['name']))}：{display_value(f)}，窗口 {' → '.join(f['window'])}，引用 `{f['id']}`。"]
        lines += [""]
    lines += ["## 数据缺口与边界", ""]
    lines.extend("- " + text(gap_text(gap)) + "（" + text(gap) + "）" for gap in report["gaps"])
    if report["stop_reason"]:
        lines.append("- 执行终止：" + text(report["stop_reason"]))
    lines += ["", "## 计算与证据链", ""]
    for f in report["facts"]:
        lines += [f"- Claim `{f['id']}`：`{text(f['formula'])}`；输入 " + ", ".join(f"`{i}`" for i in f["inputs"]) + "。"]
    lines += ["", "| Evidence | 原始记录 | 字段/单位 | 值 | 可用时点 | 来源与附件 |", "|---|---|---|---|---|---|"]
    for eid, e in report["evidence"].items():
        lines.append(f"| `{eid}` | `{e['record_id']}` | {text(e['metric'])}/{e['unit']} | {e['value']} | "
                     f"{e['available_at']} ({e['availability_basis']}) | {text(e['source_url'])}; "
                     + ", ".join(f"`{a}`" for a in e["artifact_ids"]) + " |")
    if report["documents"]:
        lines += ["", "## 可见文档索引", "", "以下为来源标题，未提取正文数值，也不证明事件因果关系。", ""]
        for d in report["documents"]:
            lines.append(f"- {text(d['title'])}；可见 {d['available_at']}；记录 `{d['record_id']}`；附件 `{d['body_artifact_id']}`。")
    tool_label = "工具尝试" if dynamic else "工具调用"
    lines += ["", "## 执行账本", "",
              f"{tool_label} {report['usage']['tool_calls']}；模型尝试 {report['usage']['model_attempts']}；"
              f"Token 预留 {report['usage']['tokens_reserved']}（UTF-8 字节保守估算，非实测 Token）；金融 Provider 网络调用 0。",
              "完整 Trace、原始/规范化值、版本、采集时间、快照与 Provider 调用 ID 见配套 JSON。", ""]
    if dynamic:
        usage = report["usage"]
        lines += [f"已知实测 Token {usage.get('total_tokens', 0)}；预算已记账 Token {usage.get('tokens_accounted', 0)}；"
                  f"未知用量调用 {usage.get('unknown_usage_calls', 0)}。未知结果保留原 Token 预留，恢复不自动重发。", ""]
    return "\n".join(lines)


def dynamic_sections(report):
    """Visible control records stay separate from deterministic financial claims."""
    stop_labels = {"cancelled": "已取消", "deadline_exceeded": "绝对截止时间已到",
                   "tool_budget_exceeded": "工具尝试预算已用尽", "model_budget_exceeded": "模型决策预算已用尽",
                   "dynamic_decision_budget_exceeded": "模型决策预算已用尽",
                   "model_input_budget_exceeded": "模型输入或总 Token 预算不足",
                   "dynamic_token_budget_exceeded": "总 Token 预算不足",
                   "context_budget_exceeded": "无损上下文超过预算", "no_progress": "连续无进展，受控停止",
                   "dynamic_context_budget_exceeded": "无损上下文超过预算",
                   "required_checks_incomplete": "事前必需检查未完成",
                   "required_checks_not_completed": "事前必需检查未完成", "evidence_insufficient": "证据不足",
                   "model_reported_insufficient": "模型请求以证据不足结束",
                   "unknown_model_outcome": "付费模型结果未知，未自动重发"}
    lines = ["## 研究问题与动态执行", "", "研究问题：" + text(report["request"]["question"]), "",
             "执行策略：**dynamic**。采用 Chat Completions 文本接口上的严格 JSON 动作协议；"
             "每轮由模型选择合法动作，Runtime 校验后执行工具，再将类型化 Observation 返回模型。", "",
             "模型 finish 仅为结束请求；Runtime 独立核对事前必需检查、数值与引用，未完成时保留 partial / insufficient。", "",
             "## 可见计划更新（控制信息）", "",
             "以下计划由模型提出，仅记录执行安排，不作为金融事实或因果依据；不包含模型隐式推理。", ""]
    for plan in report.get("plans", []):
        lines += ["### 决策轮 " + text(plan["turn"]), ""]
        lines.extend(f"{number}. {text(step)}" for number, step in enumerate(plan["steps"], 1))
        lines += [""]
    if not report.get("plans"):
        lines += ["尚无已接受的计划更新。", ""]
    lines += ["## 模型决策记录", "", "| 决策轮 | 状态 | 动作或失败类别 | Token 预留 | 已知 Token |",
              "|---|---|---|---:|---:|"]
    for decision in report.get("decisions", []):
        action = decision.get("action")
        detail = json.dumps(action, ensure_ascii=False, sort_keys=True) if action is not None else decision.get("error_type", "无已接受动作")
        known = decision.get("total_tokens")
        lines.append(f"| {text(decision['turn'])} | {text(decision['status'])} | {text(detail)} | "
                     f"{text(decision.get('token_reservation', 0))} | {text(known if known is not None else '未知')} |")
    rejected = [decision for decision in report.get("decisions", []) if decision.get("rejection")]
    if rejected:
        lines += ["", "## Runtime 结束拒绝反馈", "",
                  "以下是程序产生的控制反馈。该模型决策已计账，待完成检查保持固定；拒绝记录不作为金融事实。", "",
                  "| 决策轮 | 拒绝代码 | 尚未完成的必需检查 |", "|---|---|---|"]
        for decision in rejected:
            rejection = decision["rejection"]
            pending = ", ".join(text(check) for check in rejection.get("pending_checks", []))
            lines.append(f"| {text(decision['turn'])} | {text(rejection['code'])} | {pending} |")
    lines += ["", "## 事前必需检查", "", "| 检查 | Runtime 判定 |", "|---|---|"]
    check_labels = {"passed": "已通过", "insufficient": "证据不足", "not_completed": "尚未完成"}
    for check in report.get("required_checks", []):
        lines.append(f"| {text(check['id'])} | {text(check_labels.get(check['status'], check['status']))} |")
    reason = report.get("stop_reason")
    lines += ["", "停止原因：" + (text(stop_labels.get(reason, reason)) + "（" + text(reason) + "）" if reason
                                 else "Runtime 验证后结束，未触发强制停止。"), "",
              "## 工具与运行记录", "", "| 序号 | 时刻 | 记录类型 | 决策轮 / 工具 | 结果 |",
              "|---|---|---|---|---|"]
    event_labels = {"model_started": "模型派发 intent", "model_finished": "模型响应", "plan_updated": "计划更新",
                    "tool_started": "工具开始", "tool_finished": "工具 Observation", "repeated_action": "重复动作未重新派发",
                    "finish_rejected": "Runtime 拒绝提前结束", "child_started": "Financial Child 开始",
                    "child_finished": "Financial Child 结构化结果",
                    "report_verified": "Runtime 报告校验", "run_stopped": "受控停止"}
    for event in report.get("trace", []):
        kind = event.get("event", "")
        label = event_labels.get(kind, kind)
        if kind in {"child_started", "child_finished"} and "domain" in event:
            domain = {"financial": "Financial", "market": "Market"}.get(event["domain"], event["domain"])
            label = str(domain) + (" Child 开始" if kind == "child_started" else " Child 结构化结果")
        identity = " / ".join(str(event[key]) for key in ("turn", "tool") if key in event)
        detail = "；".join(f"{key}={event[key]}" for key in ("status", "reason", "error_type", "result_hash", "dedup", "tool_call_id")
                         if key in event)
        lines.append(f"| {text(event.get('seq', ''))} | {text(event.get('time', ''))} | "
                     f"{text(label)} | {text(identity)} | {text(detail)} |")
    return lines + [""]


def financial_child_sections(report):
    """Render only typed lifecycle, source associations and accounting fields."""
    children = report.get("child_results")
    root = report.get("root_budget")
    domains = "routes" in report or any("domain" in child for child in children or [])
    if children is None and root is None and not domains:
        return []
    lines = domain_routes_sections(report)
    lines += ["## 领域 Child 与父子证据关联" if domains else "## Financial Child 与父子证据关联", "",
             ("本入口允许 Financial、Market 两个领域各最多一个受限 Child，严格串行。" if domains else
              "本入口允许一个串行、受限的 Financial Child。") + "父子运行沿用绑定的证券、窗口、cutoff、PIT 和快照；"
             "Child 的状态与来源引用不替代父运行的必需检查或独立数值校验。", ""]
    if not children:
        lines += ["尚无已返回的领域 Child 结果。" if domains else "尚无已返回的 Financial Child 结果。", ""]
    for child in children or []:
        domain = {"financial": "Financial", "market": "Market"}.get(child.get("domain"), child.get("domain"))
        heading = text(domain) + " Child" if domain is not None else "Child"
        lines += ["### " + heading + " 运行 " + text(child["child_run_id"]), "",
                  "| 父运行 | 委派工具调用 | 状态 | 停止原因 | Child 截止时间 |", "|---|---|---|---|---|",
                  f"| {text(child['parent_run_id'])} | {text(child['tool_call_id'])} | {text(child['status'])} | "
                  f"{text(child.get('stop_reason') or '无')} | {text(child['deadline'])} |", "",
                  "| 固定请求引用 | 结构化结果引用 | 来源读取结果引用 |", "|---|---|---|",
                  f"| {text(child['request_ref'])} | {text(child['result_ref'])} | {text(child.get('source_result_ref') or '未返回')} |", "",
                  "| Child 必需检查 | 状态 |", "|---|---|"]
        for check in child.get("required_checks", []):
            lines.append(f"| {text(check['id'])} | {text(check['status'])} |")
        lines += ["", "| 来源记录 | 原始附件 SHA-256 | 快照 | 证据所属工具调用 |", "|---|---|---|---|"]
        for evidence in child.get("evidence_refs", []):
            lines.append(f"| {text(evidence['record_id'])} | {text(evidence['artifact_sha256'])} | "
                         f"{text(evidence['snapshot'])} | {text(evidence['tool_call_id'])} |")
        usage = child.get("usage", {})
        labels = {"model_attempts": "模型尝试", "tool_calls": "工具尝试", "tokens_reserved": "累计 Token 预留",
                  "tokens_accounted": "记账 Token", "total_tokens": "已知实测 Token", "unknown_usage_calls": "未知用量调用"}
        lines += ["", "Child 用量：" + "；".join(label + " " + text(usage[key]) for key, label in labels.items()
                                                if key in usage) + "。", ""]
    if root is not None:
        labels = {"decisions_accounted": "根决策记账（含 Child 占用）", "tools_accounted": "根工具记账（含 Child 占用）",
                  "tokens_accounted": "根 Token 记账（已知实际与未知预留）", "tokens_reserved": "累计模型与 Child 额度预留",
                  "tokens_dispatched_reserved": "父子实际派发的累计 Token 预留", "model_attempts": "已验证模型尝试",
                  "tool_attempts": "已验证工具尝试", "total_tokens": "已知实测 Token",
                  "unknown_usage_calls": "已报告的未知付费用量调用", "unresolved_child_allocations": "尚未结算的 Child 额度"}
        lines += ["## 根预算账本", "",
                  "根记账同时包含父运行及 Child。未知 Child 结果保留已占用额度，恢复不重置预算或自动重发。"
                  "累计预留与已知实测分别显示，不将未知用量记为零。", "",
                  "| 账本项 | 数量 |", "|---|---:|"]
        for key, label in labels.items():
            if key in root:
                value = len(root[key]) if isinstance(root[key], list) else root[key]
                lines.append(f"| {label} | {text(value)} |")
        lines += [""]
    return lines


def domain_routes_sections(report):
    """Only Runtime-recorded route identities are presentation data."""
    if "routes" not in report:
        return []
    lines = ["## Parent 领域路由", "",
             "同一 Parent 从已授权的 Financial / Market 工具或 AgentTool 中选择取证路径；"
             "路由记录来自 Runtime，领域委派按顺序执行。", "",
             "| 决策轮 | 领域 | 执行方式 | 工具 | 工具调用 | Child 运行 |", "|---|---|---|---|---|---|"]
    domains = {"financial": "Financial / 财务", "market": "Market / 行情", "research": "研究计算与校验"}
    modes = {"direct": "直接工具", "delegated": "AgentTool 委派"}
    for route in report["routes"]:
        lines.append(f"| {text(route['turn'])} | {text(domains.get(route['domain'], route['domain']))} | "
                     f"{text(modes.get(route['mode'], route['mode']))} | {text(route['tool'])} | "
                     f"{text(route['tool_call_id'])} | {text(route.get('child_run_id') or '无 Child')} |")
    if not report["routes"]:
        lines += ["", "尚未派发领域工具或 AgentTool。"]
    return lines + [""]


def domain_context_sections(report):
    context = report.get("context", {})
    if context.get("strategy") != "lossless_catalog_lazy_disclosure/v1":
        return []
    labels = {"strategy": "上下文策略", "catalog_ref": "完整目录引用", "context_stage": "当前披露阶段",
              "claims_preserved": "Claim 保留", "evidence_preserved": "Evidence 保留",
              "disclosed_refs": "本轮已披露引用", "bytes": "本轮消息字节", "byte_budget": "消息字节上限",
              "message_sha256": "精确消息 SHA-256", "facts_included": "目录 Fact 数",
              "evidence_included": "目录 Evidence 数", "source_bodies_included": "源正文数", "omitted_claims": "丢失 Claim 数"}
    lines = ["## 无损目录与按需上下文", "",
             "模型消息使用完整目录引用和按需披露。以下记录编码与披露状态；"
             "报告继续保留全部 Fact、Evidence 和实际运行记录。目录中的 Evidence 总数包含本轮未展开者；"
             "实际披露见本轮引用。", "", "| 上下文项 | 值 |", "|---|---|"]
    for key, label in labels.items():
        if key in context:
            value = context[key]
            if isinstance(value, (list, tuple)):
                value = ", ".join(str(item) for item in value) or "无"
            lines.append(f"| {label} | {text(value)} |")
    return lines + [""]


def study_sections(report):
    labels = {"supported": "支持描述性检验", "unsupported": "观察反证", "conflicted": "方向冲突",
              "insufficient": "证据不足"}
    reasons = {"required_evidence_missing": "尚缺检验必需的可见数据或同报告期基数",
               "factor_changes_endpoint_result": "端点复权因子不同，改变精确的区间价格比较",
               "no_endpoint_adjustment_difference_observed": "端点复权因子相同，未观察到端点调整差异",
               "zero_change_has_no_direction": "至少一侧变化为零，无法判定同向",
               "same_direction_observed": "同日期区间内两者同向，因果关系未建立",
               "opposite_direction_observed": "同日期区间内两者方向相反",
               "both_same_period_yoy_decline": "两项同报告期同比均下降",
               "mixed_financial_directions": "收入与利润同比方向不一致，保留反证",
               "neither_metric_declines": "两项同比未同时下降",
               "financial_period_mismatch": "利润与现金流报告期不一致，停止比较",
               "positive_profit_negative_operating_cashflow": "同报告期利润为正、经营现金流为负",
               "divergence_condition_not_observed": "未满足正利润且负经营现金流条件",
               "verified_anchor_and_observed_pre_post_closes": "合格披露锚点前后均存在可见观察收盘价",
               "event_anchor_not_requested": "本次没有指定事件来源记录",
               "event_anchor_not_visible": "指定事件记录在本次权限、快照与截止时点下不可见",
               "event_anchor_dataset_not_supported": "此数据类型不支持作为事件披露锚点",
               "capture_is_not_event_release_time": "只有采集时点，缺少合格的首次公开时间证明",
               "event_pre_post_closes_missing": "缺少合格锚点前后的有效收盘价，未计算价格变化",
               "calculation_not_completed": "执行停止，计算与检验尚未完成"}
    research_status = {"stopped": "执行停止", "evidence_incomplete": "证据不全", "tests_completed": "所选检验已完成"}
    lines = ["", "## 假设检验与综合", "",
             "研究状态：**" + research_status[report["research_status"]] + "**。支持只表示满足预先定义的描述性规则；因果结论未建立。", "",
             "| 待检验假设 | 结果 | 规则与所需证据 | 支持 / 反证 Claim | 缺口或判断依据 |",
             "|---|---|---|---|---|"]
    for h in report["hypotheses"]:
        citations = ", ".join(f"`{c}`" for c in h["claim_ids"])
        counter = ", ".join(f"`{c}`" for c in h["counterevidence_claim_ids"])
        required = ', '.join(DATA_LABELS.get(d, "指定事件来源记录" if d == "explicit_event_record" else d) for d in h['required_evidence'])
        lines.append(f"| {text(h['title'])} | {labels[h['status']]} | {text(h['test_rule'])}；{text(required)} | "
                     f"{citations or '无支持 Claim'}; 反证 {counter or '无已观察反证'} | {text(reasons.get(h['reason'], h['reason']))} |")
    lines += insufficiency_sections(report)
    anchor = report["event_anchor"]
    lines += ["", "## 事件时间锚点", ""]
    if anchor["status"] == "verified":
        lines += [f"- 精度：{text(anchor['precision'])}；来源记录 `{anchor['record_id']}`；快照 `{anchor['snapshot']}`。",
                  f"- 披露时间/日期：{text(anchor.get('disclosed_at', anchor.get('release_date')))}；"
                  f"保守日期边界 {anchor['boundary_date']}；数据可用 {anchor['available_at']}。",
                  "- 日频收盘按中国市场 15:00 划分；日期精度排除披露日作为事前端点。"
                  "统计使用窗口内最后可见事前与事后收盘，缺口不插值，不构成事件影响或因果估计。"]
    else:
        lines += ["- 证据不足：" + text(reasons.get(anchor.get("reason"), anchor.get("reason"))) + "。"]
        if anchor.get("record_id"):
            lines += [f"- 可见来源记录 `{anchor['record_id']}`；附件 " + ", ".join(f"`{a}`" for a in anchor["artifact_ids"]) + "。"]
    v = report["verification"]
    lines += ["", "## Claim 校验与上下文", "",
              f"- 校验状态 {text(v['status'])}；数值 Claim {v['numeric_claims']}；"
              f"来源证据 {v.get('evidence_checked', 0)}；假设 {v.get('hypotheses_checked', 0)}。",
              "- 数值由独立 Fraction 算术复核，并核对单位、窗口、口径、版本、来源、快照和 PIT；不认证供应商真值或因果。",
              f"- 上下文状态 {text(report['context']['status'])}；源正文与标题均不进入模型。"
              "超过无损上下文预算时停止模型步骤，保留精确本地 Evidence。", ""]
    lines += domain_context_sections(report)
    selected = report["model"].get("hypotheses", [])
    if selected:
        label = "可信请求固定的检验范围：" if report.get("schema") == "dynamic-research/v1" else "模型选择的检验重点："
        lines += [label + ", ".join(f"`{h}`" for h in selected) + "；完整检验与反证始终保留。", ""]
    return lines


def insufficiency_sections(report):
    """Render optional new-version diagnostics; legacy Markdown stays byte-identical."""
    diagnostics = report.get("insufficiency_diagnostics", [])
    if not diagnostics:
        return []
    categories = {"benchmark_or_request_contract_defect": "Benchmark / 请求契约问题",
                  "data_or_evidence_insufficiency": "数据 / Evidence 不足",
                  "intrinsic_precondition_or_temporal_impossibility": "原前置条件 / 时间条件不可满足",
                  "not_assessable": "无法进一步判断"}
    titles = {h["id"]: h["title"] for h in report["hypotheses"]}
    lines = ["", "## insufficient 原因诊断", "",
             "以下诊断仅使用本次已授权读取的可见输入，保留原假设状态、公式和证据。"
             "请求契约、证据不足及前置条件问题分别记录，不直接归责 Agent；没有据此调整任务成功率或旧评分。", "",
             "| 假设 | 原因代码 | 问题类别 | 可审计依据 | 输入引用 |", "|---|---|---|---|---|"]
    for diagnostic in diagnostics:
        for reason in diagnostic["insufficiency_reasons"]:
            names = ", ".join(DATA_LABELS.get(name, name) for name in reason["datasets"])
            field = reason.get("metric")
            if field:
                names += "；字段 " + DATA_LABELS.get(field, field)
            references = (names + "；" if names else "") + ", ".join(
                "记录 " + str(ref) for ref in reason["record_refs"])
            if reason["evidence_refs"]:
                references += ("；" if references else "") + ", ".join(
                    "Evidence " + str(ref) for ref in reason["evidence_refs"])
            category = reason["failure_category"]
            lines.append(f"| {text(titles.get(diagnostic['hypothesis_id'], diagnostic['hypothesis_id']))} | "
                         f"{text(reason['code'])} | {text(categories.get(category, category))} "
                         f"({text(category)}) | {text(reason['detail'])} | {text(references or '无可见输入引用')} |")
    return lines
