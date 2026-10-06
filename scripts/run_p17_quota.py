"""Pre-registered, bounded sustained financial API checks below reported quota.

Uses the same executor for both formal providers, hence a shared tushare limit.
The observed configured rate is distinct from an account's maximum quota.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

from stock_research.__main__ import _project_tushare_token
from stock_research.domains import DomainDataset, DomainRequest, Subject
from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.providers.tushare import TushareHTTPTransport, TushareProvider
from stock_research.providers.tushare_domains import TushareDomainProvider
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

PLAN = Path('evaluation/p17_20261001_quota_plan.json')
ROOT = Path('.artifacts/p17_20261001/quota')


def request(item):
    period = date.fromisoformat(item['period'])
    if item['dataset'] == 'financial_income':
        return DataRequest(Security(item['code'], item['exchange']), Dataset.FINANCIAL_INCOME, period, period)
    return DomainRequest(Subject('equity', item['code'], item['exchange']),
                         DomainDataset(item['dataset']), period, period)


def verify(plan, run, db, artifacts):
    access = AccessContext(plan['scope'], frozenset({'tushare'}))
    after = datetime.fromisoformat(run['finished_at'])+timedelta(seconds=1)
    checked = 0
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(), executor, db, artifacts)
        for entry in run['results']:
            if entry['status'] != 'ingested':
                continue
            req = request(entry['request'])
            ctx = QueryContext(access, entry['snapshot_id'], after, PITMode.SYSTEM)
            records = service.query(req, ctx).records
            assert len(records) == entry['visible_count'] > 0
            assert sorted(r.record_id for r in records) == entry['visible_record_ids']
            for r in records:
                assert hashlib.sha256(service.evidence(req, ctx, r.record_id)).hexdigest() == r.artifact_id
            before = min(r.available_at for r in records)-timedelta(microseconds=1)
            assert not service.query(req, QueryContext(access, entry['snapshot_id'], before)).records
            denied = AccessContext(access.scope, frozenset({'cninfo'}))
            assert not service.query(req, QueryContext(denied, entry['snapshot_id'], after)).records
            checked += 1
    starts = [v['monotonic_start'] for v in run['http_calls']]
    intervals = [b-a for a,b in zip(starts, starts[1:])]
    peak = max((sum(t <= s < t+60 for s in starts) for t in starts), default=0)
    counts = dict(Counter(v['api_name'] for v in run['http_calls']))
    passed = (checked == len(plan['requests']) == len(starts)
              and all(v.get('business_code') == 0 and v.get('response_rows',0) > 0 for v in run['http_calls'])
              and len(starts) > 1 and starts[-1]-starts[0] >= 120
              and min(intervals) >= plan['min_interval_seconds']-0.01
              and peak <= plan['configured_calls_per_minute']
              and run['provider_stats']['attempts'] == len(starts)
              and run['provider_stats']['retries'] == run['provider_stats']['cache_hits'] == 0)
    return {'checked_at':datetime.now(timezone.utc).isoformat(), 'verified_snapshots':checked,
            'http_calls':len(starts), 'calls_by_api':counts,
            'start_span_seconds':round(starts[-1]-starts[0],3) if len(starts)>1 else 0,
            'minimum_start_interval_seconds':round(min(intervals),3) if intervals else None,
            'peak_calls_in_any_60_seconds':peak, 'configured_calls_per_minute':plan['configured_calls_per_minute'],
            'configured_rate_sustained_verified':passed, 'account_maximum_80_verified':False,
            'cross_date_all_three_tables_verified':False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    plan_bytes = PLAN.read_bytes()
    plan = json.loads(plan_bytes)
    sha = hashlib.sha256(plan_bytes).hexdigest()
    ROOT.mkdir(parents=True, exist_ok=True)
    store = ArtifactStore(ROOT/'artifacts')
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    run_path, replay_path = ROOT/'run.json', ROOT/'replay.json'
    if args.verify_only:
        run = json.loads(run_path.read_text(encoding='utf-8'))
        assert sha == run['plan_sha256']
        prior = json.loads(replay_path.read_text(encoding='utf-8'))
        output = verify(plan, run, db, store)
        assert {k:v for k,v in prior.items() if k!='checked_at'} == {k:v for k,v in output.items() if k!='checked_at'}
        print(json.dumps(output))
        return 0 if output['configured_rate_sustained_verified'] else 2
    if run_path.exists():
        raise ValueError('frozen quota run exists')
    for path, expected in plan['code_sha256'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
    plan_aid = store.put_bytes(plan['scope'], plan_bytes)
    run = {'scope':plan['scope'], 'plan_sha256':sha, 'plan_artifact_id':plan_aid,
           'started_at':datetime.now(timezone.utc).isoformat(), 'results':[], 'http_calls':[]}
    token = _project_tushare_token()
    upstream = TushareHTTPTransport()
    origin = time.monotonic()

    def transport(payload, timeout):
        call = {'api_name':payload['api_name'], 'started_at':datetime.now(timezone.utc).isoformat(),
                'monotonic_start':time.monotonic()-origin}
        run['http_calls'].append(call)
        try:
            response = upstream(payload, timeout)
            call['business_code'] = response.get('code')
            call['response_rows'] = len((response.get('data') or {}).get('items') or [])
            return response
        except Exception as exc:
            call['error_type'] = type(exc).__name__
            raise
        finally:
            call['finished_at'] = datetime.now(timezone.utc).isoformat()

    standard, domains = ProviderRegistry(), ProviderRegistry()
    standard.register(TushareProvider(token, store, transport))
    domains.register(TushareDomainProvider(token, store, transport))
    access = AccessContext(plan['scope'], frozenset({'tushare'}))
    policy = ExecutionPolicy(total_timeout=20, attempt_timeout=15, max_attempts=1,
                             min_interval=plan['min_interval_seconds'], provider_concurrency=1)
    with ProviderExecutor(policy) as executor:
        services = {False:DataService(standard, executor, db, store), True:DataService(domains, executor, db, store)}
        for i, item in enumerate(plan['requests']):
            service = services[item['dataset'] != 'financial_income']
            try:
                req = request(item)
                result = service.refresh(req, access, use_cache=False)
                ctx = QueryContext(access, result.snapshot.snapshot_id, datetime.now(timezone.utc), PITMode.SYSTEM)
                rows = service.query(req, ctx).records
                if not rows:
                    raise AssertionError('mandatory financial request returned no facts')
                entry = {'request':item, 'status':'ingested', 'snapshot_id':result.snapshot.snapshot_id,
                         'stored_count':result.record_count, 'visible_count':len(rows),
                         'visible_record_ids':sorted(r.record_id for r in rows)}
            except Exception as exc:
                entry = {'request':item, 'status':'failed', 'error_type':type(exc).__name__}
            run['results'].append(entry)
            print(json.dumps({'request_number':i+1, 'dataset':item['dataset'], 'code':item['code'],
                              'status':entry['status']}), flush=True)
            if entry['status'] != 'ingested':
                break  # Stop on the first failure; do not push the account harder.
        run['provider_stats'] = executor.stats
    run['finished_at'] = datetime.now(timezone.utc).isoformat()
    with run_path.open('x',encoding='utf-8') as stream:
        json.dump(run, stream, ensure_ascii=False, indent=2)
    output = verify(plan, run, db, store)
    with replay_path.open('x',encoding='utf-8') as stream:
        json.dump(output, stream, indent=2)
    print(json.dumps(output))
    return 0 if output['configured_rate_sustained_verified'] else 2


if __name__=='__main__':
    raise SystemExit(main())
