"""One explicit supplemental request for the preserved failed archive row."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import collect_p17_szse_archive as archive
from stock_research.storage.artifacts import ArtifactStore

BASE_ROOT = archive.ROOT
BASE_PLAN = archive.PLAN
PLAN = Path('evaluation/p17_20261001_szse_archive_gap_plan.json')
ROOT = Path('.artifacts/p17_20261001/szse_archive_gap')


def prepare():
    base = json.loads(BASE_PLAN.read_bytes())
    captured = json.loads((BASE_ROOT/'collection.json').read_bytes())
    failed = [r for r in captured['results'] if r['status'] != 'collected']
    assert len(failed) == 1
    gap = failed[0]
    assert (gap['group'], gap['code'], gap['date']) == ('original', '000001', '2024-09-30')
    group = dict(next(g for g in base['groups'] if g['label'] == gap['group']), codes=[gap['code']], dates=[gap['date']])
    base.update(scope='p17-szse-archive-gap-20261001', created_at=datetime.now(timezone.utc).isoformat(),
                groups=[group], logical_requests=1, registered_cells=6, overall_deadline_seconds=30,
                preserved_failed_request=gap,
                baseline_sha256={str(p):archive.digest(p) for p in [BASE_PLAN, BASE_ROOT/'collection.json',
                                                                  BASE_ROOT/'comparison.json', BASE_ROOT/'extension.json']})
    base['source_sha256'][str(Path(__file__))] = archive.digest(__file__)
    archive.write(PLAN, base)
    print(json.dumps({'plan_sha256':archive.digest(PLAN), 'requests':1, 'registered_cells':6}))


def summarize(plan, result):
    for path, expected in plan['baseline_sha256'].items():
        assert archive.digest(path) == expected
    prior = json.loads((BASE_ROOT/'comparison.json').read_bytes())
    merged = {(c['group'],c['code'],c['date'],c['field']):dict(c) for c in prior['cells']}
    for cell in result['cells']:
        key = cell['group'],cell['code'],cell['date'],cell['field']
        assert merged[key]['status'] == 'missing_reference' and merged[key]['record_id'] == cell['record_id']
        merged[key] = cell
    counts = Counter(c['status'] for c in merged.values())
    assert len(merged) == 540 and sum(counts.values()) == 540
    prior_extension = json.loads((BASE_ROOT/'extension.json').read_bytes())
    gap_counts = result['status_counts']
    old_counts = prior_extension['original']['status_counts']
    original_matched = old_counts['match'] + gap_counts.get('match',0)
    original_mismatch = old_counts['mismatch'] + gap_counts.get('mismatch',0)
    return {'checked_at':datetime.now(timezone.utc).isoformat(), 'plan_sha256':archive.digest(PLAN),
            'baseline_sha256':plan['baseline_sha256'],
            'gap_comparison_sha256':archive.digest(ROOT/'comparison.json'),
            'registered_archive_cells':540, 'archive_status_counts':dict(counts), 'gap_status_counts':gap_counts,
            'formal':prior_extension['formal'],
            'original':{'registered_all_metric_cells':666,'matched':original_matched,'mismatched':original_mismatch,
                        'unverified':666-original_matched-original_mismatch},
            'original_failed_collection_and_comparisons_preserved':True,
            'historical_publication_not_upgraded':True, 'phase1_complete':False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--collect',action='store_true')
    parser.add_argument('--verify-only',action='store_true')
    args = parser.parse_args()
    if args.prepare:
        prepare();return 0
    plan = json.loads(PLAN.read_bytes())
    ROOT.mkdir(parents=True,exist_ok=True)
    store = ArtifactStore(ROOT/'artifacts')
    archive.PLAN, archive.ROOT = PLAN, ROOT
    if args.collect:
        if (ROOT/'collection.json').exists():
            raise ValueError('supplemental capture already exists')
        captured = archive.collect(plan,store)
        print(json.dumps({'requests':1,'http_attempts':captured['http_attempts'],
                          'status_counts':dict(Counter(e['status'] for e in captured['results']))}))
        return 0 if all(e['status']=='collected' for e in captured['results']) else 2
    result = archive.compare(plan,json.loads((ROOT/'collection.json').read_bytes()),store)
    path = ROOT/'comparison.json'
    if args.verify_only:
        prior = json.loads(path.read_bytes())
        assert {k:v for k,v in result.items() if k!='checked_at'} == {k:v for k,v in prior.items() if k!='checked_at'}
    else:
        archive.write(path,result)
    summary = summarize(plan,result)
    path = ROOT/'summary.json'
    if args.verify_only:
        prior = json.loads(path.read_bytes())
        assert {k:v for k,v in summary.items() if k!='checked_at'} == {k:v for k,v in prior.items() if k!='checked_at'}
    else:
        archive.write(path,summary)
    print(json.dumps(summary))
    return 2 if summary['archive_status_counts'].get('mismatch',0) else 0


if __name__=='__main__':
    raise SystemExit(main())
