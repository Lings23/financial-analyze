"""Local review handoff for the full retained corpus; never supplies expert scores.

The fixed reports are development/regression evidence, not a new held-out corpus.
Pending judgments stay null. A reviewer cannot override known missing required
evidence or turn local scorecard completion into general Phase 3 certification.
"""
import argparse
from collections import Counter
import copy
import json
from pathlib import Path

from accept_phase2_real import write
from phase3_followup import sha
from stock_research.errors import IntegrityError
from stock_research.models import digest


ROOT = Path('.artifacts/phase3/fullscope-20261003')
PACK = ROOT / 'review-pack'
LIVE = Path('.artifacts/phase3/followup-20261002/v3/live')


def corpus():
    real = json.loads((LIVE / 'result.json').read_bytes())
    for case in real['cases']:
        path = LIVE / (case['case'] + '.json')
        report = json.loads(path.read_bytes())
        if digest(report) != case['report_hash']:
            raise IntegrityError('original live report hash differs')
        yield 'real-model-v3', case['case'], path, report
    supplement = json.loads((ROOT / 'enriched-manifest.json').read_bytes())
    for case in supplement['cases']:
        path = ROOT / 'enriched-audit' / (case['id'] + '.json')
        report = json.loads(path.read_bytes())
        for field in ('facts', 'hypotheses'):
            if digest(report[field]) != case[field + '_hash']:
                raise IntegrityError('supplemental report differs')
        if report['request'] != case['request'] or report['model']['status'] != 'disabled':
            raise IntegrityError('supplement request/model boundary differs')
        yield 'same-securities-new-cutoff-model-disabled', case['id'], path, report


def assess(sheet, manifest):
    """Require complete explicit reviews; unknown is never zero errors or a pass."""
    if sheet['manifest_sha256'] != digest(manifest):
        raise IntegrityError('review is not bound to this manifest')
    expected = {r['id']: r for r in manifest['reports']}
    cases = {r['id']: r for r in sheet['cases']}
    if len(cases) != len(sheet['cases']) or set(cases) != set(expected):
        raise IntegrityError('review removed or duplicated corpus cases')
    results = []
    for key, original in expected.items():
        reviewed = cases[key]
        expected_ids = set(original['review_units'])
        units = {r['id']: r for r in reviewed['units']}
        if len(units) != len(reviewed['units']) or set(units) != expected_ids:
            raise IntegrityError('review removed or duplicated claim/hypothesis/anchor units')
        for unit in units.values():
            if unit['support'] not in (None, 'supported', 'unsupported', 'not_assessable'):
                raise IntegrityError('unknown evidence support judgment')
            if unit['hallucinated'] is not None and type(unit['hallucinated']) is not bool:
                raise IntegrityError('hallucination judgment is not explicit boolean/null')
        verdict = reviewed['task_success']
        if verdict is not None and type(verdict) is not bool:
            raise IntegrityError('task success judgment is not explicit boolean/null')
        pending = sum(u['support'] is None or u['hallucinated'] is None or not u['reason'] or not u['source_references']
                      for u in units.values())
        if verdict is None or not reviewed['task_reason'] or reviewed['unlisted_final_text_claims'] is None:
            pending += 1
        # Additional assertions found in the prose must be reviewed, not omitted.
        extra = reviewed['unlisted_final_text_claims']
        if extra is not None and not isinstance(extra, list):
            raise IntegrityError('additional final-text claims must be an explicit list')
        if extra:
            pending += len(extra)  # Requires a new frozen unit manifest, never silently dropped.
        assessor = sheet.get('assessor', {})
        if not assessor.get('name') or not assessor.get('completed_at') or not assessor.get('independence_statement'):
            pending += 1
        supported = sum(u['support'] == 'supported' for u in units.values())
        hallucinated = sum(u['hallucinated'] is True for u in units.values())
        complete = pending == 0
        results.append({'id': key, 'cohort': original['cohort'], 'level': original['level'],
                        'units': len(units), 'pending_review_items': pending,
                        'supported_units': supported if complete else None,
                        'hallucinated_units': hallucinated if complete else None,
                        'required_anchor': 'event_chronology' in original['request']['hypotheses'],
                        'supported_anchor': ('event_anchor' in units and units['event_anchor']['support'] == 'supported'
                                             and units['event_anchor']['hallucinated'] is False) if complete else None,
                        'evidence_support_rate': supported / len(units) if complete else None,
                        'hallucination_rate': hallucinated / len(units) if complete else None,
                        'reviewed_task_success': verdict if complete else None,
                        'known_required_evidence_complete': original['required_evidence_complete'],
                        'can_count_as_complete_research': complete and verdict is True and original['required_evidence_complete']})
    groups = []
    for cohort, level in sorted({(r['cohort'], r['level']) for r in results}):
        group = [r for r in results if r['cohort'] == cohort and r['level'] == level]
        reviewed = all(r['pending_review_items'] == 0 for r in group)
        units = sum(r['units'] for r in group)
        success = sum(r['can_count_as_complete_research'] for r in group)
        support = sum(r['supported_units'] or 0 for r in group)
        hallucinations = sum(r['hallucinated_units'] or 0 for r in group)
        anchor_total = sum(r['required_anchor'] for r in group)
        anchor_supported = sum(r['required_anchor'] and r['supported_anchor'] is True for r in group)
        groups.append({'cohort': cohort, 'level': level, 'tasks': len(group), 'units': units,
                       'review_complete': reviewed, 'success': success if reviewed else None,
                       'success_rate': success / len(group) if reviewed else None,
                       'success_85_percent_met': success / len(group) >= .85 if reviewed else None,
                       'evidence_support_rate': support / units if reviewed else None,
                       'esr_98_percent_met': support / units >= .98 if reviewed else None,
                       'hallucination_rate': hallucinations / units if reviewed else None,
                       'hallucination_at_most_1_percent_met': hallucinations / units <= .01 if reviewed else None,
                       'required_anchors': anchor_total,
                       'anchor_support_rate': anchor_supported / anchor_total if reviewed and anchor_total else None,
                       'required_anchors_100_percent_met': anchor_supported == anchor_total if reviewed else None})
    return {'review_status': 'complete' if all(g['review_complete'] for g in groups) else 'pending',
            'reports': len(results), 'review_units': sum(r['units'] for r in results),
            'groups': groups, 'cases': results,
            'independent_heldout_research_corpus_available': False,
            'general_phase3_quality_certified': False, 'full_goal_completed': False,
            'note': 'Historical regression and new-cutoff offline supplements stay separate; this scorecard alone cannot certify the general gates.'}


def build():
    PACK.mkdir(parents=True, exist_ok=False)
    reports = []
    cases = []
    index = ['# Phase 3 独立评审待办包', '',
             '所有评分留空；这是已有回归与补充报告的评审材料，不是新盲样，也不是已完成的专家评审。', '',
             '参照 docs/PHASE3_INDEPENDENT_REVIEW_20261003.md。不得把已知必需证据不足改记为完整研究成功。', '',
             '| 报告 | 层级/组别 | 必需检验完成 | JSON | 最终正文 |', '|---|---|---|---|---|']
    for cohort, case_id, path, report in corpus():
        uid = cohort + '/' + case_id
        level = 'L5' if report['request']['objective'] == 'event_review' else 'L3'
        units = [{'id': 'fact/' + f['id'], 'kind': 'numeric_claim', 'reported': f} for f in report['facts']]
        units += [{'id': 'hypothesis/' + h['id'], 'kind': 'hypothesis_conclusion', 'reported': h} for h in report['hypotheses']]
        if report['event_anchor']['status'] == 'verified':
            units.append({'id': 'event_anchor', 'kind': 'event_anchor', 'reported': report['event_anchor']})
        assert units and len({u['id'] for u in units}) == len(units)
        md_path = path.with_suffix('.md')
        assert md_path.is_file()
        complete = report['research_status'] == 'tests_completed'
        reports.append({'id': uid, 'case': case_id, 'cohort': cohort, 'level': level,
                        'path': str(path), 'sha256': sha(path), 'final_text_path': str(md_path),
                        'final_text_sha256': sha(md_path), 'request': report['request'],
                        'required_evidence_complete': complete, 'review_units': [u['id'] for u in units]})
        cases.append({'id': uid, 'task_success': None, 'task_reason': None,
                      'unlisted_final_text_claims': None,
                      'units': [{**u, 'support': None, 'hallucinated': None, 'source_references': [], 'reason': None} for u in units]})
        index.append(f'| {case_id} | {level} / {cohort} | {complete} | [{case_id}.json](<{path.resolve().as_posix()}>) | [正文](<{md_path.resolve().as_posix()}>) |')
    assert len(reports) == 68
    manifest = {'schema': 'phase3-pending-independent-review-v1', 'reports': reports,
                'source_files': {str(p): sha(p) for p in (LIVE / 'result.json', ROOT / 'enriched-manifest.json',
                                  ROOT / 'enriched-audit/result.json', ROOT / 'cashflow-reference/comparison.json',
                                  ROOT / 'remaining-gaps-rechecked.json')},
                'not_a_heldout_sample': True, 'required_thresholds': {'L3_success': .85, 'L5_success': .85,
                 'evidence_support': .98, 'hallucination': .01, 'required_anchors': 1.0}}
    write(PACK / 'manifest.json', manifest)
    sheet = {'manifest_sha256': digest(manifest), 'assessor': {'name': None, 'completed_at': None, 'independence_statement': None},
             'cases': cases}
    write(PACK / 'review-sheet.json', sheet)
    (PACK / 'INDEX.md').write_text('\n'.join(index) + '\n', encoding='utf8')
    readiness = assess(sheet, manifest)
    assert readiness['review_status'] == 'pending' and not readiness['full_goal_completed']
    assert all(g['success_rate'] is None for g in readiness['groups'])
    write(PACK / 'readiness.json', readiness)
    # Negative acceptance controls use in-memory synthetic judgments, never saved as reviews.
    dropped = copy.deepcopy(sheet)
    dropped['cases'].pop()
    try:
        assess(dropped, manifest)
    except IntegrityError:
        pass
    else:
        raise AssertionError('dropping a hard task was accepted')
    controls = {'synthetic_validation_only': True, 'blank_review_not_passed': True,
                'removed_task_rejected': True, 'known_incomplete_tasks_stay_in_denominator': True,
                'general_certification_not_inferred': True, 'model_or_provider_network_calls': 0}
    write(PACK / 'controls.json', controls)
    print(json.dumps({'reports': len(reports), 'units': readiness['review_units'], 'status': readiness['review_status'],
                      'cohorts': dict(Counter(r['cohort'] for r in reports)), 'manifest_sha256': sha(PACK / 'manifest.json')}))


def score(path, output):
    manifest = json.loads((PACK / 'manifest.json').read_bytes())
    for file, expected in manifest['source_files'].items():
        if sha(file) != expected:
            raise IntegrityError('review source changed')
    for r in manifest['reports']:
        if sha(r['path']) != r['sha256'] or sha(r['final_text_path']) != r['final_text_sha256']:
            raise IntegrityError('review report changed')
    result = assess(json.loads(path.read_bytes()), manifest)
    write(output, result)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}))


def self_check():
    manifest = json.loads((PACK / 'manifest.json').read_bytes())
    original = json.loads((PACK / 'review-sheet.json').read_bytes())
    pending = assess(original, manifest)
    assert pending['review_status'] == 'pending'
    assert all(g['evidence_support_rate'] is None and g['hallucination_rate'] is None for g in pending['groups'])
    fake = copy.deepcopy(original)
    fake['assessor'] = {'name': 'SYNTHETIC CONTROL NOT AN EXPERT', 'completed_at': 'synthetic', 'independence_statement': 'synthetic fixture only'}
    for c in fake['cases']:
        c.update(task_success=True, task_reason='synthetic', unlisted_final_text_claims=[])
        for u in c['units']:
            u.update(support='supported', hallucinated=False, source_references=['synthetic://control'], reason='synthetic')
    optimistic = assess(fake, manifest)
    assert sum(c['can_count_as_complete_research'] for c in optimistic['cases']) == 14
    assert all(g['success_85_percent_met'] is False for g in optimistic['groups'])
    assert not optimistic['full_goal_completed'] and not optimistic['general_phase3_quality_certified']
    for mutation in ('drop_case', 'drop_unit', 'bad_manifest'):
        modified = copy.deepcopy(original)
        if mutation == 'drop_case':
            modified['cases'].pop()
        elif mutation == 'drop_unit':
            modified['cases'][0]['units'].pop()
        else:
            modified['manifest_sha256'] = '0' * 64
        try:
            assess(modified, manifest)
        except IntegrityError:
            pass
        else:
            raise AssertionError('invalid review accepted: ' + mutation)
    result = {'synthetic_validation_only': True, 'blank_review_metrics_remain_null': True,
              'all_positive_fake_reviews_cannot_override_54_incomplete_tasks': True,
              'dropped_case_rejected': True, 'dropped_claim_rejected': True, 'changed_manifest_rejected': True,
              'full_goal_cannot_be_certified_by_this_development_corpus': True, 'real_expert_scores_created': 0}
    write(PACK / 'controls-verified.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--build', action='store_true')
    action.add_argument('--score', type=Path)
    action.add_argument('--self-check', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.build:
        build()
    elif args.self_check:
        self_check()
    elif args.output:
        score(args.score, args.output)
    else:
        parser.error('--score requires a fresh --output')
