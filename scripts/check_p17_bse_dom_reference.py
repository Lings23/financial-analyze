"""Seal observed tooltip bytes before authorized fixed-snapshot comparison."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit,parse_qs

from stock_research.models import AccessContext,DataRequest,Dataset,PITMode,QueryContext,Security
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository

PLAN=Path('evaluation/p17_20261001_bse_dom_reference_plan.json')
PROJECTION=Path('evaluation/p17_20261001_bse_dom_920510_recent_projection.json')
ROOT=Path('.artifacts/p17_20261001/bse_dom_reference/920510_recent')
PLAN_SHA='6a233c99345232c2adc59b8208b8f9daed7e527447c57fdc7e47bd6ba4927b7c'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


def references(payload,plan):
    source=json.loads(payload)
    assert source['plan_sha256']==PLAN_SHA and source['source_kind']=='limited_observed_rendered_daily_tooltip_projection'
    parts=urlsplit(source['url'])
    assert parts.scheme=='https' and parts.hostname=='www.bse.cn' and parts.port is None
    assert not parts.username and not parts.password and not parts.fragment
    assert parts.path=='/products/neeq_listed_companies/company_time_sharing.html'
    assert parse_qs(parts.query)=={'companyCode':['920510'],'typename':['G']}
    assert source['page_company_text']=='丰光精密 股票代码： 920510'
    result={}
    for row in source['rows']:
        assert row['code']=='920510' and row['name']=='丰光精密'
        observed=datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'))
        assert observed.tzinfo is not None and observed>=datetime.fromisoformat(plan['created_at'])
        lines=row['tooltip'].splitlines();day=date.fromisoformat(lines[0]).isoformat()
        assert day in plan['windows'][1]['dates']
        first=re.fullmatch(r'最低 : (\d+\.\d{2}) 收盘 : (\d+\.\d{2})',lines[1])
        second=re.fullmatch(r'开盘 : (\d+\.\d{2}) 最高 : (\d+\.\d{2})',lines[2])
        quantity=re.fullmatch(r'成交量 : (\d+\.\d{2})\(万股\)',lines[3])
        amount=re.fullmatch(r'成交额 : (\d+\.\d{2})\(万元\)',lines[4])
        assert first and second and quantity and amount and len(lines)==7
        values=dict(low=first[1],close=first[2],open=second[1],high=second[2],volume=quantity[1],amount=amount[1])
        assert Decimal(values['low'])<=min(Decimal(values['open']),Decimal(values['close']))
        assert Decimal(values['high'])>=max(Decimal(values['open']),Decimal(values['close']))
        key=row['code'],day;assert key not in result
        result[key]={'values':values,'observed_at':row['observed_at']}
    assert len(result)==8 and {day for code,day in result}==set(plan['windows'][1]['dates'])
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seal',action='store_true');parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args();assert digest(PLAN)==PLAN_SHA
    plan=json.loads(PLAN.read_bytes());ROOT.mkdir(parents=True,exist_ok=True);store=ArtifactStore(ROOT/'artifacts')
    for path,expected in plan['baseline_sha256'].items():assert digest(path)==expected
    manifest_path=ROOT/'manifest.json'
    if args.seal:
        if manifest_path.exists():raise ValueError('reference already sealed')
        payload=PROJECTION.read_bytes();refs=references(payload,plan)
        manifest={'sealed_at':datetime.now(timezone.utc).isoformat(),'plan_sha256':PLAN_SHA,
                  'projection_sha256':digest(PROJECTION),'projection_artifact_id':store.put_bytes(plan['scope'],payload),
                  'comparison_code_sha256':digest(__file__),'reference_security_days':len(refs),'reference_cells':48,
                  'limited_dom_projection_only':True,'no_tushare_comparison_before_seal':True}
        write(manifest_path,manifest);print(json.dumps(manifest));return 0
    manifest=json.loads(manifest_path.read_bytes());assert manifest['plan_sha256']==PLAN_SHA
    assert digest(__file__)==manifest['comparison_code_sha256'] and digest(PROJECTION)==manifest['projection_sha256']
    payload=store.get(plan['scope'],manifest['projection_artifact_id']);assert hashlib.sha256(payload).hexdigest()==manifest['projection_sha256']
    refs=references(payload,plan)
    db=PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    access=AccessContext(plan['original_scope'],frozenset({'tushare'}))
    ctx=QueryContext(access,plan['snapshot_id'],datetime.fromisoformat(plan['original_finished_at'])+timedelta(seconds=1),PITMode.SYSTEM)
    cells=[]
    with ProviderExecutor() as executor:
        service=DataService(ProviderRegistry(),executor,db,ArtifactStore(plan['original_artifacts']))
        for security in plan['securities']:
            for window in plan['windows']:
                req=DataRequest(Security(security['symbol'],'BSE'),Dataset.MARKET_DAILY,date.fromisoformat(window['start']),date.fromisoformat(window['end']))
                records={r.period.isoformat():r for r in service.query(req,ctx).records}
                for record in records.values():
                    for aid in record.artifact_ids:service.evidence(req,ctx,record.record_id,aid)
                for day in window['dates']:
                    record=records.get(day);metrics={m.name:m.value for m in record.metrics} if record else {}
                    ref=refs.get((security['symbol'],day))
                    for field,rule in plan['rules'].items():
                        cell={'symbol':security['symbol'],'exchange':'BSE','date':day,'field':field,'record_id':record.record_id if record else None}
                        if not record:cell['status']='missing_provider'
                        elif metrics.get(field) is None:cell['status']='provider_null'
                        elif not ref:cell['status']='missing_reference'
                        else:
                            value=Decimal(ref['values'][field])*Decimal(rule.get('multiplier','1'));delta=metrics[field]-value
                            cell.update(actual=str(metrics[field]),reference=str(value),difference=str(delta),tolerance=rule['tolerance'],exact=delta==0,
                                        reference_artifact_id=manifest['projection_artifact_id'],reference_observed_at=ref['observed_at'],
                                        status='match' if abs(delta)<=Decimal(rule['tolerance']) else 'mismatch')
                        cells.append(cell)
    assert len(cells)==510
    formal=json.loads(Path('.artifacts/p17_20261001/formal/comparison.json').read_bytes())
    merged={(c['symbol'],c['date'],c['field']):dict(c) for c in formal['market_cells']}
    archive=json.loads(Path('.artifacts/p17_20261001/szse_archive/comparison.json').read_bytes())
    for cell in archive['cells']:
        if cell['group']!='formal':continue
        key=cell['code'],cell['date'],cell['field'];old=merged[key]
        assert old['status']=='missing_reference' and old['record_id']==cell['record_id']
        merged[key]=dict(old,**{k:v for k,v in cell.items() if k not in {'group','code'}})
    for cell in cells:
        key=cell['symbol'],cell['date'],cell['field'];old=merged[key]
        assert old['exchange']=='BSE' and old['status']=='missing_reference' and old['record_id']==cell['record_id']
        merged[key]=cell
    assert len(merged)==2550
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'plan_sha256':PLAN_SHA,'manifest_sha256':digest(manifest_path),
            'registered_bse_cells':510,'reference_cells':48,'bse_status_counts':dict(Counter(c['status'] for c in cells)),
            'formal_status_counts':dict(Counter(c['status'] for c in merged.values())),'cells':cells,
            'historical_publication_not_upgraded':True,'runtime_providers_unchanged':True,'phase1_complete':False}
    target=ROOT/'comparison.json'
    if args.verify_only:
        old=json.loads(target.read_bytes());assert {k:v for k,v in old.items() if k!='checked_at'}=={k:v for k,v in report.items() if k!='checked_at'}
    else:write(target,report)
    print(json.dumps({k:v for k,v in report.items() if k!='cells'}))
    return 2 if report['bse_status_counts'].get('mismatch',0) else 0


if __name__=='__main__':raise SystemExit(main())
