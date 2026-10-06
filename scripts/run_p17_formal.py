"""Collect/replay pre-registered broader daily/income samples in persistent PG."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import time

from stock_research.__main__ import _project_tushare_token
from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.providers.tushare import TushareHTTPTransport, TushareProvider, _json_safe
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

PLAN = Path('evaluation/p17_20261001_formal_plan.json')
ROOT = Path('.artifacts/p17_20261001/formal')


def request(item):
    return DataRequest(Security(item['symbol'],item['exchange']),Dataset(item['dataset']),
                       date.fromisoformat(item['start']),date.fromisoformat(item['end']))


def requests(plan):
    for s in plan['securities']:
        for w in plan['daily_windows']:
            yield {'symbol':s['symbol'],'exchange':s['exchange'],'stratum':s['stratum'],
                   'dataset':'market_daily','start':w['start'],'end':w['end']}
        yield {'symbol':s['symbol'],'exchange':s['exchange'],'stratum':s['stratum'],
               'dataset':'financial_income','start':min(plan['financial_periods']),'end':max(plan['financial_periods'])}


def write(path, data):
    with path.open('x',encoding='utf8') as stream: json.dump(data,stream,ensure_ascii=False,indent=2)


def verify(plan, run, db, store):
    assert run['plan_sha256'] == hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert store.get(plan['scope'],run['plan_artifact_id']) == PLAN.read_bytes()
    for source in plan['population_sources']:
        assert hashlib.sha256(Path(source['run_path']).read_bytes()).hexdigest() == source['run_sha256']
        ArtifactStore(source['root']).get(source['scope'],source['artifact_id'])
    access = AccessContext(plan['scope'],frozenset({'tushare'}))
    after = datetime.fromisoformat(run['finished_at'])+timedelta(seconds=1)
    groups, artifacts = [], set()
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(),executor,db,store)
        for entry in run['results']:
            if entry['status'] != 'ingested': continue
            req = request(entry['request'])
            raw = db.read(access.scope,entry['snapshot_id'])
            assert sorted(r.record_id for r in raw) == entry['snapshot_record_ids']
            ctx = QueryContext(access,entry['snapshot_id'],after,PITMode.SYSTEM)
            records = service.query(req,ctx).records
            assert sorted(r.record_id for r in records) == entry['visible_record_ids']
            assert len(records) == entry['visible_count']
            denied = AccessContext(access.scope,frozenset({'cninfo'}))
            assert not service.query(req,QueryContext(denied,entry['snapshot_id'],after)).records
            try:
                service.query(req,QueryContext(AccessContext(access.scope+'-other',access.allowed_providers),entry['snapshot_id'],after))
            except PermissionDenied: pass
            else: raise AssertionError('wrong scope accepted')
            for r in records:
                assert r.availability_basis == 'observed_at'
                before = r.available_at-timedelta(microseconds=1)
                assert r.record_id not in {v.record_id for v in service.query(req,QueryContext(access,entry['snapshot_id'],before)).records}
                for aid in r.artifact_ids:
                    assert hashlib.sha256(service.evidence(req,ctx,r.record_id,aid)).hexdigest() == aid
                    artifacts.add(aid)
            groups.append({'request':entry['request'],'visible_count':len(records),'snapshot_unchanged':True,
                           'source_and_scope_authorization':True,'before_capture_invisible':True})
    starts = [c['monotonic_start'] for c in run['http_calls']]
    for c in run['http_calls']:
        if c.get('response_artifact_id'):
            body = json.loads(store.get(access.scope,c['response_artifact_id']))
            assert len(body['items']) == c['returned_rows'] and body['params'] == c['params']
            artifacts.add(c['response_artifact_id'])
    peak = max((sum(t <= s < t+60 for s in starts) for t in starts),default=0)
    interval = min((b-a for a,b in zip(starts,starts[1:])),default=None)
    return {'checked_at':utcnow().isoformat(),'plan_sha256':run['plan_sha256'],'verified_groups':len(groups),
            'http_calls':len(starts),'calls_by_api':dict(Counter(c['api_name'] for c in run['http_calls'])),
            'minimum_interval':round(interval,3) if interval is not None else None,'peak_calls_in_60_seconds':peak,
            'configured_rate_conforms':peak <= 24 and (interval is None or interval >= plan['min_interval_seconds']-0.01),
            'retries':run['provider_stats']['retries'],'cache_hits':run['provider_stats']['cache_hits'],
            'verified_source_artifacts':len(artifacts),'visible_records':sum(g['visible_count'] for g in groups),
            'requests_completed':len(groups) == len(list(requests(plan))) == len(starts),
            'numeric_quality_not_yet_verified':True,'groups':groups}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only',action='store_true')
    args = parser.parse_args()
    plan_raw = PLAN.read_bytes(); plan = json.loads(plan_raw)
    ROOT.mkdir(parents=True,exist_ok=True)
    store = ArtifactStore(ROOT/'artifacts')
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf8').strip())
    path = ROOT/'run.json'
    if args.verify_only:
        run = json.loads(path.read_text(encoding='utf8'))
        output = verify(plan,run,db,store)
        prior = json.loads((ROOT/'replay.json').read_text(encoding='utf8'))
        assert {k:v for k,v in output.items() if k != 'checked_at'} == {k:v for k,v in prior.items() if k != 'checked_at'}
    else:
        if path.exists(): raise ValueError('formal run exists; refusing overwrite')
        for p, expected in plan['code_sha256'].items(): assert hashlib.sha256(Path(p).read_bytes()).hexdigest() == expected
        run = {'scope':plan['scope'],'plan_sha256':hashlib.sha256(plan_raw).hexdigest(),
               'plan_artifact_id':store.put_bytes(plan['scope'],plan_raw),'started_at':utcnow().isoformat(),'results':[],'http_calls':[]}
        token = _project_tushare_token(); upstream = TushareHTTPTransport(); origin = time.monotonic()
        def transport(payload,timeout):
            call = {'api_name':payload['api_name'],'params':payload['params'],
                    'monotonic_start':time.monotonic()-origin,'started_at':utcnow().isoformat()}
            run['http_calls'].append(call)
            try:
                body = upstream(payload,timeout)
                call['business_code'] = body.get('code')
                call['returned_rows'] = len((body.get('data') or {}).get('items') or [])
                if body.get('code') == 0:
                    data = body['data']; fields = payload['fields'].split(','); response_fields = data['fields']
                    assert len(response_fields) == len(set(response_fields)) and set(fields) <= set(response_fields)
                    assert call['returned_rows'] < 10000
                    projected = []
                    for row in data['items']:
                        assert len(row) == len(response_fields)
                        cells = [_json_safe(row[response_fields.index(f)]) for f in fields]
                        assert all(type(v) in {str,int,float,bool,type(None)} for v in cells)
                        assert not any(isinstance(v,str) and token in v for v in cells)
                        projected.append(cells)
                    call['response_artifact_id'] = store.put(access.scope,{'api':payload['api_name'],'params':payload['params'],
                        'fields':fields,'items':projected,'started_at':call['started_at'],'finished_at':utcnow().isoformat()})
                return body
            except Exception as exc:
                call['error_type'] = type(exc).__name__; raise
            finally: call['finished_at'] = utcnow().isoformat()
        registry = ProviderRegistry(); registry.register(TushareProvider(token,store,transport))
        access = AccessContext(plan['scope'],frozenset({'tushare'}))
        policy = ExecutionPolicy(total_timeout=plan['total_timeout'],attempt_timeout=plan['attempt_timeout'],
                                 max_attempts=plan['max_attempts'],min_interval=plan['min_interval_seconds'],provider_concurrency=1)
        with ProviderExecutor(policy) as executor:
            service = DataService(registry,executor,db,store); parent = None
            for i,item in enumerate(requests(plan)):
                entry = {'request':item,'started_at':utcnow().isoformat()}
                try:
                    result = service.refresh(request(item),access,parent_snapshot_id=parent,use_cache=False)
                    parent = result.snapshot.snapshot_id
                    rows = service.query(request(item),QueryContext(access,parent,utcnow(),PITMode.SYSTEM)).records
                    entry.update(status='ingested',snapshot_id=parent,stored_count=result.record_count,visible_count=len(rows),
                                 visible_record_ids=sorted(r.record_id for r in rows),
                                 snapshot_record_ids=sorted(r.record_id for r in db.read(access.scope,parent)))
                except Exception as exc: entry.update(status='failed',error_type=type(exc).__name__)
                entry['finished_at'] = utcnow().isoformat(); run['results'].append(entry)
                print(json.dumps({'number':i+1,'symbol':item['symbol'],'dataset':item['dataset'],
                                  'status':entry['status'],'visible_count':entry.get('visible_count')}),flush=True)
                if entry['status'] == 'failed': break
            run['provider_stats'] = executor.stats
        run['finished_at'] = utcnow().isoformat(); write(path,run)
        output = verify(plan,run,db,store); write(ROOT/'replay.json',output)
    print(json.dumps({k:v for k,v in output.items() if k != 'groups'}))
    return 0 if output['requests_completed'] else 2


if __name__ == '__main__': raise SystemExit(main())
