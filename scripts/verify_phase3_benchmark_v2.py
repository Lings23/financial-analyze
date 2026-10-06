"""Verify preservation, frozen inputs, one-attempt outputs and fixed denominators."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.artifacts/phase3/benchmark-v2-20261004'


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify():
    baseline = read(OUT / 'preservation-baseline.json')
    preregistration = read(OUT / 'EVALUATION_PREREGISTRATION.json')
    manifest = read(OUT / 'benchmark-manifest.json')
    results = read(OUT / 'agent-results.json')
    receipt = read(OUT / 'AGENT_OUTPUT_FREEZE.json')
    plan = read(OUT / 'model-dispatch-plan.json')
    checks = {}
    checks['historical_files_unchanged'] = all((ROOT / path).is_file() and sha(ROOT / path) == expected
        for path, expected in baseline['files'].items())
    checks['preregistered_files_unchanged'] = all(sha(ROOT / path) == expected
        for path, expected in preregistration['files'].items())
    checks['Agent_implementation_unchanged_after_freeze'] = all(sha(ROOT / path) == expected
        for path, expected in manifest['evaluation_protocol']['implementation_files'].items())
    checks['all_Agent_raw_outputs_unchanged'] = all(sha(OUT / path) == expected
        for path, expected in receipt['files'].items())
    cases = manifest['cases']
    expected_ids = {case['id'] for case in cases}
    actual_ids = {case['case_id'] for case in results['cases']}
    checks['all_38_cases_retained'] = len(cases) == len(results['cases']) == 38 and expected_ids == actual_ids
    checks['original_68_and_952_retained'] = baseline['old_task_count'] == 68 and baseline['old_review_units'] == 952
    checks['original_manifest_unchanged'] = baseline['old_manifest_sha256'] == sha(ROOT / '.artifacts/phase3/fullscope-20261003/review-pack/manifest.json')
    checks['new_levels_fixed'] = sum(case['level'] == 'L3' for case in cases) == 34 and sum(case['level'] == 'L5' for case in cases) == 4
    checks['whole_batch_contract_valid'] = manifest['contract_validation']['valid_case_count'] == 38 and manifest['contract_validation']['all_cases_contract_valid'] is True
    checks['all_input_files_unchanged'] = all(sha(ROOT / case['input_path']) == case['input_sha256'] for case in cases)
    checks['all_declared_source_files_unchanged'] = all(sha(ROOT / path) == expected for case in cases for path, expected in case['source_hashes'].items())
    checks['exact_frozen_dispatch_plan'] = results['manifest_sha256'] == sha(OUT / 'benchmark-manifest.json') == plan['manifest_sha256'] and results['dispatch_plan_sha256'] == sha(OUT / 'model-dispatch-plan.json')
    ledger = results['campaign_ledger']
    checks['exactly_38_single_attempts'] = ledger['dispatches'] == 38 and len(ledger['intents']) == 38 and len({item['case_id'] for item in ledger['intents']}) == 38 and all(item['attempt'] == 1 for item in ledger['intents'])
    checks['bounded_reservations'] = ledger['reserved'] <= plan['max_token_reservations']
    checks['all_raw_responses_saved'] = len(list((OUT / 'live').glob('raw-response-*.json'))) == 38 and all(read(OUT / 'live' / ('raw-response-' + identity + '.json'))['case_id'] == identity for identity in expected_ids)
    checks['no_duplicate_case_dispatch'] = all(case['dispatch_count'] == 1 for case in results['cases'])
    checks['no_model_substitution'] = plan['model'] == manifest['evaluation_protocol']['model'] == 'deepseek-v4-flash-0731' and all(case['model']['requested_model'] == plan['model'] for case in results['cases'])
    for filename in ('independent-review.json', 'metrics.json'):
        path = OUT / filename
        if path.exists():
            value = read(path)
            if filename == 'independent-review.json':
                checks['all_tasks_independently_scored'] = {task['task_id'] for task in value['tasks']} == expected_ids and len(value['tasks']) == 38
                checks['not_assessable_never_automatically_supported'] = all(unit['supported'] is not True for task in value['tasks'] for unit in task['units'] if unit['assessable'] is not True)
            else:
                checks['metric_denominators_fixed'] = value['L3']['denominator'] == 34 and value['L5']['denominator'] == 4 and value['benchmark_contract_validity']['denominator'] == 38
    return {'schema': 'phase3-benchmark-preservation-verification/v2', 'checks': checks,
        'passed': all(checks.values()), 'historical_files_checked': len(baseline['files']),
        'formal_cases': 38, 'original_cases': 68, 'original_review_units': 952,
        'model_calls_during_verification': 0, 'provider_calls_during_verification': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify()
    with args.output.open('x', encoding='utf8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result))
    if not result['passed']:
        raise SystemExit(1)
