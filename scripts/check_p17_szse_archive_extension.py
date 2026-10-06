"""Merge independent archive comparisons without replacing earlier failed evidence."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path('.artifacts/p17_20261001/szse_archive')


def load(path):
    return json.loads(Path(path).read_bytes())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    extension_path = ROOT/'comparison.json'
    plan_path = Path('evaluation/p17_20261001_szse_archive_plan.json')
    new, plan = load(extension_path), load(plan_path)
    assert new['plan_sha256'] == digest(plan_path)
    formal_path = Path('.artifacts/p17_20261001/formal/comparison.json')
    formal = load(formal_path)
    original_path = Path('.artifacts/p17_20261001/combined-quality.json')
    original = load(original_path)
    frozen_original = {}
    for path, expected in original['evidence_sha256'].items():
        assert digest(path) == expected
        report = load(path)
        for item in report.get('financial_comparisons', report.get('comparisons', [])):
            assert item['match']
            key = item['record_id'], item['field']
            if key in frozen_original:
                assert frozen_original[key]['actual'] == item['actual']
            frozen_original[key] = dict(item, status='match')
    assert len(frozen_original) == original['unique_independently_compared'] == 450
    formal_cells = {(c['symbol'], c['date'], c['field']): dict(c) for c in formal['market_cells']}
    assert len(formal_cells) == 2550
    additions = Counter()
    for item in new['cells']:
        if item['group'] == 'formal':
            key = item['code'], item['date'], item['field']
            old = formal_cells[key]
            assert old['exchange'] == 'SZSE' and old['status'] == 'missing_reference'
            assert old['record_id'] == item['record_id']
            formal_cells[key] = dict(old, **{k: v for k, v in item.items() if k not in {'group', 'code'}})
        else:
            assert item['group'] == 'original'
            key = item['record_id'], item['field']
            assert item['record_id'] and key not in frozen_original
            frozen_original[key] = item
        additions[item['group']] += 1
    assert additions == {'formal': 432, 'original': 108}
    formal_counts = Counter(c['status'] for c in formal_cells.values())
    original_counts = Counter(c['status'] for c in frozen_original.values())
    output = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'source_sha256': {str(p): digest(p) for p in [plan_path, extension_path, formal_path, original_path]},
        'archive_addition_counts': dict(additions), 'archive_status_counts': new['status_counts'],
        'formal': {'registered_market_cells': 2550, 'status_counts': dict(formal_counts),
                   'original_reference_gap': 942, 'remaining_missing_reference': formal_counts.get('missing_reference', 0),
                   'expected_halt_absence_cells_separately_qualified': 72,
                   'exact_matches': sum(c.get('exact', False) for c in formal_cells.values()),
                   'registered_financial_cells': 225, 'financial_comparison_remains_separate': True},
        'original': {'registered_all_metric_cells': 666, 'status_counts': dict(original_counts),
                     'remaining_uncompared': 666 - len(frozen_original)},
        'original_450_and_formal_1536_reports_preserved': True,
        'all_runtime_sources_unchanged': True, 'historical_publication_not_upgraded': True,
        'whole_market_statistical_certification': False, 'phase1_complete': False,
    }
    path = ROOT/'extension.json'
    if args.verify_only:
        prior = load(path)
        assert {k: v for k, v in prior.items() if k != 'checked_at'} == {k: v for k, v in output.items() if k != 'checked_at'}
    else:
        with path.open('x', encoding='utf-8') as stream:
            json.dump(output, stream, indent=2)
            stream.write('\n')
    print(json.dumps(output))
    return 2 if new['status_counts'].get('mismatch', 0) else 0


if __name__ == '__main__':
    raise SystemExit(main())
