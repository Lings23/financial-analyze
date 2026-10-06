"""Seal completed new review files, keeping every prior frozen file intact."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.artifacts/phase3/benchmark-v2-20261004'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    required = ('benchmark-manifest.json', 'contract-validation.json', 'agent-results.json',
                'independent-review.json', 'metrics.json', 'semantic-review.json',
                'PHASE3_BENCHMARK_V2_REPORT.md', 'REMEDIATION_RECOMMENDATIONS.md',
                'verification-final.json', 'recomputed/aggregation/verification.json')
    for name in required:
        if not (OUT / name).is_file():
            raise ValueError('Incomplete review: ' + name)
    for name in ('verification-final.json', 'recomputed/aggregation/verification.json'):
        if json.loads((OUT / name).read_bytes())['passed'] is not True:
            raise ValueError('Verification failed: ' + name)
    target = OUT / 'BENCHMARK_REVIEW_FREEZE.json'
    if target.exists():
        raise FileExistsError('Refusing to overwrite the completed independent review freeze')
    files = {path.relative_to(ROOT).as_posix(): sha(path)
             for path in sorted(OUT.rglob('*'))
             if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}
    scripts = list((ROOT / 'scripts').glob('*phase3_benchmark_v2*.py'))
    scripts += list((ROOT / 'tests').glob('*phase3_benchmark_v2*.py'))
    scripts += [ROOT / 'tests/test_profit_change.py', ROOT / 'tests/test_study_v5.py']
    implementation = {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted(set(scripts))}
    documents = {name: sha(ROOT / name) for name in ('docs/STATUS.md', 'docs/PLAN.md', 'docs/ARCHITECTURE.md', 'README.md')}
    result = {'schema': 'phase3-independent-review-freeze/v2', 'review_date': '2026-10-04',
              'timezone': 'Asia/Shanghai', 'manifest_sha256': sha(OUT / 'benchmark-manifest.json'),
              'files': files, 'review_scripts_and_tests': implementation, 'current_document_receipt': documents,
              'formal_cases': 38, 'model_calls': 38, 'model_retries': 0,
              'frozen_original_task_count': 68, 'frozen_original_review_unit_count': 952,
              'original_scores_modified': False, 'freeze_receipt_self_excluded': True,
              'warning': 'Validation-only reused corpus; source support is not full official accuracy or blind generalization.'}
    with target.open('x', encoding='utf8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'files_frozen': len(files), 'review_code_files': len(implementation),
                      'freeze_sha256': sha(target)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
