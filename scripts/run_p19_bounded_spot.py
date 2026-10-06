"""Three original spot functions with bounded, archived complete pagination."""
import argparse
from datetime import timedelta
import hashlib
import inspect
import json
import re
from pathlib import Path

from stock_research.errors import PermissionDenied
from stock_research.models import AccessContext, PITMode, utcnow
from stock_research.providers.akshare import AkShareCaptureProvider
from stock_research.storage.artifacts import ArtifactStore

ROOT = Path('.artifacts/p19_20261001/bounded_spot')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--label')
    args = parser.parse_args()
    global ROOT
    if args.label:
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,40}', args.label): raise ValueError('invalid evidence label')
        ROOT = ROOT / args.label
    ROOT.mkdir(parents=True, exist_ok=True)
    artifacts = ArtifactStore(ROOT / 'artifacts')
    access = AccessContext('p19-bounded-spot-20261001', frozenset({'akshare'}))
    provider = AkShareCaptureProvider(artifacts)
    target = ROOT / 'run.json'
    if args.verify_only:
        run = json.loads(target.read_bytes())
    else:
        if target.exists(): raise ValueError('bounded spot evidence exists; refusing overwrite')
        import akshare as ak
        names = ['stock_zh_a_spot_em', 'stock_cy_a_spot_em', 'stock_kc_a_spot_em']
        plan = {'scope': access.scope, 'akshare_version': ak.__version__, 'endpoints': names,
            'timeout_seconds_per_endpoint': 120, 'max_pages_per_endpoint': 100,
            'max_rows': 10000, 'max_page_bytes': 2 * 1024 * 1024, 'max_attempts_per_page': 1,
            'page_delay_seconds': 1, 'route': 'unchanged_environment',
            'original_urls_filters_and_fields': True, 'no_fallback': True,
            'code_sha256': {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [
                'src/stock_research/providers/akshare.py', 'src/stock_research/providers/akshare_worker.py',
                'src/stock_research/providers/akshare_spot.py']},
            'installed_function_sha256': {n: hashlib.sha256(inspect.getsource(getattr(ak, n)).encode()).hexdigest() for n in names}}
        plan_id = artifacts.put(access.scope, plan)
        with (ROOT / 'plan.json').open('x', encoding='utf8') as stream: json.dump(plan, stream, indent=2)
        run = {'scope': access.scope, 'plan_artifact_id': plan_id, 'started_at': utcnow().isoformat(), 'results': []}
        for name in names:
            entry = {'endpoint': name, 'started_at': utcnow().isoformat()}
            try:
                capture = provider.capture(name, access, timeout=120)
                assert capture.row_count > 0 and capture.completion_basis == 'stable_total_unique_securities_all_pages'
                sources = provider.source_evidence(capture.snapshot_id, access, utcnow(), PITMode.SYSTEM)
                assert len(sources) == 1
                source = json.loads(sources[0])
                entry.update(status='captured', snapshot_id=capture.snapshot_id, row_count=capture.row_count,
                    source_artifact_id=capture.source_artifact_ids[0], pages=source['page_count'],
                    attempts=source['attempts'], retries=source['retries'])
            except Exception as exc:
                entry.update(status='failed', error_type=type(exc).__name__)
                if getattr(exc, 'diagnostic', None) is not None: entry['worker_diagnostic'] = exc.diagnostic
            entry['finished_at'] = utcnow().isoformat()
            run['results'].append(entry)
            print(json.dumps(entry), flush=True)
        run['finished_at'] = utcnow().isoformat()
        run['all_three_complete_captures'] = all(r['status'] == 'captured' for r in run['results'])
        with target.open('x', encoding='utf8') as stream: json.dump(run, stream, indent=2)
    replay = []
    for entry in run['results']:
        if entry['status'] != 'captured': continue
        capture = provider.read(entry['snapshot_id'], access, utcnow(), PITMode.SYSTEM)
        assert capture.row_count == entry['row_count'] and capture.completion_basis == 'stable_total_unique_securities_all_pages'
        for denied, cutoff in [(access, capture.captured_at - timedelta(microseconds=1)),
                (AccessContext(access.scope, frozenset({'tushare'})), utcnow()),
                (access, capture.ingested_at - timedelta(microseconds=1))]:
            try: provider.source_evidence(entry['snapshot_id'], denied, cutoff, PITMode.SYSTEM)
            except PermissionDenied: pass
            else: raise AssertionError('source evidence bypassed PIT or provider permission')
        try: provider.read(entry['snapshot_id'], AccessContext('wrong-p19-scope', access.allowed_providers), utcnow())
        except FileNotFoundError: pass
        else: raise AssertionError('spot snapshot crossed scope')
        source = provider.source_evidence(entry['snapshot_id'], access, utcnow())[0]
        assert hashlib.sha256(source).hexdigest() == entry['source_artifact_id']
        replay.append({'endpoint': entry['endpoint'], 'snapshot_id': capture.snapshot_id,
                       'row_count': capture.row_count, 'authorization_pit_hash_passed': True})
    report = {'replayed_captures': replay, 'all_three_complete_captures': run['all_three_complete_captures']}
    replay_path = ROOT / 'replay.json'
    if args.verify_only:
        assert report == json.loads(replay_path.read_bytes())
    else:
        with replay_path.open('x', encoding='utf8') as stream: json.dump(report, stream, indent=2)
    print(json.dumps({'all_three_complete_captures': report['all_three_complete_captures'],
                      'replayed_captures': len(replay)}))


if __name__ == '__main__': main()
