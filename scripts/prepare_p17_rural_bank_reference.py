"""Freeze a narrower official summary request without replacing the failed batch."""
import hashlib
import json
from pathlib import Path


def main():
    original = Path('evaluation/p17_20261001_formal_financial_reference_plan.json')
    discovery = Path('.artifacts/p17_20261001/formal/reference_gap_discovery/run.json')
    plan = json.loads(original.read_bytes())
    item = dict(next(r for r in plan['requests'] if r['code'] == '601528' and r['period'] == '2024-12-31'))
    item['selector'] = '2024年年度报告摘要'
    target = Path('evaluation/p17_20261001_rural_bank_reference_plan.json')
    result = {
        'scope': 'p17-rural-bank-reference-20261001',
        'original_plan_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
        'discovery_run_sha256': hashlib.sha256(discovery.read_bytes()).hexdigest(),
        'reason': 'Correct-code official index returned full report and summary; narrow summary independently of provider values. Preserve original failed batch.',
        'min_interval_seconds': 2.5,
        'original_financial_denominator': 225,
        'requests': [item],
    }
    with target.open('x', encoding='utf8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'plan_sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'requests': 1}))


if __name__ == '__main__':
    main()
