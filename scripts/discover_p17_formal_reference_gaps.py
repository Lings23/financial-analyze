"""Four bounded public-index diagnostics; no source facts or alias acceptance."""
from datetime import date, timedelta
import json
from pathlib import Path
import time

from stock_research.models import utcnow
from stock_research.providers.documents import DocumentHTTPTransport
from stock_research.storage.artifacts import ArtifactStore


def main():
    root=Path('.artifacts/p17_20261001/formal/reference_gap_discovery');root.mkdir(parents=True,exist_ok=True)
    target=root/'run.json'
    if target.exists():raise ValueError('gap discovery exists; refusing overwrite')
    plan_path=Path('evaluation/p17_20261001_formal_financial_reference_plan.json'); plan=json.loads(plan_path.read_bytes())
    requests=[]
    for code in ('601528','920110','000016'):
        item=next(r for r in plan['requests'] if r['code']==code and r['period']=='2024-12-31')
        requests.append({'code':code,'start':item['start_date'],'end':item['end_date'],'selector':item['selector'],
                         'reason':'Original failed/empty financial reference, inspect explicit public row identities'})
    requests.append({'code':'920016','start':'2024-09-03','end':'2024-09-13','selector':'上市',
                     'reason':'Original listing-book search empty; broader explicit title discovery only'})
    scope='p17-formal-gap-discovery-20261001';store=ArtifactStore(root/'artifacts');transport=DocumentHTTPTransport()
    frozen={'scope':scope,'requests':requests,'max_pages':1,'page_size':100,'single_attempt_per_request':True,
            'min_interval_seconds':2.5,'timeout_seconds':12,'facts_or_aliases_accepted':False}
    run={'scope':scope,'plan_artifact_id':store.put(scope,frozen),'started_at':utcnow().isoformat(),'results':[]}
    directory=transport('https://www.cninfo.com.cn/new/data/szse_stock.json',12)
    for item in requests:
        entry={'request':item,'started_at':utcnow().isoformat()}
        try:
            matches=[r for r in directory['stockList'] if r['code']==item['code']];assert len(matches)==1
            mapping={k:matches[0][k] for k in ('code','orgId')};entry['mapping']=mapping
            form={'pageNum':'1','pageSize':'100','column':'szse','tabName':'fulltext','plate':'',
                  'stock':mapping['code']+','+mapping['orgId'],'searchkey':item['selector'],'secid':'','category':'',
                  'trade':'','seDate':item['start']+'~'+item['end'],'sortName':'','sortType':'','isHLtitle':'false'}
            body=transport('https://www.cninfo.com.cn/new/hisAnnouncement/query',12,form=form)
            rows=body.get('announcements') or [];assert len(rows)<=100
            projected=[{k:r[k] for k in ('secCode','announcementId','announcementTitle','announcementTime','adjunctUrl')} for r in rows]
            entry.update(status='collected',row_count=len(rows),reported_total=body['totalAnnouncement'],
                artifact_id=store.put(scope,{'mapping':mapping,'form':form,'rows':projected,'total':body['totalAnnouncement']}),
                returned_codes=sorted({r['secCode'] for r in projected}),
                titles=[r['announcementTitle'] for r in projected],full_index_coverage_claimed=False)
        except Exception as exc:entry.update(status='failed',error_type=type(exc).__name__)
        entry['finished_at']=utcnow().isoformat();run['results'].append(entry)
        print(json.dumps({k:v for k,v in entry.items() if k not in {'request','mapping','titles'}},ensure_ascii=False),flush=True);time.sleep(2.5)
    run['finished_at']=utcnow().isoformat()
    with target.open('x',encoding='utf8') as stream:json.dump(run,stream,ensure_ascii=False,indent=2)


if __name__=='__main__':main()
