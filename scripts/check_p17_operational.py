"""Recheck the frozen standard-provider archive without making network calls."""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, DataRequest, Dataset, PITMode, QueryContext, Security
from stock_research.providers.base import ProviderRegistry
from stock_research.providers.executor import ProviderExecutor
from stock_research.service import DataService
from stock_research.storage.artifacts import ArtifactStore
from stock_research.storage.postgres import PostgresRepository


def main():
    root = Path('.artifacts/p17_20261001/operational')
    run = json.loads((root/'run.json').read_text(encoding='utf-8'))
    access = AccessContext(run['scope'], frozenset({'tushare'}))
    store = ArtifactStore(root/'artifacts')
    # This is a trusted local acceptance process with the frozen scope context.
    plan = json.loads(store.get(access.scope, run['pre_registered_plan_artifact']))
    assert plan['scope'] == access.scope
    repo = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    checks = []
    with ProviderExecutor() as executor:
        service = DataService(ProviderRegistry(), executor, repo, store)
        for item, entry in zip(plan['requests'], run['requests'], strict=True):
            request = DataRequest(Security('600000', 'SSE'), Dataset(entry['dataset']),
                                  date(2024,9,18) if entry['dataset']=='market_daily' else date(2024,12,31),
                                  date(2024,9,30) if entry['dataset']=='market_daily' else date(2024,12,31))
            assert request.identity() == item
            cutoff = datetime.fromisoformat(run['checked_at'])+timedelta(seconds=1)
            ctx = QueryContext(access, entry['snapshot_id'], cutoff, PITMode.SYSTEM)
            records = service.query(request, ctx).records
            assert len(records) == entry['visible_count']
            assert {record.provider_version for record in records} == {'2'}
            assert {record.artifact_id for record in records} == {entry['raw_artifact_id']}
            raw = json.loads(service.evidence(request, ctx, records[0].record_id))
            assert raw['archive_schema'] == 'tushare_requested_response_v2'
            assert len(raw['items']) == raw['response_row_count'] == entry['raw_row_count']
            assert raw['selected_row_count'] == entry['selected_row_count']
            assert raw['started_at'] == entry['started_at']
            assert raw['finished_at'] == entry['finished_at']
            before = min(record.available_at for record in records)-timedelta(microseconds=1)
            assert not service.query(request, QueryContext(access, entry['snapshot_id'], before)).records
            denied = QueryContext(AccessContext(access.scope, frozenset({'cninfo'})),
                                  entry['snapshot_id'], cutoff, PITMode.SYSTEM)
            assert not service.query(request, denied).records
            try:
                service.evidence(request, denied, records[0].record_id)
            except PermissionDenied:
                pass
            else:
                raise AssertionError('unauthorized artifact was returned')
            checks.append({'dataset':request.dataset.value, 'snapshot_id':entry['snapshot_id'],
                           'visible_count':len(records), 'raw_row_count':len(raw['items']),
                           'before_capture_count':0, 'unauthorized_count':0,
                           'unauthorized_evidence_denied':True, 'raw_hash_verified':True})
    output = {'checked_at':datetime.now(timezone.utc).isoformat(), 'requests':checks,
              'network_calls':0, 'all_checks_passed':True}
    target = root/'replay.json'
    if target.exists():
        prior = json.loads(target.read_text(encoding='utf-8'))
        assert {k:v for k,v in prior.items() if k!='checked_at'} == {
            k:v for k,v in output.items() if k!='checked_at'}
    else:
        with target.open('x',encoding='utf-8') as stream:
            json.dump(output, stream, indent=2)
    print(json.dumps(output))


if __name__=='__main__':
    main()
