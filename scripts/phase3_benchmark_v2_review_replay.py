"""Recompute frozen review metrics and compare a fresh independent source replay.

No Agent execution, production calculator imports, financial network calls or new
semantic judgments. The latter remain human/Codex annotations bound to Markdown
hashes; this replay verifies and aggregates those already frozen annotations.
"""
import argparse
import hashlib
import json
from pathlib import Path

from assemble_phase3_benchmark_v2 import OUT, assemble


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open('x', encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def run(destination):
    destination.mkdir(parents=True, exist_ok=False)
    checks, differences = {}, {}
    for name in ('deterministic-review.json', 'official-coverage.json'):
        old = OUT / 'independent-oracle-baseline' / name
        fresh = OUT / 'recomputed/independent-oracle-baseline' / name
        checks['strict_baseline_bytes_equal_' + name] = old.read_bytes() == fresh.read_bytes()
    for name in ('official-coverage.json', 'source-duplicate-proofs.json', 'ORACLE_CORRECTION_PROTOCOL.json'):
        checks['supplement_bytes_equal_' + name] = ((OUT / 'independent-oracle' / name).read_bytes()
                                                  == (OUT / 'recomputed/independent-oracle' / name).read_bytes())
    a = read(OUT / 'independent-oracle/deterministic-review.json')
    b = read(OUT / 'recomputed/independent-oracle/deterministic-review.json')
    changed = [key for key in set(a) | set(b) if a.get(key) != b.get(key)]
    differences['supplement_differing_top_level_keys'] = sorted(changed)
    allowed = {'baseline_directory_preserved', 'supplemental_input_sha256'}
    checks['only_replay_output_paths_differ'] = set(changed) <= allowed
    checks['all_38_tasks_588_units_and_judgments_equal'] = a['tasks'] == b['tasks'] and a['summary'] == b['summary']
    for value in (a, b):
        for field in allowed:
            value.pop(field, None)
    checks['all_other_supplement_content_equal'] = a == b
    review, metrics, coverage = assemble()
    for name, value in (('independent-review.json', review), ('metrics.json', metrics),
                        ('official-numeric-claim-coverage.json', coverage)):
        fresh = destination / name
        write_new(fresh, value)
        checks['aggregation_bytes_equal_' + name] = fresh.read_bytes() == (OUT / name).read_bytes()
    manifest = read(OUT / 'benchmark-manifest.json')
    results = read(OUT / 'agent-results.json')
    identities = {case['case_id']: case for case in results['cases']}
    semantic = read(OUT / 'semantic-review.json')
    checks['all_38_full_text_annotations_hash_bound'] = (len(semantic['tasks']) == 38 and all(
        task['full_text_read'] is True
        and task['markdown_sha256'] == digest(OUT.parents[2] / identities[task['case_id']]['markdown_path'])
        for task in semantic['tasks']))
    checks['all_38_case_ids_unchanged'] = ({task['task_id'] for task in review['tasks']}
                                        == {case['id'] for case in manifest['cases']})
    result = {'schema': 'phase3-independent-review-replay/v2', 'passed': all(checks.values()),
              'checks': checks, 'documented_path_differences': differences,
              'semantic_review_recomputed': False,
              'semantic_review_basis': 'Frozen full-text annotations, each verified against original Markdown SHA.',
              'Agent_runs': 0, 'model_calls': 0, 'financial_provider_calls': 0,
              'production_calculation_imports': 0}
    write_new(destination / 'verification.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    result = run(parser.parse_args().destination)
    print(json.dumps(result, ensure_ascii=False))
    if not result['passed']:
        raise SystemExit(1)
