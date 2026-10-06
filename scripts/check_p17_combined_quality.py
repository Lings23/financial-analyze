"""Count distinct original financial cells; never double count repeated references."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from stock_research.models import AccessContext
from stock_research.storage.postgres import PostgresRepository


def main():
    root = Path('.artifacts/p17_20261001')
    original = json.loads(Path('.artifacts/p17_20260930/run.json').read_text(encoding='utf-8'))
    paths = [root/'reference-comparison.json', root/'sse_market/comparison.json',
             root/'szse_market/comparison-precision.json']
    reports = [json.loads(path.read_text(encoding='utf-8')) for path in paths]
    snapshot = original['results'][-1]['snapshot_id']
    db = PostgresRepository(Path('.runtime/p17-dsn.txt').read_text(encoding='utf-8').strip())
    access = AccessContext(original['scope'],frozenset({'tushare'}))
    rows = db.read(access.scope,snapshot)
    # Trusted local acceptance context: the frozen snapshot was fully ingested before this cutoff.
    cutoff = datetime.fromisoformat(original['finished_at'])+timedelta(seconds=1)
    assert all(r.provider in access.allowed_providers and r.ingested_at<=cutoff and r.available_at<=cutoff for r in rows)
    cells = {(r.record_id,m.name):(r,m.value) for r in rows for m in r.metrics}
    assert len(cells)==666
    compared = {}
    for report in reports:
        assert report.get('original_snapshot', report.get('snapshot_id'))==snapshot
        for item in report.get('financial_comparisons',report.get('comparisons',[])):
            key = item['record_id'],item['field']
            assert key in cells
            record, actual = cells[key]
            assert actual == Decimal(item['actual'])
            expected, tolerance = Decimal(item['reference']),Decimal(item['tolerance'])
            assert abs(actual-expected)<=tolerance and item['match']
            if key in compared:
                assert compared[key]['actual']==item['actual']
            compared[key] = item
    output = {'checked_at':datetime.now(timezone.utc).isoformat(),'snapshot_id':snapshot,
              'evidence_sha256':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths},
              'original_metric_cells':len(cells),'unique_independently_compared':len(compared),
              'matched_within_source_precision':len(compared),'remaining_uncompared':len(cells)-len(compared),
              'counts_by_dataset':dict(Counter(cells[k][0].dataset.value for k in compared)),
              'counts_by_exchange':dict(Counter(cells[k][0].canonical_symbol.split(':',1)[0] for k in compared)),
              'counts_by_security':dict(Counter(cells[k][0].canonical_symbol for k in compared)),
              'counts_by_field':dict(Counter(k[1] for k in compared)),
              'post_capture_szse_precision_correction':True,'market_wide_accuracy_verified':False,
              'historical_release_verified':False}
    path = root/'combined-quality.json'
    if path.exists():
        prior = json.loads(path.read_text(encoding='utf-8'))
        assert {k:v for k,v in prior.items() if k!='checked_at'}=={k:v for k,v in output.items() if k!='checked_at'}
    else:
        with path.open('x',encoding='utf-8') as stream:
            json.dump(output,stream,indent=2)
    print(json.dumps(output))


if __name__=='__main__':
    main()
