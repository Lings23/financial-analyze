"""Frozen listing/halt document requests; source documents are not qualifications."""
import argparse
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path

from stock_research.domains import DomainDataset, DomainRequest, Subject
from stock_research.models import AccessContext, PITMode, QueryContext, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.documents import CNInfoAnnouncementProvider
from stock_research.providers.executor import ExecutionPolicy, ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

ROOT = Path('.artifacts/p17_20261001/formal/strata')
PLAN = Path('evaluation/p17_20261001_formal_strata_plan.json')


def write(path, data):
    with path.open('x',encoding='utf8') as stream: json.dump(data,stream,ensure_ascii=False,indent=2)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare-only',action='store_true'); parser.add_argument('--verify-only',action='store_true'); args = parser.parse_args()
    formal_path = Path('evaluation/p17_20261001_formal_plan.json'); formal = json.loads(formal_path.read_bytes())
    if args.prepare_only:
        if PLAN.exists(): raise ValueError('strata plan exists')
        requests = []
        for s in formal['securities']:
            if s['stratum'] != 'new_listing': continue
            day = date.fromisoformat(s['list_date'][:4]+'-'+s['list_date'][4:6]+'-'+s['list_date'][6:])
            requests.append({'symbol':s['symbol'],'exchange':s['exchange'],'start':(day-timedelta(days=10)).isoformat(),
                             'end':day.isoformat(),'selector':'上市公告书','metadata_listing_date':day.isoformat(),'purpose':'official listing-date proof'})
        requests.append({'symbol':'600301','exchange':'SSE','start':'2026-09-18','end':'2026-09-21',
                         'selector':'复牌','purpose':'qualify actual halt end, not projected duration'})
        plan = {'scope':'p17-formal-strata-20261001','formal_plan_sha256':hashlib.sha256(formal_path.read_bytes()).hexdigest(),
                'created_at':utcnow().isoformat(),'requests':requests,'max_attempts':1,'min_interval':2.5,
                'timeout_seconds':60,'rules':'Collect original PDFs; document dates do not upgrade PIT. Later qualification must cite actual text/page/code/date, not infer from title.',
                'code_sha256':{str(Path(__file__).relative_to(Path.cwd())):hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}}
        write(PLAN,plan);print(json.dumps({'requests':len(requests),'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest()}));return
    plan = json.loads(PLAN.read_bytes()); ROOT.mkdir(parents=True,exist_ok=True)
    assert plan['formal_plan_sha256'] == hashlib.sha256(formal_path.read_bytes()).hexdigest()
    store = ArtifactStore(ROOT/'artifacts'); db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf8').strip())
    registry = ProviderRegistry()
    if not args.verify_only: registry.register(CNInfoAnnouncementProvider(store))
    access = AccessContext(plan['scope'],frozenset({'cninfo'})); target = ROOT/'run.json'
    if args.verify_only:
        run = json.loads(target.read_text(encoding='utf8')); assert run['plan_sha256'] == hashlib.sha256(PLAN.read_bytes()).hexdigest()
        assert store.get(access.scope,run['plan_artifact_id']) == PLAN.read_bytes()
    else:
        if target.exists(): raise ValueError('strata evidence exists')
        for p, sha in plan['code_sha256'].items(): assert hashlib.sha256(Path(p).read_bytes()).hexdigest() == sha
        run = {'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),'plan_artifact_id':store.put_bytes(access.scope,PLAN.read_bytes()),
               'scope':access.scope,'started_at':utcnow().isoformat(),'results':[]}
    with ProviderExecutor(ExecutionPolicy(total_timeout=60,attempt_timeout=60,max_attempts=1,min_interval=2.5)) as executor:
        service = DataService(registry,executor,db,store)
        for index,item in enumerate(plan['requests']):
            req = DomainRequest(Subject('equity',item['symbol'],item['exchange']),DomainDataset.ANNOUNCEMENT,
                                date.fromisoformat(item['start']),date.fromisoformat(item['end']),item['selector'])
            if args.verify_only:
                entry = run['results'][index]; assert entry['request'] == item
            else:
                entry = {'request':item,'started_at':utcnow().isoformat()}
                try:
                    result = service.refresh(req,access,('cninfo',),use_cache=False)
                    entry.update(status='ingested',snapshot_id=result.snapshot.snapshot_id)
                except Exception as exc: entry.update(status='failed',error_type=type(exc).__name__)
            if entry['status'] == 'ingested':
                ctx = QueryContext(access,entry['snapshot_id'],utcnow(),PITMode.SYSTEM)
                records = service.query(req,ctx).records; files = []
                for r in records:
                    attrs = dict(r.attributes); aid = attrs['pdf_artifact_id']; data = service.evidence(req,ctx,r.record_id,aid)
                    pdf = ROOT/(item['symbol']+'_'+r.fact_id+'.pdf')
                    if args.verify_only: assert pdf.read_bytes() == data
                    else:
                        with pdf.open('xb') as stream: stream.write(data)
                    files.append({'record_id':r.record_id,'source_url':r.source_url,'pdf_sha256':aid,'path':str(pdf),
                                  'title':attrs['title'],'source_date':attrs['source_date']})
                if args.verify_only: assert entry['files'] == files
                else: entry['files'] = files
            if not args.verify_only:
                entry['finished_at'] = utcnow().isoformat(); run['results'].append(entry)
                print(json.dumps({'symbol':item['symbol'],'status':entry['status'],'pdfs':len(entry.get('files',[]))}),flush=True)
        if not args.verify_only: run['provider_stats'] = executor.stats
    if not args.verify_only:
        run['finished_at'] = utcnow().isoformat();write(target,run)
    print(json.dumps({'requests':len(run['results']),'pdfs':sum(len(e.get('files',[])) for e in run['results']),
                      'failed':sum(e['status'] != 'ingested' for e in run['results']),'qualification_automatic':False}))


if __name__ == '__main__': main()
