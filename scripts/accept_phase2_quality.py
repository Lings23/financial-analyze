"""Task-quality rubric and bounded real-model campaign. No provider refresh.

Readable reports and model relevance are distinct from arithmetic/provider accuracy.
Prepare exact outbound messages before dispatch; no retries or model substitution.
"""
import argparse
import hashlib
import json
import time
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from accept_phase2_real import oracle, read_inputs, service, write
from stock_research.errors import IntegrityError
from stock_research.models import AccessContext, digest
from stock_research.model_adapters.chat import ChatHTTPTransport, ChatModelAdapter, load_model_config
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.contracts import ResearchRequest
from stock_research.research.report import markdown
from stock_research.research.runtime import ResearchRuntime, model_messages

CORPUS = Path('evaluation/phase2_real_acceptance_20261002.json')
REPORTS = Path('.artifacts/phase2/acceptance-20261002/real-retest')
ROOT = Path('.artifacts/phase2/task-quality-20261002')


def selection_checks(report):
    facts = {f['id']: f for f in report['facts']}
    selected = report['model'].get('highlights', [])
    valid = bool(selected) and len(selected) <= 3 and len(selected) == len(set(selected)) and all(i in facts for i in selected)
    names = {facts[i]['name'] for i in selected if i in facts}
    available = {f['name'] for f in facts.values()}
    market = lambda n: n.startswith('observed_') or n in {'factor_adjusted_price_change', 'benchmark_price_change', 'price_change_difference'}
    financial = lambda n: n.startswith('financial_') or n.endswith('_yoy')
    revenue_pair = [f for f in facts.values() if f['name'] in {'financial_income.revenue', 'financial_income.total_revenue'}]
    duplicate = (len(revenue_pair) == 2 and all(f['name'] in names for f in revenue_pair)
                 and Decimal(revenue_pair[0]['value']) == Decimal(revenue_pair[1]['value'])
                 and revenue_pair[0]['unit'] == revenue_pair[1]['unit'] and revenue_pair[0]['window'] == revenue_pair[1]['window'])
    return {'verified_model': report['model']['status'] == 'verified', 'valid_existing_claims': valid,
            'market_covered_when_available': not any(market(n) for n in available) or any(market(n) for n in names),
            'financial_covered_when_available': not any(financial(n) for n in available) or any(financial(n) for n in names),
            'no_equal_revenue_redundancy': not duplicate}


def report_checks(report, rendered):
    facts = {f['name']: f for f in report['facts']}
    summary = rendered.split('## 概览', 1)[-1].split('## 请求', 1)[0] if '## 概览' in rendered else ''
    price = facts.get('observed_price_change')
    financial = next((facts[n] for n in ('financial_income.revenue', 'financial_income.net_income_parent') if n in facts), None)
    return {'plain_summary': bool(summary),
            'observed_price_window': price is None or all(d in summary for d in price['window']),
            'readable_price_percent': price is None or '%' in summary,
            'financial_period_and_cny': financial is None or (financial['window'][-1] in summary and '元' in summary),
            'missing_market_not_zero': price is not None or '无法计算价格变化' in summary,
            'yoy_gap_explained': not any('yoy_prior_year_period_not_visible' in g for g in report['gaps']) or '无法计算同比' in rendered,
            'coverage_explained': '覆盖尚未认证' in rendered,
            'claim_references': all(f['id'] in rendered for f in report['facts']),
            'exact_json_values': report['coverage'] == 'not_verified'}


def authorized_report(svc, case, access):
    report = json.loads((REPORTS / (case['id'] + '.json')).read_bytes())
    request = ResearchRequest.from_dict(case['request'])
    assert report['request'] == case['request']
    data = read_inputs(svc, request, access)
    assert digest({k: [r.to_dict() for r in rows] for k, rows in data.items()}) == case['input_hash']
    expected, _ = oracle(data)
    actual = {f['name']: f for f in report['facts']}
    assert set(actual) == set(expected)
    assert all(abs(Fraction(Decimal(actual[k]['value'])) - v) < Fraction(1, 10**28)
               for k, v in expected.items())
    expected_hash = next(r['report_hash'] for r in json.loads((REPORTS / 'result.json').read_bytes())['cases'] if r['case'] == case['id'])
    assert digest(report) == expected_hash
    return report


def audit(output):
    corpus = json.loads(CORPUS.read_bytes())
    svc = service()
    access = AccessContext(corpus['scope'], frozenset({'tushare'}))
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for case in corpus['cases']:
        report = authorized_report(svc, case, access)
        rendered = markdown(report)
        checks = report_checks(report, rendered)
        (output / (case['id'] + '.md')).write_text(rendered, encoding='utf-8')
        results.append({'case': case['id'], 'passed': all(checks.values()), 'checks': checks})
    result = {'kind': 'real_report_product_quality', 'rubric_version': 'overview-task-quality-v1',
              'tasks_passed': sum(r['passed'] for r in results), 'tasks_total': len(results), 'cases': results,
              'model_network_calls': 0, 'provider_network_calls': 0, 'independent_expert_quality_certified': False}
    write(output / 'result.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}))


def prepare():
    corpus = json.loads(CORPUS.read_bytes())
    svc = service()
    access = AccessContext(corpus['scope'], frozenset({'tushare'}))
    cases = []
    for case in corpus['cases']:
        if case['request']['bindings'][0]['start'] != '2026-09-15':
            continue
        report = authorized_report(svc, case, access)
        cases.append({'case': case['id'], 'request': case['request'], 'source_report_hash': digest(report),
                      'facts_hash': digest(report['facts']), 'messages': model_messages(report['facts'])})
    assert len(cases) == 25
    manifest = {'rubric_version': 'overview-task-quality-v1', 'model': 'deepseek-v4-flash-0731',
                'endpoint': 'test_api.txt configured HTTPS endpoint only', 'max_dispatches': 25,
                'max_total_token_reservation': 60000, 'max_completion_tokens_per_call': 384,
                'corpus_sha256': hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
                'criteria': ['strict verified selection', 'market and financial coverage when available',
                             'no redundant equal revenue/total_revenue of same period and unit',
                             'unchanged deterministic facts and no provider calls'], 'cases': cases}
    write(ROOT / 'proposed-model-campaign.json', manifest)
    print(json.dumps({'prepared_calls': len(cases), 'manifest_sha256': hashlib.sha256((ROOT / 'proposed-model-campaign.json').read_bytes()).hexdigest(),
                      'max_total_token_reservation': 60000}))


def live(output):
    manifest_path = ROOT / 'proposed-model-campaign.json'
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest['model'] == 'deepseek-v4-flash-0731' and len(manifest['cases']) == 25
    assert hashlib.sha256(CORPUS.read_bytes()).hexdigest() == manifest['corpus_sha256']
    output.mkdir(parents=True, exist_ok=False)
    config = load_model_config()
    upstream = ChatHTTPTransport()
    svc = service()
    access = AccessContext(json.loads(CORPUS.read_bytes())['scope'], frozenset({'tushare'}))
    store = CheckpointStore(output / 'runs')
    dispatches, reserved = 0, 0
    results = []
    for case in manifest['cases']:
        request = ResearchRequest.from_dict(case['request'])
        def transport(cfg, payload, timeout):
            nonlocal dispatches, reserved
            if cfg.endpoint != config.endpoint or payload['model'] != manifest['model'] or payload['messages'] != case['messages']:
                raise IntegrityError('outbound request differs from reviewed campaign')
            if payload['max_tokens'] != manifest['max_completion_tokens_per_call']:
                raise IntegrityError('campaign output budget changed')
            reservation = sum(len(m['content'].encode('utf-8')) for m in payload['messages']) + 256 + payload['max_tokens']
            if dispatches >= manifest['max_dispatches'] or reserved + reservation > manifest['max_total_token_reservation']:
                raise IntegrityError('campaign budget exceeded')
            dispatches += 1
            reserved += reservation
            # Persist whole-campaign intent before dispatch, in addition to Runtime intent.
            write(output / ('dispatch-' + str(dispatches) + '.json'),
                  {'case': case['case'], 'dispatch': dispatches, 'tokens_reserved': reserved, 'outbound_messages_hash': digest(payload['messages'])})
            return upstream(cfg, payload, min(timeout, 30))
        report = ResearchRuntime(svc, store, ChatModelAdapter(config, transport)).run(request, access)
        checks = selection_checks(report)
        checks['facts_unchanged'] = digest(report['facts']) == case['facts_hash']
        checks.update(report_checks(report, markdown(report)))
        write(output / (case['case'] + '.json'), report)
        (output / (case['case'] + '.md')).write_text(markdown(report), encoding='utf-8')
        results.append({'case': case['case'], 'passed': all(checks.values()), 'checks': checks, 'model': report['model'],
                        'status': report['status'], 'report_hash': digest(report)})
        print(json.dumps({'case': case['case'], 'passed': all(checks.values()), 'model_status': report['model']['status']}), flush=True)
        time.sleep(0.5)
    result = {'kind': 'real_model_fixed_task_quality', 'rubric_version': manifest['rubric_version'],
              'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
              'tasks_total': len(results), 'tasks_passed': sum(r['passed'] for r in results),
              'model_dispatches': dispatches, 'tokens_reserved': reserved,
              'known_measured_tokens': sum(r['model']['total_tokens'] for r in results if r['model'].get('total_tokens') is not None),
              'total_measured_tokens': None if any(r['model'].get('total_tokens') is None for r in results) else sum(r['model']['total_tokens'] for r in results),
              'unknown_usage_calls': sum(r['model'].get('total_tokens') is None for r in results),
              'provider_network_calls': 0, 'independent_expert_quality_certified': False, 'cases': results}
    write(output / 'result.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}))


def verify_campaign(directory, output):
    """New process, independent arithmetic and current authorization; never dispatch a model."""
    manifest_path = ROOT / 'proposed-model-campaign.json'
    manifest = json.loads(manifest_path.read_bytes())
    result = json.loads((directory / 'result.json').read_bytes())
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == result['manifest_sha256']
    assert result['model_dispatches'] == len(manifest['cases']) == 25
    output.mkdir(parents=True, exist_ok=False)
    svc = service()
    access = AccessContext(json.loads(CORPUS.read_bytes())['scope'], frozenset({'tushare'}))
    config = load_model_config()
    attempts = 0
    def forbid(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise AssertionError('replay attempted a model dispatch')
    runtime = ResearchRuntime(svc, CheckpointStore(directory / 'runs'), ChatModelAdapter(config, forbid))
    numeric_count = evidence_count = product_passed = quality_passed = tokens = 0
    cases = []
    for i, case in enumerate(manifest['cases'], 1):
        report = json.loads((directory / (case['case'] + '.json')).read_bytes())
        saved = next(r for r in result['cases'] if r['case'] == case['case'])
        assert digest(report) == saved['report_hash'] and digest(report['facts']) == case['facts_hash']
        request = ResearchRequest.from_dict(case['request'])
        assert runtime.run(request, access, resume=report['run_id']) == report
        data = read_inputs(svc, request, access)
        expected, _ = oracle(data)
        actual = {f['name']: f for f in report['facts']}
        assert set(actual) == set(expected)
        assert all(abs(Fraction(Decimal(actual[k]['value'])) - v) < Fraction(1, 10**28) for k, v in expected.items())
        records = {r.record_id: r for rows in data.values() for r in rows}
        for evidence in report['evidence'].values():
            record = records[evidence['record_id']]
            metric = next(m for m in record.metrics if m.name == evidence['metric'])
            assert evidence['value'] == (None if metric.value is None else str(metric.value)) and evidence['unit'] == metric.unit
            assert tuple(evidence['artifact_ids']) == record.artifact_ids
        assert all(f['inputs'] and all(eid in report['evidence'] for eid in f['inputs']) for f in report['facts'])
        rendered = markdown(report)
        checks = {**selection_checks(report), 'facts_unchanged': True, **report_checks(report, rendered)}
        assert checks == saved['checks']  # Frozen scoring, including the original failure.
        numeric_count += len(actual)
        evidence_count += len(report['evidence'])
        quality_passed += all(checks.values())
        product = report_checks(report, rendered)
        income = [f for f in report['facts'] if f['name'] in {'financial_income.revenue', 'financial_income.total_revenue'}
                  and f['id'] in report['model'].get('highlights', [])]
        section = rendered.split('## 模型重点选择')[1].split('## 数据缺口')[0]
        if len(income) == 2 and Decimal(income[0]['value']) == Decimal(income[1]['value']) and income[0]['window'] == income[1]['window'] and income[0]['unit'] == income[1]['unit']:
            product['redundant_display_merged'] = not ('营业收入（累计）' in section and '营业总收入（累计）' in section) and '展示已合并' in section
        else:
            product['redundant_display_merged'] = True
        assert all(product.values())
        product_passed += all(product.values())
        tokens += report['model']['total_tokens']
        intent = json.loads((directory / ('dispatch-' + str(i) + '.json')).read_bytes())
        assert intent['case'] == case['case'] and intent['outbound_messages_hash'] == digest(case['messages'])
        (output / (case['case'] + '.md')).write_text(rendered, encoding='utf-8')
        cases.append({'case': case['case'], 'raw_quality_passed': all(checks.values()), 'display_passed': all(product.values()),
                      'replay_identical': True, 'numeric_claims_checked': len(actual), 'evidence_checked': len(report['evidence'])})
    assert attempts == 0 and tokens == result['total_measured_tokens']
    verification = {'tasks': len(cases), 'raw_model_quality_passed': quality_passed, 'report_display_passed': product_passed,
                    'numeric_claims_correct': numeric_count, 'numeric_claims_total': numeric_count,
                    'evidence_checked': evidence_count, 'replay_identical': len(cases), 'model_dispatches': attempts,
                    'provider_network_calls': 0, 'measured_tokens_unchanged': tokens, 'cases': cases}
    write(output / 'result.json', verification)
    print(json.dumps({k: v for k, v in verification.items() if k != 'cases'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--verify-campaign', type=Path, help='local authorized replay; no model dispatch')
    parser.add_argument('--output', type=Path, default=ROOT / 'audit')
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.live:
        live(args.output)
    elif args.verify_campaign:
        verify_campaign(args.verify_campaign, args.output)
    else:
        audit(args.output)
