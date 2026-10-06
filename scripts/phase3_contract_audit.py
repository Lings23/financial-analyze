"""Versioned contract audit of all 68 retained requests; no data/model calls.

Input validity is checked against full frozen snapshot memberships before reading
any Judge success verdict. The original end-to-end denominators stay unchanged.
"""
import argparse
from collections import Counter
import hashlib
import json
from datetime import datetime
from pathlib import Path

from phase3_benchmark_gate import precheck_cases, write_new
from stock_research.errors import IntegrityError
from stock_research.models import AccessContext, DataRecord, QueryContext, digest
from stock_research.providers.base import ProviderRegistry
from stock_research.research.cli import ReadArtifactStores
from stock_research.research.scoped import ScopedReadService, SourceGrant
from stock_research.research.study_contracts import StudyRequest
from stock_research.service import DataService
from stock_research.storage.memory import MemoryRepository

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / '.artifacts/phase3/independent-codex-review-20261004'
PACK = ROOT / '.artifacts/phase3/fullscope-20261003/review-pack'
ROUTE_SCOPES = {'pilot': 'p17-validation-20260930', 'p18': 'p18-validation-20261001',
                'qualified': 'p17-qualified-cninfo-20261001'}


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FrozenSources:
    """Full original snapshots rebuilt in memory; original artifacts stay read-only."""
    def __init__(self):
        self.input_hashes = {}
        self.snapshots = {}
        stores = [ROOT / p for p in (
            '.artifacts/p17_20261001/formal/artifacts', '.artifacts/p17_20260930/artifacts',
            '.artifacts/p18_20261001/artifacts', '.artifacts/p17_20261001/release_date/artifacts',
            '.artifacts/phase3/followup-20261002/event-prices/artifacts',
            '.artifacts/phase3/fullscope-20261003/domains/artifacts')]
        self.repository = MemoryRepository()
        self.service = DataService(ProviderRegistry(), None, self.repository, ReadArtifactStores(stores))
        self.empty_captures = {}
        self.service.benchmark_empty_capture_reader = self.empty_capture
        base = ROOT / '.artifacts/phase3'
        formal_run = self.load(ROOT / '.artifacts/p17_20261001/formal/run.json')
        for path in sorted((base / 'quality-20261002/repair-manifest-projections').glob('*.json')):
            if path.name.endswith('offline-report.json'):
                continue
            saved = self.load(path)
            if 'records' in saved:
                rows = tuple(DataRecord.from_dict(r) for r in saved['records'])
                sid = digest({'scope': saved['scope'], 'record_ids': sorted({r.record_id for r in rows})})
                if any(b['snapshot'] != sid for b in saved['projected_request']['bindings']):
                    raise IntegrityError('original projection snapshot differs')
                self.add(saved['scope'], sid, rows)
                if (saved['source_request']['symbol'] == '000016'
                        and not any(r.dataset.value == 'market_daily' for r in rows)):
                    b = next(b for b in saved['projected_request']['bindings'] if b['dataset'] == 'market_daily')
                    # Explicit frozen requested-response archive, not inferred from
                    # an empty projection or a provider capability declaration.
                    key = (saved['scope'], sid, b['dataset'], b['provider'],
                           saved['projected_request']['symbol'], b['start'], b['end'])
                    captured = [item for item in formal_run['results'] if item['request']['symbol'] == saved['source_request']['symbol']
                        and item['request']['dataset'] == b['dataset'] and item['request']['start'] == b['start']
                        and item['request']['end'] == b['end'] and item.get('stored_count') == 0 and item.get('visible_count') == 0]
                    if len(captured) != 1:
                        raise IntegrityError('empty source query is not independently located')
                    self.empty_captures[key] = ('53c6fe98247f95c104c63d836853f022dac3b8710d9dd003b02ac921dbce0c88',
                                                path.relative_to(ROOT).as_posix(), captured[0]['finished_at'])
        for path in (base / 'followup-20261002/event-prices/result.json',
                     base / 'fullscope-20261003/domains/result.json'):
            saved = self.load(path)
            for item in saved['results']:
                self.add(saved['scope'], item['snapshot'], item['records'])
        for item in self.load(REVIEW / 'lineage_db_snapshots.json')['snapshots']:
            self.add(item['scope'], item['snapshot'], item['records'])
        self.live = {c['id']: c for c in self.load(base / 'followup-20261002/v3/model-manifest.json')['cases']}
        self.extra = {c['id']: c for c in self.load(base / 'fullscope-20261003/enriched-manifest.json')['cases']}
        self.event_scope = self.load(base / 'followup-20261002/event-prices/result.json')['scope']
        self.domain_scope = self.load(base / 'fullscope-20261003/domains/result.json')['scope']

    def load(self, path):
        path = Path(path)
        self.input_hashes[path.relative_to(ROOT).as_posix()] = sha(path)
        return read(path)

    def add(self, scope, snapshot, raw):
        rows = tuple(r if isinstance(r, DataRecord) else DataRecord.from_dict(r) for r in raw)
        actual = self.repository.commit(scope, rows)
        if actual.snapshot_id != snapshot:
            raise IntegrityError('frozen full snapshot hash differs')
        self.snapshots[(scope, snapshot)] = actual.record_ids

    def empty_capture(self, request, binding, context):
        key = (context.access.scope, binding.snapshot, binding.dataset, binding.provider,
               request.security.symbol, binding.start.isoformat(), binding.end.isoformat())
        item = self.empty_captures.get(key)
        if item is None:
            return None
        if binding.provider not in context.access.allowed_providers:
            raise IntegrityError('empty capture source is not authorized')
        artifact_id, projection_path, available_at = item
        if datetime.fromisoformat(available_at) > context.as_of_date:
            return None
        raw = self.service.artifacts.get(context.access.scope, artifact_id)
        # get() verifies the immutable Artifact hash in the authorized namespace.
        proof = {'kind': 'tushare_requested_response_v2_empty/v1', 'source_authorized': True,
                 'source_scope': context.access.scope, 'bound_snapshot': binding.snapshot,
                 'request_identity': request.data_request(binding).identity(),
                 'archive_artifact_id': artifact_id, 'archive': json.loads(raw),
                 'source_refs': [projection_path, '.artifacts/p17_20261001/formal/run.json']}
        artifact_path = '.artifacts/p17_20261001/formal/artifacts/' + hashlib.sha256(context.access.scope.encode()).hexdigest() + '/' + artifact_id[:2] + '/' + artifact_id
        self.input_hashes[artifact_path] = hashlib.sha256(raw).hexdigest()
        self.input_hashes['.artifacts/p17_20261001/formal/run.json'] = sha(ROOT / '.artifacts/p17_20261001/formal/run.json')
        return proof

    def context(self, case):
        owner = self.live[case['case']] if case['cohort'] == 'real-model-v3' else self.extra[case['case']]['original']
        original = self.live[case['case']] if case['cohort'] == 'real-model-v3' else self.extra[case['case']]
        if original['request'] != case['request']:
            raise IntegrityError('frozen case request differs from manifest')
        scope = owner['scope'] if case['cohort'] == 'real-model-v3' else 'phase3-fullscope-supplement-20261003'
        request = StudyRequest.from_dict(case['request'])
        grants = []
        for binding in request.bindings:
            if case['cohort'] != 'real-model-v3' and binding.dataset in {'adjustment_factor', 'index_daily', 'financial_cashflow'}:
                source_scope = self.domain_scope
            elif owner['kind'] == 'real_scoped_catalogue':
                route = owner['routes'][binding.dataset]
                source_scope = self.event_scope if route == 'event_prices' else ROUTE_SCOPES[route]
            else:
                source_scope = owner['scope']
            if (source_scope, binding.snapshot) not in self.snapshots:
                raise IntegrityError('source grant references unknown frozen snapshot')
            grants.append(SourceGrant(self.service, AccessContext(source_scope, frozenset({binding.provider})),
                binding.snapshot, request.data_request(binding), binding.provider))
        return ScopedReadService(scope, lambda: tuple(grants)), AccessContext(scope, frozenset(b.provider for b in request.bindings))


def ratio(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'rate': numerator / denominator if denominator else None}


def dual_metrics(manifest, precheck, review, frozen_metrics):
    """Join only after validity is fixed, preserving every original task/unit."""
    entries = {r['id']: r for r in manifest['reports']}
    contracts = {c['id']: c for c in precheck['cases']}
    judgments = {t['task_id']: t for t in review['tasks']}
    if (len(entries) != len(manifest['reports']) or len(contracts) != len(precheck['cases'])
            or len(judgments) != len(review['tasks']) or set(entries) != set(contracts) or set(entries) != set(judgments)
            or len(entries) != 68 or sum(len(r['review_units']) for r in entries.values()) != 952):
        raise IntegrityError('original task/unit denominator differs')
    for task_id, entry in entries.items():
        if judgments[task_id]['original_request'] != entry['request'] or contracts[task_id]['request_sha256'] != digest(entry['request']):
            raise IntegrityError('request/cutoff changed during contract attribution')
    completed_checks, required_checks, completed_tasks = 0, 0, 0
    for task in judgments.values():
        required, completed = task['required_hypotheses'], task['completed_hypotheses']
        if len(required) != len(set(required)) or len(completed) != len(set(completed)) or not set(completed) <= set(required):
            raise IntegrityError('required-check accounting differs')
        required_checks += len(required)
        completed_checks += len(completed)
        completed_tasks += set(required) == set(completed)
    groups = {}
    selectors = {'L3': lambda e: e['level'] == 'L3', 'L5': lambda e: e['level'] == 'L5',
                 'L3_real_model': lambda e: e['level'] == 'L3' and e['cohort'] == 'real-model-v3',
                 'L3_new_cutoff_model_disabled': lambda e: e['level'] == 'L3' and e['cohort'] != 'real-model-v3'}
    for name, select in selectors.items():
        ids = [i for i, e in entries.items() if select(e)]
        valid = [i for i in ids if contracts[i]['valid'] is True]
        success = lambda subset: sum(judgments[i]['task_success'] is True for i in subset)
        e2e = ratio(success(ids), len(ids))
        if any(e2e[k] != frozen_metrics[name][k] for k in e2e):
            raise IntegrityError('end-to-end score differs from frozen independent review')
        groups[name] = {'benchmark_contract_validity': ratio(len(valid), len(ids)),
            'contract_valid_agent_task_success': ratio(success(valid), len(valid)),
            'frozen_end_to_end_request_success': e2e,
            'contract_invalid_count': sum(contracts[i]['valid'] is False for i in ids),
            'contract_not_assessable_count': sum(contracts[i]['valid'] is None for i in ids)}
    return {'schema': 'phase3-dual-success-attribution-v1', 'task_count': len(entries),
            'original_review_units': 952, 'benchmark_contract_validity': ratio(sum(c['valid'] is True for c in contracts.values()), len(entries)),
            'groups': groups, 'source_support': frozen_metrics['ESR'],
            'official_accuracy': frozen_metrics['official_external_reference_coverage'],
            'required_check_completion': {**ratio(completed_checks, required_checks), 'unit': 'required_hypothesis_checks'},
            'all_required_checks_completed_tasks': ratio(completed_tasks, len(entries)),
            'critical_anchor_validity': frozen_metrics['critical_anchor'], 'hallucination': frozen_metrics['hallucination'],
            'problem_class_task_counts': {k: sum(any(i['category'] == k for i in c['issues']) for c in contracts.values())
                for k in ('research_agent_implementation_defect', 'benchmark_or_request_contract_defect',
                          'data_or_evidence_insufficiency', 'intrinsic_precondition_or_temporal_impossibility')},
            'issue_taxonomy': precheck['issue_taxonomy'],
            'interpretation': 'Retrospective attribution on the original development/regression corpus; validity is audited before joining success. The valid subset is small and not a new blind capability experiment. Zero denominators mean not_assessable, never 100%.',
            'original_scores_modified': False, 'new_generation_model_calls': 0, 'new_provider_calls': 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True, help='new output directory only')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = read(PACK / 'manifest.json')
    receipt = read(REVIEW / 'REVIEW_FREEZE.json')
    if receipt['original_manifest_sha256'] != sha(PACK / 'manifest.json'):
        raise IntegrityError('original manifest differs from independent review freeze')
    for name in ('lineage_db_snapshots.json', 'review-result.json', 'metrics.json'):
        if sha(REVIEW / name) != receipt['files'][name]['sha256']:
            raise IntegrityError('frozen independent review input differs: ' + name)
    for source, expected in manifest['source_files'].items():
        if sha(ROOT / source) != expected:
            raise IntegrityError('original manifest-bound source hash differs')
    for entry in manifest['reports']:
        if sha(ROOT / entry['path']) != entry['sha256'] or sha(ROOT / entry['final_text_path']) != entry['final_text_sha256']:
            raise IntegrityError('original report/Markdown hash differs')
    sources = FrozenSources()
    candidates = [{'id': e['id'], **e} for e in manifest['reports']]
    precheck = precheck_cases(candidates, sources.context)
    precheck['input_file_sha256'] = {**sources.input_hashes,
        str((PACK / 'manifest.json').relative_to(ROOT)): sha(PACK / 'manifest.json'),
        **{p: sha(ROOT / p) for p in ('src/stock_research/research/benchmark_contracts.py',
                                      'scripts/phase3_contract_audit.py', 'scripts/phase3_benchmark_gate.py')}}
    precheck['frozen_case_count'] = 68
    precheck['snapshot_count'] = len(sources.snapshots)
    # Persist validity before loading any previous success verdict.
    write_new(args.output / 'contract-precheck.json', precheck)
    review = read(REVIEW / 'review-result.json')
    frozen_metrics = read(REVIEW / 'metrics.json')
    if review['manifest_file_sha256'] != sha(PACK / 'manifest.json') or frozen_metrics['manifest_file_sha256'] != sha(PACK / 'manifest.json'):
        raise IntegrityError('frozen Judge metrics belong to a different manifest')
    metrics = dual_metrics(manifest, precheck, review, frozen_metrics)
    metrics['frozen_judge_input_sha256'] = {n: sha(REVIEW / n) for n in ('review-result.json', 'metrics.json')}
    metrics['contract_precheck_sha256'] = sha(args.output / 'contract-precheck.json')
    write_new(args.output / 'metrics.json', metrics)
    attribution = []
    judgments = {t['task_id']: t for t in review['tasks']}
    for case in precheck['cases']:
        original = judgments[case['id']]
        attribution.append({'task_id': case['id'], 'level': original['level'], 'cohort': original['cohort'],
            'original_request': original['original_request'], 'benchmark_contract_validity': case['valid'],
            'contract_valid_task_success': original['task_success'] if case['valid'] is True else None,
            'end_to_end_task_success': original['task_success'], 'failure_attribution': case['issues'],
            'implementation_defects': [u for u in original['units'] if 'implementation_defect' in u.get('problem_class', [])],
            'source_refs': list(precheck['input_file_sha256']), 'input_sha256': case['input_sha256']})
    write_new(args.output / 'case-attribution.json', {'schema': 'phase3-four-class-attribution-v1', 'tasks': attribution})
    print(json.dumps({'tasks': 68, 'valid': precheck['valid_case_count'], 'invalid': precheck['invalid_case_count'],
                      'unknown': precheck['not_assessable_case_count'], 'groups': metrics['groups']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
