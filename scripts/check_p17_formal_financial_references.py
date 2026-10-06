"""No-network authorized replay of all collected formal filing bytes."""
from collections import Counter
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path

from stock_research.domains import DomainDataset, DomainRequest, Subject
from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, PITMode, QueryContext, utcnow
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


def main():
    plan_path = Path('evaluation/p17_20261001_formal_financial_reference_plan.json')
    plan = json.loads(plan_path.read_bytes()); root = Path('.artifacts/p17_20261001/formal/financial_references')
    run = json.loads((root/'collection.json').read_text(encoding='utf8')); store = ArtifactStore(root/'artifacts')
    assert run['plan_sha256'] == hashlib.sha256(plan_path.read_bytes()).hexdigest()
    assert store.get(plan['scope'],run['plan_artifact']) == plan_path.read_bytes()
    assert len(run['requests']) == len(plan['requests']) == 75
    assert hashlib.sha256(Path(plan['original_run_path']).read_bytes()).hexdigest() == plan['original_run_sha256']
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf8').strip())
    access = AccessContext(plan['scope'],frozenset({'cninfo'})); after = datetime.fromisoformat(run['finished_at'])+timedelta(seconds=1)
    checks, reports = 0,[]
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(),executor,db,store)
        for expected,entry in zip(plan['requests'],run['requests']):
            assert entry['request'] == expected
            if entry['status'] == 'failed':
                assert 'snapshot_id' not in entry and not entry.get('files');continue
            req = DomainRequest(Subject('equity',expected['code'],expected['exchange']),DomainDataset.ANNOUNCEMENT,
                date.fromisoformat(expected['start_date']),date.fromisoformat(expected['end_date']),expected['selector'])
            ctx = QueryContext(access,entry['snapshot_id'],after,PITMode.SYSTEM)
            rows = service.query(req,ctx).records; byid = {r.record_id:r for r in rows}
            assert len(rows) == len(entry['files'])
            assert (entry['status'] == 'empty') == (len(rows) == 0)
            assert not service.query(req,QueryContext(AccessContext(access.scope,frozenset({'tushare'})),entry['snapshot_id'],after)).records
            try: service.query(req,QueryContext(AccessContext(access.scope+'-other',access.allowed_providers),entry['snapshot_id'],after))
            except PermissionDenied: pass
            else: raise AssertionError('scope authorization failed')
            for f in entry['files']:
                r = byid[f['record_id']]; attrs = dict(r.attributes)
                assert r.source_url == f['source_url'] and attrs['pdf_artifact_id'] == f['sha256']
                pdf = Path(f['path']).resolve(); assert pdf.is_relative_to(root.resolve())
                content = service.evidence(req,ctx,r.record_id,f['sha256'])
                assert content == pdf.read_bytes() and hashlib.sha256(content).hexdigest() == f['sha256']
                assert not service.query(req,QueryContext(access,entry['snapshot_id'],r.available_at-timedelta(microseconds=1))).records
                service.evidence(req,ctx,r.record_id,f['source_index_artifact']); checks += 1
            reports.append({'code':expected['code'],'period':expected['period'],'status':entry['status'],'pdfs':len(rows),
                            'source_scope_pit_and_hash_passed':True})
    output = {'checked_at':utcnow().isoformat(),'plan_sha256':run['plan_sha256'],'registered_periods':75,
              'status_counts':dict(Counter(e['status'] for e in run['requests'])),'verified_pdfs':checks,
              'provider_attempts':run['provider_stats']['attempts'],'retries':run['provider_stats']['retries'],
              'uncollected':[{'code':e['request']['code'],'period':e['request']['period'],'status':e['status'],
                             'error_type':e.get('error_type')} for e in run['requests'] if e['status'] != 'collected'],
              'registered_financial_cells':225,'financial_numeric_comparisons_completed':0,
              'pdf_presence_is_not_numeric_truth':True,'phase1_complete':False,'groups':reports}
    target = root/'replay.json'
    if target.exists():
        prior = json.loads(target.read_text(encoding='utf8'));assert {k:v for k,v in prior.items() if k != 'checked_at'} == {k:v for k,v in output.items() if k != 'checked_at'}
    else:
        with target.open('x',encoding='utf8') as stream: json.dump(output,stream,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in output.items() if k not in {'groups','uncollected'}},ensure_ascii=False))


if __name__ == '__main__': main()
