"""Bounded capture of the original 25-task missing domains; no model dispatch.

Public query parameters go only to the configured official Tushare transport.
No production DB writes, historical backdating, retries, or silent fallback.
"""
from datetime import date, timedelta
import json
from pathlib import Path
import time

from accept_phase2_real import write
from phase3_followup import sha
from stock_research.__main__ import _project_tushare_token
from stock_research.domains import DomainDataset, DomainRequest, Subject
from stock_research.models import AccessContext, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.providers.tushare_domains import TushareDomainProvider
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.memory import MemoryRepository


ROOT=Path('.artifacts/phase3/fullscope-20261003/domains')
SOURCE=Path('.artifacts/phase3/quality-20261002/proposed-model-manifest.json')
SCOPE='phase3-fullscope-domains-20261003'


def request(item):
    return DomainRequest(Subject(item['kind'],item['code'],item.get('exchange')),
                         DomainDataset(item['dataset']),date.fromisoformat(item['start']),date.fromisoformat(item['end']))


def capture():
    ROOT.mkdir(parents=True,exist_ok=False)
    source=json.loads(SOURCE.read_bytes())
    cases=[c for c in source['cases'] if c['kind']=='real_archived_income_projection']
    assert len(cases)==25
    queries=[]
    for case in cases:
        r=case['request']
        for dataset,start,end in (('adjustment_factor','2026-09-15','2026-09-25'),
                                   ('financial_cashflow','2025-06-30','2025-06-30')):
            queries.append({'case':case['id'],'kind':'equity','code':r['symbol'],'exchange':r['exchange'],
                            'dataset':dataset,'start':start,'end':end})
    queries.append({'case':'shared-benchmark','kind':'index','code':'000300.SH','dataset':'index_daily',
                    'start':'2026-09-15','end':'2026-09-25'})
    write(ROOT/'plan.json',{'source_manifest_sha256':sha(SOURCE),'scope':SCOPE,'queries':queries,
                           'limits':{'calls':51,'seconds':300,'attempt_timeout':30,'max_attempts':1,'min_interval':2.5},
                           'endpoint':'https://api.tushare.pro','model_calls':0,'availability':'observed_at_only'})
    artifacts=ArtifactStore(ROOT/'artifacts'); repo=MemoryRepository(); registry=ProviderRegistry()
    registry.register(TushareDomainProvider(_project_tushare_token(),artifacts))
    access=AccessContext(SCOPE,frozenset({'tushare'})); outcomes=[]
    started=utcnow(); deadline=time.monotonic()+300
    with ProviderExecutor(ExecutionPolicy(total_timeout=30,attempt_timeout=30,max_attempts=1,
                                         min_interval=2.5,provider_concurrency=1)) as executor:
        svc=DataService(registry,executor,repo,artifacts)
        for n,item in enumerate(queries):
            remaining=deadline-time.monotonic()
            if remaining<30:
                outcome={'query':item,'status':'not_dispatched_root_deadline'}
            else:
                write(ROOT/f'intent-{n+1}.json',{'query':item,'started_at':utcnow().isoformat(),
                                                'attempt':1,'unknown_outcome_must_not_retry':True})
                try:
                    result=svc.refresh(request(item),access,('tushare',),use_cache=False)
                    rows=repo.read(SCOPE,result.snapshot.snapshot_id)
                    outcome={'query':item,'status':'captured' if rows else 'empty','snapshot':result.snapshot.snapshot_id,
                             'records':[r.to_dict() for r in rows],'warnings':list(result.warnings)}
                except Exception as exc:
                    outcome={'query':item,'status':'failed','error_type':type(exc).__name__}
            write(ROOT/f'capture-{n+1}.json',outcome); outcomes.append(outcome)
            print(json.dumps({'sequence':n+1,'case':item['case'],'dataset':item['dataset'],'status':outcome['status'],
                              'records':len(outcome.get('records',[]))}),flush=True)
        final={'scope':SCOPE,'started_at':started.isoformat(),'finished_at':utcnow().isoformat(),
               'plan_sha256':sha(ROOT/'plan.json'),'provider_stats':executor.stats,'results':outcomes,
               'model_calls':0,'historical_visibility_or_source_accuracy_certified':False}
        write(ROOT/'result.json',final)
        print(json.dumps({'captured':sum(r['status']=='captured' for r in outcomes),
                          'empty':sum(r['status']=='empty' for r in outcomes),'queries':len(outcomes),
                          'provider_stats':executor.stats}))


if __name__=='__main__': capture()
