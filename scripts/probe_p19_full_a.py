"""Check whether the successful small-page route supports the standard full call."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from stock_research.models import AccessContext
from stock_research.providers.akshare import AkShareCaptureProvider
from stock_research.storage.artifacts import ArtifactStore


def main():
    root = Path('.artifacts/p19_20261001/full_a')
    root.mkdir(parents=True, exist_ok=True)
    target = root/'run.json'
    if target.exists():
        raise ValueError('full-call evidence exists')
    access = AccessContext('p19-full-a-20261001', frozenset({'akshare'}))
    artifacts = ArtifactStore(root/'artifacts')
    plan_aid = artifacts.put(access.scope, {'endpoint':'stock_zh_a_spot_em', 'params':{},
        'timeout_seconds':45, 'route':'unchanged_environment', 'logical_attempts':1,
        'upstream_sdk_may_retry':True,
        'provider_source_sha256':hashlib.sha256(Path(
            'src/stock_research/providers/akshare.py').read_bytes()).hexdigest(),
        'worker_source_sha256':hashlib.sha256(Path(
            'src/stock_research/providers/akshare_worker.py').read_bytes()).hexdigest()})
    outcome = {'scope':access.scope, 'plan_artifact_id':plan_aid,
               'started_at':datetime.now(timezone.utc).isoformat()}
    try:
        provider = AkShareCaptureProvider(artifacts)
        capture = provider.capture('stock_zh_a_spot_em', access, timeout=45)
        assert capture.row_count > 0
        assert provider.read(capture.snapshot_id, access, datetime.now(timezone.utc)).rows == capture.rows
        outcome.update(status='captured', snapshot_id=capture.snapshot_id, row_count=capture.row_count)
    except Exception as exc:
        outcome.update(status='failed', error_type=type(exc).__name__)
    outcome['finished_at'] = datetime.now(timezone.utc).isoformat()
    with target.open('x',encoding='utf-8') as stream:
        json.dump(outcome, stream, indent=2)
    print(json.dumps(outcome))


if __name__=='__main__':
    main()
