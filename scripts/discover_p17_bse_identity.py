"""Bounded official index discovery for missing historical security identities."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from stock_research.models import utcnow
from stock_research.providers.documents import DocumentHTTPTransport
from stock_research.storage.artifacts import ArtifactStore

ROOT = Path('.artifacts/p17_20261001/formal/bse_identity_discovery')
PLAN = Path('evaluation/p17_20261001_bse_identity_discovery_plan.json')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.prepare_only:
        requests = [{'code':code,'start':'2025-01-01','end':'2025-10-10','selector':'证券代码'}
                    for code in ('920110','920510','920489','920175')]
        requests.append({'code':'000016','start':'2026-04-28','end':'2026-04-30','selector':'2025年年度报告'})
        plan = {'scope':'p17-bse-identity-discovery-20261001','requests':requests,
                'reason':'Official code-change identity evidence and restated comparative-period report discovery; no aliases or financial facts accepted.',
                'max_pages':1,'page_size':100,'timeout_seconds':12,'min_interval_seconds':2.5,
                'single_attempt_per_request':True,'accept_historical_identity':False}
        with PLAN.open('x',encoding='utf8') as stream: json.dump(plan,stream,ensure_ascii=False,indent=2)
        print(json.dumps({'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),'requests':len(requests)}))
        return
    plan = json.loads(PLAN.read_bytes())
    store = ArtifactStore(ROOT/'artifacts')
    target = ROOT/'run.json'
    if args.verify_only:
        run = json.loads(target.read_bytes())
        assert store.get(plan['scope'],run['plan_artifact_id']) == PLAN.read_bytes()
        assert len(run['results']) == len(plan['requests']) == 5
        for item, entry in zip(plan['requests'],run['results']):
            assert item == entry['request']
            if entry['status'] == 'failed': continue
            body = json.loads(store.get(plan['scope'],entry['artifact_id']))
            assert body['form']['searchkey'] == item['selector']
            assert body['form']['seDate'] == item['start']+'~'+item['end']
            assert len(body['rows']) == entry['row_count'] <= 100
            assert entry['returned_codes'] == sorted({r['secCode'] for r in body['rows']})
        print(json.dumps({'verified_requests':5,'financial_facts_or_aliases_accepted':False}))
        return
    if target.exists(): raise ValueError('identity discovery already exists')
    ROOT.mkdir(parents=True,exist_ok=True)
    run = {'scope':plan['scope'],'plan_artifact_id':store.put_bytes(plan['scope'],PLAN.read_bytes()),
           'started_at':utcnow().isoformat(),'results':[]}
    transport = DocumentHTTPTransport()
    directory = transport('https://www.cninfo.com.cn/new/data/szse_stock.json',plan['timeout_seconds'])
    assert isinstance(directory.get('stockList'),list)
    for item in plan['requests']:
        entry = {'request':item,'started_at':utcnow().isoformat()}
        try:
            matches = [r for r in directory['stockList'] if r.get('code') == item['code']]
            assert len(matches) == 1 and matches[0].get('orgId')
            mapping = {k:matches[0][k] for k in ('code','orgId')}
            form = {'pageNum':'1','pageSize':'100','column':'szse','tabName':'fulltext','plate':'',
                    'stock':mapping['code']+','+mapping['orgId'],'searchkey':item['selector'],'secid':'','category':'',
                    'trade':'','seDate':item['start']+'~'+item['end'],'sortName':'','sortType':'','isHLtitle':'false'}
            body = transport('https://www.cninfo.com.cn/new/hisAnnouncement/query',plan['timeout_seconds'],form=form)
            rows = body.get('announcements') or []
            assert isinstance(rows,list) and len(rows) <= 100 and type(body['totalAnnouncement']) is int
            projected = [{k:r[k] for k in ('secCode','announcementId','announcementTitle','announcementTime','adjunctUrl')} for r in rows]
            aid = store.put(plan['scope'],{'mapping':mapping,'form':form,'rows':projected,'total':body['totalAnnouncement']})
            entry.update(status='collected',row_count=len(rows),reported_total=body['totalAnnouncement'],
                         artifact_id=aid,returned_codes=sorted({r['secCode'] for r in projected}),
                         titles=[r['announcementTitle'] for r in projected],full_index_coverage_claimed=False)
        except Exception as exc: entry.update(status='failed',error_type=type(exc).__name__)
        entry['finished_at'] = utcnow().isoformat()
        run['results'].append(entry)
        print(json.dumps({k:v for k,v in entry.items() if k != 'request'},ensure_ascii=False),flush=True)
        time.sleep(plan['min_interval_seconds'])
    run['finished_at'] = utcnow().isoformat()
    with target.open('x',encoding='utf8') as stream: json.dump(run,stream,ensure_ascii=False,indent=2)


if __name__ == '__main__': main()
