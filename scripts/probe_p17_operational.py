"""Bounded fresh P1.7 standard-archive checks and announcement-time entitlement probe."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import time

from stock_research.__main__ import _project_tushare_token
from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.providers.tushare import TushareHTTPTransport, TushareProvider, _json_safe
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


def main():
    root = Path('.artifacts/p17_20261001/operational')
    root.mkdir(parents=True,exist_ok=True)
    target = root/'run.json'
    if target.exists(): raise ValueError('original operational evidence exists')
    scope = 'p17-standard-archive-20261001'
    artifacts = ArtifactStore(root/'artifacts')
    token = _project_tushare_token()
    requests = [DataRequest(Security('600000','SSE'),Dataset.MARKET_DAILY,date(2024,9,18),date(2024,9,30)),
                DataRequest(Security('600000','SSE'),Dataset.FINANCIAL_INCOME,date(2024,12,31),date(2024,12,31))]
    plan = {'scope':scope,'requests':[r.identity() for r in requests],
            'announcement_probe':{'api':'anns_d','ts_code':'300122.SZ','ann_date':'20250422',
                                  'fields':['ann_date','ts_code','name','title','url','rec_time']},
            'max_attempts':1,'min_interval':1.5,'purpose':'Cross-date current reachability and standard requested-field archival; not sustained quota certification'}
    plan_aid = artifacts.put(scope,plan)
    registry = ProviderRegistry()
    registry.register(TushareProvider(token,artifacts))
    repo = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    access = AccessContext(scope,frozenset({'tushare'}))
    outcome = {'scope':scope,'pre_registered_plan_artifact':plan_aid,'requests':[]}
    with ProviderExecutor(ExecutionPolicy(total_timeout=30,attempt_timeout=30,max_attempts=1,min_interval=1.5)) as executor:
        service = DataService(registry,executor,repo,artifacts)
        for req in requests:
            result = service.refresh(req,access,use_cache=False)
            ctx = QueryContext(access,result.snapshot.snapshot_id,datetime.now(timezone.utc),PITMode.SYSTEM)
            records = service.query(req,ctx).records
            assert records
            record = records[0]
            raw = json.loads(service.evidence(req,ctx,record.record_id))
            assert raw['archive_schema']=='tushare_requested_response_v2'
            assert len(raw['items'])==raw['response_row_count']
            assert token not in json.dumps(raw)
            pre = service.query(req,QueryContext(access,result.snapshot.snapshot_id,
                         min(r.available_at for r in records)-timedelta(microseconds=1)))
            assert not pre.records
            outcome['requests'].append({'dataset':req.dataset.value,'snapshot_id':result.snapshot.snapshot_id,
                     'visible_count':len(records),'raw_row_count':raw['response_row_count'],
                     'selected_row_count':raw['selected_row_count'],'raw_artifact_id':record.artifact_id,
                     'all_requested_rows_preserved':True,'before_capture_count':len(pre.records),
                     'started_at':raw['started_at'],'finished_at':raw['finished_at']})
        outcome['provider_stats'] = executor.stats
    time.sleep(1.5)
    fields = plan['announcement_probe']['fields']
    params = {'ts_code':'300122.SZ','ann_date':'20250422'}
    try:
        response = TushareHTTPTransport()({'api_name':'anns_d','token':token,'params':params,'fields':','.join(fields)},20)
        code = response.get('code')
        data = response.get('data') or {}
        actual_fields, rows = data.get('fields') or [],data.get('items') or []
        safe_rows = [{f:_json_safe(dict(zip(actual_fields,row)).get(f)) for f in fields} for row in rows]
        if token in json.dumps(safe_rows): raise ValueError('credential reflected')
        aid = artifacts.put(scope,{'api_name':'anns_d','params':params,'requested_fields':fields,
                                 'business_code':code,'requested_response_rows':safe_rows})
        outcome['announcement_time_probe'] = {'business_code':code,'row_count':len(rows),'artifact_id':aid,
                 'status':'returned' if code==0 else 'permission_denied' if code in {2002,40203} else 'rejected',
                 'historical_release_verified':False}
    except Exception as exc:
        outcome['announcement_time_probe'] = {'status':'failed','error_type':type(exc).__name__,
                                              'historical_release_verified':False}
    outcome['checked_at'] = datetime.now(timezone.utc).isoformat()
    with target.open('x',encoding='utf-8') as stream: json.dump(outcome,stream,ensure_ascii=False,indent=2)
    print(json.dumps(outcome))


if __name__=='__main__': main()
