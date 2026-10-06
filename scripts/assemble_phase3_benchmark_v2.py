"""Mechanical aggregation of independently reviewed, immutable v2 units."""
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.artifacts/phase3/benchmark-v2-20261004'
CATEGORIES = ('research_agent_implementation_defect', 'benchmark_or_request_contract_defect',
              'data_or_evidence_insufficiency', 'intrinsic_precondition_or_temporal_impossibility')


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ratio(n, d):
    return {'numerator': n, 'denominator': d, 'rate': n / d if d else None}


def write(name, value):
    with (OUT / name).open('x', encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def assemble():
    manifest = read(OUT / 'benchmark-manifest.json')
    deterministic = read(OUT / 'independent-oracle/deterministic-review.json')
    semantic = read(OUT / 'semantic-review.json')
    official = read(OUT / 'independent-oracle/official-coverage.json')
    results = read(OUT / 'agent-results.json')
    cases = {case['id']: case for case in manifest['cases']}
    numerical = {task['case_id']: task for task in deterministic['tasks']}
    language = {task['case_id']: task for task in semantic['tasks']}
    outputs = {case['case_id']: case for case in results['cases']}
    if not (len(cases) == len(numerical) == len(language) == len(outputs) == 38
            and set(cases) == set(numerical) == set(language) == set(outputs)):
        raise ValueError('Frozen denominator or independent judgment task IDs differ')
    cells = {(cell['security'], cell['exchange'], cell['period'], cell['metric'], cell['source_revision']): cell
             for cell in official['checks']}
    contracts = {case['id']: case for case in manifest['contract_validation']['cases']}
    tasks = []
    official_units = []
    for identity, case in cases.items():
        num, sem, report = numerical[identity], language[identity], outputs[identity]['output']
        if sem['full_text_read'] is not True or sem['markdown_sha256'] != outputs[identity]['markdown_sha256']:
            raise ValueError('Every final Markdown must have hash-bound full semantic review')
        units = copy.deepcopy(num['units']) + copy.deepcopy(sem['additional_claim_units'])
        for unit in units:
            unit.update(task_id=identity, level=case['level'])
            unit.setdefault('claim_id', None)
            unit.setdefault('hypothesis_id', None)
            unit.setdefault('evidence_refs', [])
            unit.setdefault('source_refs', [])
            unit.setdefault('anchor_valid', None)
            if unit['assessable'] is not True and unit['supported'] is True:
                raise ValueError('Unknown unit cannot be a supported pass')
            if unit['unit_type'] == 'numeric_claim':
                checks = []
                for eid in unit['evidence_refs']:
                    ev = report['evidence'][eid]
                    key = case['request']['symbol'], case['request']['exchange'], ev['period'], ev['metric'], ev['revision_id']
                    cell = cells.get(key)
                    checks.append({'evidence_id': eid, 'assessable': cell is not None and cell['assessable'] is True,
                        'supported': None if cell is None else cell['supported'], 'source_ref': None if cell is None else cell.get('source_ref'),
                        'reason': 'No independent official source cell/version' if cell is None else cell['reason']})
                item = {'task_id': identity, 'claim_id': unit['claim_id'], 'name': unit.get('name'),
                    'source_supported': unit['supported'], 'official_assessable': bool(checks) and all(check['assessable'] for check in checks),
                    'official_supported': True if checks and all(check['supported'] is True for check in checks) else
                        False if any(check['supported'] is False for check in checks) else None, 'input_checks': checks}
                official_units.append(item)
                unit['official_accuracy'] = item
        quality_ok = all(unit['supported'] is True for unit in units if unit['assessable'] is True)
        quality_known = all(unit['assessable'] is True for unit in units)
        task_success = num['deterministic_success_candidate'] is True and sem['task_completion_supported'] is True and quality_ok and quality_known
        problems = sorted({issue['category'] for issue in contracts[identity]['issues']})
        failure_categories = [] if task_success else [CATEGORIES[0]]
        if not task_success and CATEGORIES[0] not in problems:
            problems.append(CATEGORIES[0])
        for unit in units:
            unit['task_success'] = task_success
        tasks.append({'task_id': identity, 'level': case['level'], 'research_question': case['research_question'],
            'original_request': case['request'], 'contract_valid': contracts[identity]['contract_valid'],
            'task_success': task_success, 'failure_category': failure_categories,
            'problem_classes': problems, 'input_limitations': contracts[identity]['issues'],
            'required_completion': num['required_completion'], 'semantic_review': sem, 'units': units,
            'reasoning_summary': sem['reasoning_summary'] if task_success else
                'Required independent checks failed: ' + ', '.join(key for key, passed in num['required_completion']['checks'].items() if not passed)
                + '; ' + sem['reasoning_summary'], 'source_refs': [case['input_path'], outputs[identity]['report_path'], outputs[identity]['markdown_path']]})
    units = [unit for task in tasks for unit in task['units']]
    assessable = [unit for unit in units if unit['assessable'] is True]
    anchors = [unit for unit in units if unit['unit_type'] == 'required_event_anchor']
    checks = sum(task['required_completion']['required_checks'] for task in tasks)
    correct = sum(task['required_completion']['correct_required_checks'] for task in tasks)
    required_event_count = sum('event_chronology' in case['request']['hypotheses'] for case in cases.values())
    if len(anchors) != required_event_count:
        raise ValueError('Required anchor denominator must include every event task')
    official_assessable = [unit for unit in official_units if unit['official_assessable']]
    metrics = {'schema': 'phase3-independent-capability-metrics/v2', 'manifest_sha256': sha(OUT / 'benchmark-manifest.json'),
        'benchmark_contract_validity': ratio(sum(task['contract_valid'] is True for task in tasks), len(tasks)),
        **{level: ratio(sum(task['level'] == level and task['task_success'] for task in tasks), sum(task['level'] == level for task in tasks)) for level in ('L3', 'L5')},
        'ESR': ratio(sum(unit['supported'] is True for unit in assessable), len(assessable)),
        'hallucination': ratio(sum(unit['hallucination'] is True for unit in assessable), len(assessable)),
        'critical_anchor': ratio(sum(unit['anchor_valid'] is True for unit in anchors), required_event_count),
        'required_check_completion': ratio(correct, checks),
        'decisive_required_check_completion': ratio(sum(task['required_completion']['decisive_correct_checks'] for task in tasks),
            sum(task['required_completion']['decisive_required_checks'] for task in tasks)),
        'not_assessable_count': sum(unit['assessable'] is not True for unit in units),
        'not_assessable_dimensions': {
            'source_support_units': sum(unit['assessable'] is not True for unit in units),
            'official_numeric_claim_occurrences': len(official_units) - len(official_assessable),
            'official_distinct_source_revision_cells': official['summary']['not_assessable'],
            'meaning': 'Source-support assessability and corresponding-version official accuracy are separate judgments.'},
        'official_accuracy_coverage': {**ratio(len(official_assessable), len(official_units)),
            'source_supported': sum(unit['source_supported'] is True for unit in official_units),
            'independently_official_verified': sum(unit['official_supported'] is True and unit['official_assessable'] for unit in official_units),
            'official_contradictions': sum(unit['official_supported'] is False for unit in official_assessable),
            'not_assessable': len(official_units) - len(official_assessable),
            'conditional_official_accuracy': ratio(sum(unit['official_supported'] is True for unit in official_assessable), len(official_assessable)),
            'all_claim_financial_accuracy_certified': False, 'distinct_official_revision_cells': official['summary']},
        'failure_taxonomy': {category: {'problem_case_count': sum(category in task['problem_classes'] for task in tasks),
            'failed_task_count': sum(not task['task_success'] and category in task['problem_classes'] for task in tasks)} for category in CATEGORIES},
        'data_insufficient_count': sum(CATEGORIES[2] in task['problem_classes'] for task in tasks),
        'implementation_defect_count': sum(CATEGORIES[0] in task['problem_classes'] for task in tasks),
        'underspecified_request_count': 0, 'temporally_impossible_count': 0,
        'units_by_type': dict(Counter(unit['unit_type'] for unit in units)),
        'model': {'calls': results['campaign_ledger']['dispatches'], 'attempts_per_case': 1,
            'verified': sum(case['model']['status'] == 'verified' for case in results['cases']),
            'measured_tokens': sum(case['model'].get('total_tokens') or 0 for case in results['cases']),
            'unknown_usage_calls': sum(case['model'].get('total_tokens') is None for case in results['cases']),
            'reserved_tokens': results['campaign_ledger']['reserved'], 'financial_provider_calls': 0},
        'sampling': {'validation_cases': 38, 'independent_test_cases': 0, 'blind': False,
            'distinct_compiled_messages': 37, 'distinct_securities': len({case['security'] for case in cases.values()}),
            'L5_distinct_securities': len({case['security'] for case in cases.values() if case['level'] == 'L5'}),
            'L5_distinct_events': len({case['event']['record_id'] for case in cases.values() if case['level'] == 'L5'})},
        'historical_end_to_end_unchanged': {'L3': ratio(12, 62), 'L3_real_model': ratio(12, 37), 'L3_new_cutoff': ratio(0, 25),
            'L5': ratio(2, 6), 'ESR': ratio(952, 952), 'hallucination': ratio(0, 952), 'critical_anchor': ratio(2, 56)},
        'new_benchmark_thresholds_passed': False, 'phase3_full_acceptance': False,
        'full_acceptance_limitation': 'Validation-only reused corpus, no independent held-out test, one L5 security/two events; fixed descriptive catalogue and selection workflow do not certify broad/free-form research or all external financial truth.'}
    metrics['new_benchmark_thresholds_passed'] = (metrics['benchmark_contract_validity']['rate'] == 1
        and metrics['L3']['rate'] >= .85 and metrics['L5']['rate'] >= .85 and metrics['ESR']['rate'] >= .98
        and metrics['hallucination']['rate'] <= .01 and metrics['critical_anchor']['rate'] == 1)
    review = {'schema': 'phase3-independent-review/v2', 'manifest_sha256': metrics['manifest_sha256'],
        'input_hashes': {name: sha(OUT / name) for name in ('independent-oracle/deterministic-review.json',
            'independent-oracle/official-coverage.json', 'semantic-review.json', 'AGENT_OUTPUT_FREEZE.json')},
        'independence': 'Source/Fraction oracle and full-text Codex Judge separated from Agent generation; no previous verdict used as ground truth.',
        'tasks': tasks, 'total_units': len(units), 'original_scores_modified': False}
    return review, metrics, {'schema': 'official-numeric-claim-coverage/v2', 'claims': official_units}


if __name__ == '__main__':
    review, metrics, coverage = assemble()
    write('independent-review.json', review)
    write('metrics.json', metrics)
    write('official-numeric-claim-coverage.json', coverage)
    print(json.dumps({key: metrics[key] for key in ('L3', 'L5', 'ESR', 'hallucination', 'critical_anchor', 'required_check_completion', 'official_accuracy_coverage')}, ensure_ascii=False))
