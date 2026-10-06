"""Independent SSE/SZSE comparison, with every registered cell retained."""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from exchange_http import get_reference
from run_p17_formal import PLAN, ROOT, request, write
from stock_research.models import AccessContext, PITMode, QueryContext, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.documents import DocumentHTTPTransport
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


def collect(plan, store):
    for p, sha in plan['code_sha256'].items(): assert hashlib.sha256(Path(p).read_bytes()).hexdigest() == sha
    sse, szse = plan['sse_reference'],plan['szse_reference']
    assert hashlib.sha256(Path(sse['renderer_path']).read_bytes()).hexdigest() == sse['renderer_sha256']
    for p, sha in szse['source_sha256'].items(): assert hashlib.sha256(Path(p).read_bytes()).hexdigest() == sha
    result = {'plan_sha256':hashlib.sha256(PLAN.read_bytes()).hexdigest(),'started_at':utcnow().isoformat(),
              'plan_artifact_id':store.put_bytes(plan['reference_scope'],PLAN.read_bytes()),'results':[],'halt_pdfs':[]}
    for s in plan['securities']:
        entry = {'symbol':s['symbol'],'exchange':s['exchange'],'started_at':utcnow().isoformat()}
        if s['exchange'] == 'BSE': entry.update(status='unavailable',reason='no_verified_official_endpoint',attempts=0)
        else:
            spec = sse if s['exchange'] == 'SSE' else szse
            url = ('https://yunhq.sse.com.cn:32042/v1/sh1/dayk/'+s['symbol']) if s['exchange'] == 'SSE' else szse['url']
            params = spec['params'] if s['exchange'] == 'SSE' else dict(spec['params'],code=s['symbol'])
            entry.update(url=url,params=params,attempts=1,retries=0)
            try:
                content = get_reference(url,params,spec['page_url'])
                body = json.loads(content,parse_float=Decimal)
                if s['exchange'] == 'SSE':
                    assert body['code'] == s['symbol']; rows = body['kline']; assert len(rows) < 600
                else:
                    assert body['code'] == '0' and body['data']['code'] == s['symbol']; rows = body['data']['picupdata']; assert len(rows) < 1000
                entry.update(status='collected',http_status=200,row_count=len(rows),
                             artifact_id=store.put_bytes(plan['reference_scope'],content))
            except Exception as exc: entry.update(status='failed',error_type=type(exc).__name__)
        entry['finished_at'] = utcnow().isoformat(); result['results'].append(entry)
        print(json.dumps({k:v for k,v in entry.items() if k not in {'params'}}),flush=True)
    for item in plan['halt_pdf_references']:
        entry = {'index_row':item,'started_at':utcnow().isoformat(),'attempts':1,'retries':0,
                 'url':'https://static.cninfo.com.cn/'+item['adjunctUrl']}
        try:
            content = DocumentHTTPTransport()(entry['url'],12,kind='pdf')
            entry.update(status='collected',artifact_id=store.put_bytes(plan['reference_scope'],content))
        except Exception as exc: entry.update(status='failed',error_type=type(exc).__name__)
        entry['finished_at'] = utcnow().isoformat(); result['halt_pdfs'].append(entry)
        print(json.dumps({'halt_symbol':item['secCode'],'status':entry['status']}),flush=True)
    result['finished_at'] = utcnow().isoformat()
    return result


def compare(plan, run, refs, db, store):
    sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert refs['plan_sha256'] == run['plan_sha256'] == sha
    assert store.get(plan['reference_scope'],refs['plan_artifact_id']) == PLAN.read_bytes()
    entries = {(e['exchange'],e['symbol']):e for e in refs['results']}
    assert len(entries) == len(plan['securities'])
    indices = {}
    for key,e in entries.items():
        indexed = {}
        if e['status'] == 'collected':
            body = json.loads(store.get(plan['reference_scope'],e['artifact_id']),parse_float=Decimal)
            if key[0] == 'SSE':
                assert body['code'] == key[1]; rows = body['kline']; assert all(len(r) == 7 for r in rows)
                indexed = {datetime.strptime(str(r[0]),'%Y%m%d').date().isoformat():r for r in rows}
            else:
                assert body['code'] == '0' and body['data']['code'] == key[1]
                rows, lower = body['data']['picupdata'],body['data']['picdowndata']
                assert len(rows) == len(lower) and all(len(r) == 9 for r in rows)
                assert all(a[0] == b[0] and a[7] == b[1] for a,b in zip(rows,lower))
                assert all(type(r[7]) is int for r in rows)
                indexed = {r[0]:r for r in rows}
            assert len(indexed) == len(rows) == e['row_count']
        indices[key] = indexed
    for e in refs['halt_pdfs']:
        if e['status'] == 'collected': assert store.get(plan['reference_scope'],e['artifact_id']).startswith(b'%PDF')
    access = AccessContext(plan['scope'],frozenset({'tushare'}))
    after = datetime.fromisoformat(run['finished_at'])+timedelta(seconds=1)
    records = {}
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(),executor,db,ArtifactStore(ROOT/'artifacts'))
        for e in run['results']:
            if e['status'] != 'ingested': continue
            req = request(e['request']); ctx = QueryContext(access,e['snapshot_id'],after,PITMode.SYSTEM)
            for r in service.query(req,ctx).records:
                key = (req.security.exchange,req.security.symbol,req.dataset.value,r.period.isoformat())
                assert key not in records
                for aid in r.artifact_ids: service.evidence(req,ctx,r.record_id,aid)
                records[key] = r
    cells, finance = [], []
    for s in plan['securities']:
        key = s['exchange'],s['symbol']; indexed = indices[key]; source = entries[key]
        rules = plan['szse_reference']['fields'] if key[0] == 'SZSE' else plan['sse_reference']['fields']
        for w in plan['daily_windows']:
            for day in w['dates']:
                r = records.get((*key,'market_daily',day)); ref = indexed.get(day)
                metrics = {m.name:m.value for m in r.metrics} if r else {}
                for name,rule in rules.items():
                    c = {'exchange':key[0],'symbol':key[1],'stratum':s['stratum'],'date':day,'field':name,
                         'record_id':r.record_id if r else None,'reference_artifact_id':source.get('artifact_id')}
                    if not r: c['status'] = 'missing_provider' if ref else 'missing_provider_and_reference'
                    elif name not in metrics or metrics[name] is None: c['status'] = 'provider_null'
                    elif ref is None: c['status'] = 'missing_reference'
                    else:
                        expected = Decimal(str(ref[rule['position']]))*Decimal(rule.get('multiplier','1'))
                        delta = metrics[name]-expected
                        c.update(actual=str(metrics[name]),reference=str(expected),difference=str(delta),tolerance=rule['tolerance'],
                                 status='match' if abs(delta) <= Decimal(rule['tolerance']) else 'mismatch',exact=delta == 0)
                    cells.append(c)
        for period in plan['financial_periods']:
            r = records.get((*key,'financial_income',period)); metrics = {m.name:m.value for m in r.metrics} if r else {}
            for name in plan['financial_fields']:
                finance.append({'exchange':key[0],'symbol':key[1],'stratum':s['stratum'],'period':period,'field':name,
                                'record_id':r.record_id if r else None,'status':'missing_provider' if not r else
                                'provider_null' if metrics.get(name) is None else 'missing_reference'})
    assert len(cells) == plan['potential_market_cells'] and len(finance) == plan['financial_cells']
    assert len({(c['exchange'],c['symbol'],c['date'],c['field']) for c in cells}) == len(cells)
    summary = dict(Counter(c['status'] for c in cells)); strata = defaultdict(Counter)
    for c in cells: strata[c['stratum']][c['status']] += 1
    compared = summary.get('match',0)+summary.get('mismatch',0)
    return {'checked_at':utcnow().isoformat(),'plan_sha256':sha,'registered_market_cells':len(cells),'market_status_counts':summary,
            'registered_financial_cells':len(finance),'financial_status_counts':dict(Counter(c['status'] for c in finance)),
            'market_compared':compared,'market_matched':summary.get('match',0),
            'exact_market_matches':sum(c.get('exact',False) for c in cells),
            'all_registered_numeric_cells_verified':summary.get('match',0) == len(cells) and all(c['status'] == 'match' for c in finance),
            'market_accuracy_among_compared':str(Decimal(summary.get('match',0))/Decimal(compared)) if compared else None,
            'strata':{k:dict(v) for k,v in strata.items()},'halt_absence_qualified':False,
            'whole_market_statistical_certification':False,'phase1_complete':False,'market_cells':cells,'financial_cells':finance}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--verify-only',action='store_true'); args = parser.parse_args()
    plan = json.loads(PLAN.read_bytes()); run = json.loads((ROOT/'run.json').read_text(encoding='utf8'))
    store = ArtifactStore(ROOT/'reference_artifacts'); path = ROOT/'references.json'
    if args.verify_only: refs = json.loads(path.read_text(encoding='utf8'))
    else:
        if path.exists(): raise ValueError('formal references exist; refusing overwrite')
        refs = collect(plan,store); write(path,refs)
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf8').strip())
    output = compare(plan,run,refs,db,store)
    if args.verify_only:
        prior = json.loads((ROOT/'comparison.json').read_text(encoding='utf8'))
        assert {k:v for k,v in output.items() if k != 'checked_at'} == {k:v for k,v in prior.items() if k != 'checked_at'}
    else: write(ROOT/'comparison.json',output)
    print(json.dumps({k:v for k,v in output.items() if k not in {'market_cells','financial_cells'}},ensure_ascii=False))
    return 0  # Completed audit may report failures/unverified; this exit is not an acceptance flag.


if __name__ == '__main__': raise SystemExit(main())
