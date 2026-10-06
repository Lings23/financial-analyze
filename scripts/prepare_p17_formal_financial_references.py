"""Freeze original filing requests for all 75 registered financial periods."""
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path

from run_p17_formal import PLAN, ROOT, request
from stock_research.models import AccessContext, PITMode, QueryContext, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


def main():
    target = Path('evaluation/p17_20261001_formal_financial_reference_plan.json')
    if target.exists(): raise ValueError('financial reference plan already exists')
    plan = json.loads(PLAN.read_bytes()); run = json.loads((ROOT/'run.json').read_text(encoding='utf8'))
    assert run['plan_sha256'] == hashlib.sha256(PLAN.read_bytes()).hexdigest()
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf8').strip())
    access = AccessContext(plan['scope'],frozenset({'tushare'})); requests = []
    after = datetime.fromisoformat(run['finished_at'])+timedelta(seconds=1)
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(),executor,db,ArtifactStore(ROOT/'artifacts'))
        for e in run['results']:
            if e['request']['dataset'] != 'financial_income' or e['status'] != 'ingested': continue
            req = request(e['request']); ctx = QueryContext(access,e['snapshot_id'],after,PITMode.SYSTEM)
            for r in sorted(service.query(req,ctx).records,key=lambda r:r.period):
                assert r.period.isoformat() in plan['financial_periods']
                service.evidence(req,ctx,r.record_id)
                day = datetime.strptime(str(r.revision_order),'%Y%m%d').date()
                selector = {'2024-12-31':'2024年年度报告','2025-03-31':'季度报告','2025-06-30':'2025年半年度报告'}[r.period.isoformat()]
                requests.append({'code':req.security.symbol,'exchange':req.security.exchange,'period':r.period.isoformat(),
                    'announcement_date':r.announcement_date.isoformat(),'effective_provider_announcement_date':day.isoformat(),
                    'start_date':(day-timedelta(days=1)).isoformat(),'end_date':(day+timedelta(days=1)).isoformat(),
                    'selector':selector,'original_record_id':r.record_id,'original_snapshot':e['snapshot_id'],
                    'fields':plan['financial_fields']})
    assert len(requests) == 75 and len({(r['code'],r['period']) for r in requests}) == 75
    output = {'scope':'p17-formal-financial-reference-20261001','created_at':utcnow().isoformat(),'requests':requests,
              'original_scope':plan['scope'],'original_plan_sha256':run['plan_sha256'],'original_run_path':str(ROOT/'run.json'),
              'original_run_sha256':hashlib.sha256((ROOT/'run.json').read_bytes()).hexdigest(),'min_interval_seconds':2.5,
              'purpose':'Every registered financial period; independent financial values not consulted for reference selection',
              'rules':'Current Tushare ann/f_ann metadata selects a three-date search window; actual official index date is separate. Generic quarter title covers 第一季度/一季度 variants. Original consolidated cumulative same-version printed fields only; no aliases or missing-as-zero. Current capture is observed_at, not historical publication proof.',
              'code_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in
                ['scripts/prepare_p17_formal_financial_references.py','scripts/collect_p17_reference_extension.py','src/stock_research/providers/documents.py']}}
    with target.open('x',encoding='utf8') as stream: json.dump(output,stream,ensure_ascii=False,indent=2)
    print(json.dumps({'requests':len(requests),'cells':225,'plan_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))


if __name__ == '__main__': main()
