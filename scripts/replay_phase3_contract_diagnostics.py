"""Offline implementation regression, including retained invalid inputs.

This is not a new Agent capability benchmark or a rescore. Gate-invalid legacy
cases are exercised solely to verify compatibility and honest diagnostics.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from phase3_benchmark_gate import write_new
from phase3_contract_audit import FrozenSources, PACK, ROOT, read, sha
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import AccessContext, digest
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.report import markdown
from stock_research.research.study import StudyRuntime
from stock_research.research.study_contracts import StudyRequest, StudySpec


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume-from', type=Path, help='revalidate persisted diagnostic runs in a fresh process')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    sources = FrozenSources()
    previous = {c['task_id']: c for c in read(args.resume_from / 'result.json')['cases']} if args.resume_from else {}
    cases = []
    for entry in read(PACK / 'manifest.json')['reports']:
        if sha(ROOT / entry['path']) != entry['sha256']:
            raise IntegrityError('original report differs')
        original = read(ROOT / entry['path'])
        request = StudyRequest.from_dict(entry['request'])
        service, access = sources.context(entry)
        store = CheckpointStore((args.resume_from if args.resume_from else args.output) / 'runs')
        legacy = StudyRuntime(service, store, spec=StudySpec(version='single-research-v3'))
        current = StudyRuntime(service, store, spec=StudySpec(version='single-research-v4'))
        if args.resume_from:
            prior = previous[entry['id']]
            old = legacy.run(request, access, resume=prior['legacy_run_id'])
            new = current.run(request, access, resume=prior['new_run_id'])
            if digest(old) != prior['legacy_report_digest'] or digest(new) != prior['new_report_digest']:
                raise IntegrityError('fresh process persisted report replay differs')
        else:
            old = legacy.run(request, access)
            new = current.run(request, access)
        for key in ('facts', 'hypotheses', 'event_anchor'):
            if old[key] != original[key] or new[key] != original[key]:
                raise IntegrityError('legacy/new factual payload differs from frozen original: ' + key)
        if 'insufficiency_diagnostics' in old or new['diagnostics_version'] != 'study-insufficiency-v1':
            raise IntegrityError('diagnostics version isolation failed')
        if legacy.run(request, access, resume=old['run_id']) != old or current.run(request, access, resume=new['run_id']) != new:
            raise IntegrityError('completed report replay differs')
        try:
            current.run(request, AccessContext(access.scope, frozenset({'revoked-synthetic-provider'})), resume=new['run_id'])
        except PermissionDenied:
            pass
        else:
            raise AssertionError('replay bypassed revoked provider authorization')
        output = args.output / entry['cohort']
        write_new(output / (entry['case'] + '.json'), new)
        with (output / (entry['case'] + '.md')).open('x', encoding='utf8') as stream:
            stream.write(markdown(new))
        cases.append({'task_id': entry['id'], 'original_report_sha256': entry['sha256'],
                      'original_request_sha256': digest(entry['request']),
                      'legacy_and_v4_facts_hypotheses_anchor_equal_original': True,
                      'legacy_and_v4_completed_replays_equal': True, 'revocation_denied': True,
                      'legacy_run_id': old['run_id'], 'new_run_id': new['run_id'],
                      'legacy_report_digest': digest(old), 'new_report_digest': digest(new),
                      'new_report_path': (output / (entry['case'] + '.json')).relative_to(ROOT).as_posix(),
                      'diagnostic_codes': [r['code'] for h in new['insufficiency_diagnostics'] for r in h['insufficiency_reasons']]})
    result = {'schema': 'phase3-v4-offline-diagnostic-regression-v1',
              'not_a_capability_benchmark': True, 'original_scores_modified': False,
              'tasks': len(cases), 'original_payload_matches': len(cases), 'replays': len(cases) * 2,
              'revocation_checks': len(cases), 'diagnostic_taxonomy': dict(Counter(r for c in cases for r in c['diagnostic_codes'])),
              'fresh_process_persisted_resume': bool(args.resume_from),
              'provider_network_calls': 0, 'model_dispatches': 0, 'cases': cases}
    write_new(args.output / 'result.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}))


if __name__ == '__main__':
    main()
