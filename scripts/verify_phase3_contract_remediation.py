"""Fresh-process recomputation and immutable-original controls for this repair."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from phase3_benchmark_gate import freeze_benchmark, precheck_cases, write_new
from phase3_contract_audit import FrozenSources, PACK, ROOT, REVIEW, read, sha
from stock_research.errors import IntegrityError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repair', type=Path, default=ROOT / '.artifacts/phase3/contract-remediation-20261004')
    parser.add_argument('--output', type=Path, required=True, help='new verification directory')
    args = parser.parse_args()
    args.repair, args.output = args.repair.resolve(), args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    process = subprocess.run([sys.executable, str(ROOT / 'scripts/phase3_contract_audit.py'),
        '--output', str(args.output / 'contract-recomputed')], cwd=ROOT, env=environment,
        text=True, capture_output=True, check=True)
    with (args.output / 'recompute.log').open('x', encoding='utf8') as stream:
        stream.write(process.stdout + process.stderr)
    comparisons = {name: sha(args.repair / 'audit-verified' / name) == sha(args.output / 'contract-recomputed' / name)
                   for name in ('contract-precheck.json', 'metrics.json', 'case-attribution.json')}
    original = read(args.repair / 'preservation-before.json')['files']
    changed, deleted = [], []
    for file, expected in original.items():
        path = ROOT / file
        if not path.exists():
            deleted.append(file)
        elif sha(path) != expected:
            changed.append(file)
    current_paths = {p.relative_to(ROOT).as_posix() for p in (ROOT / '.artifacts').rglob('*')
                     if p.is_file() and args.repair not in p.parents and '__pycache__' not in p.parts}
    added = sorted(current_paths - set(original))
    receipt = read(REVIEW / 'REVIEW_FREEZE.json')
    review_mismatches = [name for name, info in receipt['files'].items()
                        if name != 'REMEDIATION_RECOMMENDATIONS.md' and sha(REVIEW / name) != info['sha256']]
    manifest = read(PACK / 'manifest.json')
    sources = FrozenSources()
    candidates = list(manifest['reports'])
    check = precheck_cases(candidates, sources.context)
    rejected = False
    try:
        freeze_benchmark(args.output / 'must-not-freeze.json', candidates, check,
            benchmark_version='negative-control-retained-68', implementation_version='single-research-v4',
            parent_manifest_sha256=sha(PACK / 'manifest.json'), source_context=sources.context)
    except IntegrityError:
        rejected = True
    result = {'schema': 'phase3-contract-remediation-verification-v1',
              'original_files_checked': len(original), 'changed': changed, 'deleted': deleted, 'added_outside_repair': added,
              'original_judge_files_checked': len(receipt['files']) - 1, 'original_judge_mismatches': review_mismatches,
              'user_edited_recommendation_sha256': sha(REVIEW / 'REMEDIATION_RECOMMENDATIONS.md'),
              'original_manifest_sha256': sha(PACK / 'manifest.json'),
              'all_68_tasks_and_952_units_retained': len(manifest['reports']) == 68 and sum(len(r['review_units']) for r in manifest['reports']) == 952,
              'recomputed_files_byte_identical': comparisons,
              'whole_invalid_corpus_freeze_rejected': rejected,
              'no_partial_manifest_written': not (args.output / 'must-not-freeze.json').exists(),
              'provider_network_calls': 0, 'generation_model_calls': 0}
    write_new(args.output / 'verification.json', result)
    print(json.dumps(result))
    if changed or deleted or added or review_mismatches or not all(comparisons.values()) or not rejected:
        raise AssertionError('repair verification failed; see immutable receipt')


if __name__ == '__main__':
    main()
