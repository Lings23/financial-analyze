"""Frozen real-snapshot offline Runtime acceptance; no provider/model dispatch.

Fraction oracle is independent of production calculation. Source accuracy and live
model Task Success are explicitly outside this suite's denominator.
"""
import argparse
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, PITMode, QueryContext, digest
from stock_research.providers.base import ProviderRegistry
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.contracts import Binding, ResearchRequest
from stock_research.research.runtime import ResearchRuntime
from stock_research.models import Security
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

ROOT = Path('.artifacts/p17_20261001/formal')
RUN = ROOT / 'run.json'
PLAN = Path('evaluation/p17_20261001_formal_plan.json')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def service():
    # Read-only application operations; never print or persist the local DSN.
    dsn = Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip()
    return DataService(ProviderRegistry(), None, PostgresRepository(dsn), ArtifactStore(ROOT / 'artifacts'))


def read_inputs(svc, request, access):
    return {b.dataset: svc.query(request.data_request(b),
            QueryContext(access, b.snapshot, request.as_of, request.mode)).records for b in request.bindings}


def oracle(data):
    expected = {}
    prices = sorted(data['market_daily'], key=lambda r: r.period)
    closes = [next(m.value for m in r.metrics if m.name == 'close') for r in prices]
    if len(closes) >= 2 and all(v is not None and v > 0 for v in closes):
        values = [Fraction(v) for v in closes]
        expected['observed_price_change'] = values[-1] / values[0] - 1
        expected['observed_max_drawdown'] = max(1 - v / max(values[:i+1]) for i, v in enumerate(values))
    financials = sorted(data['financial_income'], key=lambda r: r.period)
    if financials:
        latest = financials[-1]
        expected.update({'financial_income.' + m.name: Fraction(m.value)
                         for m in latest.metrics if m.value is not None})
        prior = next((r for r in financials if r.period.isoformat() ==
                      str(latest.period.year - 1) + latest.period.isoformat()[4:]), None)
        if prior:
            for field in ('revenue', 'net_income_parent'):
                current = next(m.value for m in latest.metrics if m.name == field)
                base = next(m.value for m in prior.metrics if m.name == field)
                if current is not None and base is not None and base > 0:
                    expected[field + '_yoy'] = Fraction(current) / Fraction(base) - 1
    partial = (len(closes) < 2 or any(v is None or v <= 0 for v in closes)
               or not financials or any(m.value is None for m in financials[-1].metrics))
    return expected, 'partial' if partial else 'completed'


def prepare(path):
    run = json.loads(RUN.read_bytes())
    plan_sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert run['plan_sha256'] == plan_sha
    svc = service()
    access = AccessContext(run['scope'], frozenset({'tushare'}))
    cutoff = datetime.fromisoformat(run['finished_at']) + timedelta(seconds=1)
    income = {e['request']['symbol']: e for e in run['results']
              if e['request']['dataset'] == 'financial_income' and e['status'] == 'ingested'}
    cases = []
    for entry in run['results']:
        item = entry['request']
        if item['dataset'] != 'market_daily':
            continue
        assert entry['status'] == 'ingested'
        entries = (entry, income[item['symbol']])
        bindings = tuple(Binding(e['request']['dataset'], e['snapshot_id'], 'tushare',
                         datetime.fromisoformat(e['request']['start']).date(),
                         datetime.fromisoformat(e['request']['end']).date()) for e in entries)
        request = ResearchRequest(Security(item['symbol'], item['exchange']), cutoff, PITMode.SYSTEM, bindings)
        data = read_inputs(svc, request, access)
        expected, status = oracle(data)
        cases.append({'id': item['symbol'] + '-' + item['start'], 'request': request.to_dict(),
                      'expected': {k: [v.numerator, v.denominator] for k, v in expected.items()},
                      'expected_status': status,
                      'input_hash': digest({k: [r.to_dict() for r in rows] for k, rows in data.items()})})
    assert len(cases) == 50 and len({c['id'] for c in cases}) == 50
    write(path, {'kind': 'real_frozen_snapshot_fixed_runtime', 'scope': access.scope,
                 'source_run_sha256': hashlib.sha256(RUN.read_bytes()).hexdigest(),
                 'source_plan_sha256': plan_sha, 'model': 'disabled', 'cases': cases,
                 'oracle': 'Fraction arithmetic from authorized pinned inputs, frozen before Runtime execution',
                 'provider_accuracy_certified': False, 'live_model_task_success_certified': False})
    print(json.dumps({'prepared_cases': len(cases), 'corpus_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}))


def evaluate(path, output):
    corpus = json.loads(path.read_bytes())
    assert hashlib.sha256(RUN.read_bytes()).hexdigest() == corpus['source_run_sha256']
    assert hashlib.sha256(PLAN.read_bytes()).hexdigest() == corpus['source_plan_sha256']
    output.mkdir(parents=True, exist_ok=False)
    svc = service()
    access = AccessContext(corpus['scope'], frozenset({'tushare'}))
    store = CheckpointStore(output / 'runs')
    results = []
    numeric_total = numeric_correct = lineage_total = 0
    for case in corpus['cases']:
        request = ResearchRequest.from_dict(case['request'])
        data = read_inputs(svc, request, access)
        assert digest({k: [r.to_dict() for r in rows] for k, rows in data.items()}) == case['input_hash']
        report = ResearchRuntime(svc, store).run(request, access)
        facts = {f['name']: f for f in report['facts']}
        expected = {k: Fraction(*v) for k, v in case['expected'].items()}
        checks = {'fact_set': set(facts) == set(expected), 'status': report['status'] == case['expected_status'],
                  'model_disabled': report['model']['status'] == 'disabled', 'coverage': report['coverage'] == 'not_verified'}
        numeric = [k in facts and abs(Fraction(Decimal(facts[k]['value'])) - v) < Fraction(1, 10**28)
                   for k, v in expected.items()]
        checks['arithmetic'] = all(numeric)
        records = {r.record_id: r for rows in data.values() for r in rows}
        for evidence in report['evidence'].values():
            record = records[evidence['record_id']]
            metric = next(m for m in record.metrics if m.name == evidence['metric'])
            assert evidence['value'] == (None if metric.value is None else str(metric.value))
            assert evidence['unit'] == metric.unit and evidence['provider_call_id'] == record.provider_call_id
            assert tuple(evidence['artifact_ids']) == record.artifact_ids
            assert datetime.fromisoformat(evidence['available_at']) <= request.as_of
            assert datetime.fromisoformat(evidence['ingested_at']) <= request.as_of
            assert evidence['snapshot'] == next(b.snapshot for b in request.bindings if b.dataset == record.dataset.value)
        checks['lineage'] = all(f['inputs'] and all(i in report['evidence'] and report['evidence'][i]['value'] is not None
                                                   for i in f['inputs']) for f in facts.values())
        replay = ResearchRuntime(svc, CheckpointStore(output / 'runs')).run(request, access, resume=report['run_id'])
        checks['completed_replay'] = replay == report
        try:
            ResearchRuntime(svc, store).run(request, AccessContext(access.scope, frozenset({'cninfo'})), resume=report['run_id'])
        except PermissionDenied:
            checks['revoked_source_denied'] = True
        else:
            checks['revoked_source_denied'] = False
        # Genuine observations before capture must produce no claims, not backfilled historical facts.
        before = min(r.available_at for r in records.values()) - timedelta(microseconds=1)
        historical = ResearchRuntime(svc, store).run(replace(request, as_of=before), access)
        checks['pre_capture_invisible'] = not historical['facts'] and historical['status'] == 'partial'
        write(output / (case['id'] + '.json'), report)
        numeric_total += len(expected)
        numeric_correct += sum(numeric)
        lineage_total += len(report['facts'])
        results.append({'case': case['id'], 'passed': all(checks.values()), 'checks': checks,
                        'numeric_checks': len(expected), 'evidence_checked': len(report['evidence']),
                        'report_hash': digest(report)})
    result = {'kind': corpus['kind'], 'corpus_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'tasks_total': len(results), 'tasks_passed': sum(r['passed'] for r in results),
              'numeric_checks_total': numeric_total, 'numeric_checks_correct': numeric_correct,
              'numeric_claims_lineage_checked': lineage_total,
              'evidence_checked': sum(r['evidence_checked'] for r in results),
              'model_network_calls': 0, 'financial_provider_network_calls': 0,
              'provider_accuracy_certified': False, 'live_model_task_success_certified': False,
              'cases': results}
    write(output / 'result.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}))
    return 0 if all(r['passed'] for r in results) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--corpus', type=Path, default=Path('evaluation/phase2_real_acceptance_20261002.json'))
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('.artifacts/phase2/acceptance-20261002/real'))
    args = parser.parse_args()
    if args.prepare:
        prepare(args.corpus)
    else:
        raise SystemExit(evaluate(args.corpus, args.output))
