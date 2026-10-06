"""Synthetic gate/accounting mechanisms, never financial ground truth."""
import copy
import json
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research_fixtures import fixture
from study_fixtures import study_request
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import AccessContext, digest
from stock_research.research.scoped import ScopedReadService, SourceGrant

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from phase3_benchmark_gate import freeze_benchmark, precheck_cases, require_valid_precheck
from phase3_contract_audit import dual_metrics
from phase3_followup import prepare
import phase3_archive_quality
import phase3_enriched_audit


class FreezeBuilderTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.f = fixture(self.root)
        self.request = study_request(self.f, hypotheses=('financial_deterioration',))
        self.cases = [{'id': 'synthetic-valid', 'request': self.request.to_dict()}]
        self.context = lambda case: (self.f.service, self.f.access)

    def freeze(self, cases, precheck, context=None):
        return freeze_benchmark(self.root / 'benchmark.json', cases, precheck,
            benchmark_version='synthetic-v1', implementation_version='single-research-v4',
            parent_manifest_sha256='0' * 64, source_context=context or self.context)

    def test_valid_set_freezes_once_with_lineage(self):
        precheck = precheck_cases(self.cases, self.context)
        self.assertTrue(precheck['all_cases_contract_valid'])
        frozen = self.freeze(self.cases, precheck)
        self.assertEqual(frozen['cases'], self.cases)
        self.assertFalse(frozen['original_scores_modified'])
        with self.assertRaises(FileExistsError):
            self.freeze(self.cases, precheck)

    def test_batch_with_invalid_case_is_rejected_without_filtering(self):
        invalid = {'id': 'synthetic-missing-event', 'request': replace(self.request,
            hypotheses=('event_chronology',)).to_dict()}
        cases = self.cases + [invalid]
        check = precheck_cases(cases, self.context)
        self.assertEqual((check['case_count'], check['valid_case_count'], check['invalid_case_count']), (2, 1, 1))
        with self.assertRaises(IntegrityError):
            self.freeze(cases, check)
        self.assertFalse((self.root / 'benchmark.json').exists())

    def test_caller_cannot_forge_valid_verdict_or_erase_failure(self):
        cases = [{'id': 'invalid', 'request': replace(self.request, hypotheses=('event_chronology',)).to_dict()}]
        fake = {'candidate_sha256': digest(cases), 'case_count': 1,
                'cases': [{'id': 'invalid', 'request_sha256': digest(cases[0]['request']), 'valid': True}]}
        with self.assertRaises(IntegrityError):
            self.freeze(cases, fake)
        self.assertFalse((self.root / 'benchmark.json').exists())

    def test_changed_cutoff_and_removed_case_invalidate_precheck(self):
        check = precheck_cases(self.cases, self.context)
        changed = copy.deepcopy(self.cases)
        changed[0]['request']['as_of'] = '2025-04-17T00:00:00+00:00'
        with self.assertRaises(IntegrityError):
            require_valid_precheck(changed, check)
        with self.assertRaises(IntegrityError):
            require_valid_precheck([], check)

    def test_freeze_rechecks_revocable_grants_and_source_bytes(self):
        recipient = AccessContext('synthetic-recipient', self.f.access.allowed_providers)
        grants = [SourceGrant(self.f.service, self.f.access, b.snapshot, self.request.data_request(b), b.provider)
                  for b in self.request.bindings]
        service = ScopedReadService(recipient.scope, lambda: tuple(grants))
        context = lambda case: (service, recipient)
        check = precheck_cases(self.cases, context)
        grants.clear()
        with self.assertRaises(PermissionDenied):
            self.freeze(self.cases, check, context)
        aid = self.f.records[0].artifact_id
        self.f.artifacts._path(self.f.access.scope, aid).write_bytes(b'synthetic corrupt bytes')
        with self.assertRaises(IntegrityError):
            self.freeze(self.cases, check)

    def test_duplicate_cases_and_unknown_verdict_cannot_freeze(self):
        with self.assertRaises(IntegrityError):
            precheck_cases(self.cases * 2, self.context)
        check = precheck_cases(self.cases, self.context)
        check['cases'][0]['valid'] = None
        with self.assertRaises(IntegrityError):
            require_valid_precheck(self.cases, check)

    def test_existing_formal_builder_blocks_before_runtime_or_model_configuration(self):
        cases = [{'id': 'synthetic-invalid', 'request': replace(self.request, hypotheses=('event_chronology',)).to_dict()}]
        output = self.root / 'formal-builder'
        with patch('phase3_followup.source_context', self.context), patch('phase3_followup.load_model_config') as model_config:
            with self.assertRaises(IntegrityError):
                prepare(output / 'manifest.json', selected_cases=cases, root=output)
        model_config.assert_not_called()
        self.assertTrue((output / 'contract-precheck.json').exists())
        self.assertFalse((output / 'manifest.json').exists())
        self.assertFalse((output / 'prepare-runs').exists())

    def test_archive_builder_prechecks_before_any_agent_execution(self):
        corpus_path = self.root / 'synthetic-corpus.json'
        invalid = replace(self.request, hypotheses=('event_chronology',),
                          bindings=tuple(replace(b, provider='tushare') for b in self.request.bindings))
        original = copy.deepcopy(invalid.to_dict())
        original['bindings'][0]['start'] = '2026-09-15'
        original['bindings'][0]['end'] = '2026-09-25'
        corpus_path.write_text(json.dumps({'scope': self.f.access.scope, 'cases': [{'id': 'invalid', 'request': original}]}))
        def paths(value):
            return corpus_path if str(value) == 'evaluation/phase3_real_cases_20261002.json' else Path(value)
        output = self.root / 'archive-builder'
        with patch.object(phase3_archive_quality, 'Path', side_effect=paths), \
                patch.object(phase3_archive_quality, 'service', return_value=self.f.service), \
                patch.object(phase3_archive_quality, 'projection_service', return_value=(self.f.service, invalid, (), {})), \
                patch.object(phase3_archive_quality, 'StudyRuntime') as runtime:
            with self.assertRaises(IntegrityError):
                phase3_archive_quality.prepare(output / 'manifest.json', {})
        runtime.assert_not_called()
        self.assertTrue((output / 'manifest-contract-precheck.json').exists())
        self.assertFalse((output / 'manifest.json').exists())

    def test_enriched_builder_prechecks_all_25_before_any_agent_execution(self):
        output = self.root / 'enriched-builder'
        corpus_path = self.root / 'synthetic-projection-candidates.json'
        invalid = replace(self.request, hypotheses=('event_chronology',))
        old_cases = [{'id': f'synthetic-{i}', 'kind': 'real_archived_income_projection', 'request': invalid.to_dict()} for i in range(25)]
        corpus_path.write_text(json.dumps({'cases': old_cases}))
        snapshot = self.request.bindings[0].snapshot
        captures = [{'query': {'case': c['id'], 'dataset': dataset, 'start': '2025-04-01', 'end': '2025-04-03'},
                     'snapshot': snapshot} for c in old_cases for dataset in ('adjustment_factor', 'financial_cashflow', 'index_daily')]
        captured = (None, None, {'finished_at': self.request.as_of.isoformat(), 'results': captures})
        access = AccessContext(self.f.access.scope, frozenset({'fixture', 'tushare'}))
        with patch.object(phase3_enriched_audit, 'ROOT', output), patch.object(phase3_enriched_audit, 'ORIGINAL', corpus_path), \
                patch.object(phase3_enriched_audit, 'captured_service', return_value=captured), \
                patch.object(phase3_enriched_audit, 'source_context', return_value=(self.f.service, access, {})), \
                patch.object(phase3_enriched_audit, 'StudyRuntime') as runtime:
            with self.assertRaises(IntegrityError):
                phase3_enriched_audit.prepare()
        runtime.assert_not_called()
        check = json.loads((output / 'enriched-prepare/contract-precheck.json').read_bytes())
        self.assertEqual((check['case_count'], check['invalid_case_count']), (25, 25))
        self.assertFalse((output / 'enriched-manifest.json').exists())


class DualMetricTests(unittest.TestCase):
    def inputs(self):
        entries, contracts, tasks = [], [], []
        for i in range(68):
            level = 'L3' if i < 62 else 'L5'
            cohort = 'real-model-v3' if i < 37 or i >= 62 else 'same-securities-new-cutoff-model-disabled'
            request = {'synthetic': True, 'as_of': '2025-04-16T00:00:00+00:00', 'id': i}
            valid = i < 12 or i >= 66
            entries.append({'id': str(i), 'level': level, 'cohort': cohort, 'request': request,
                            'review_units': [str(n) for n in range(14)]})
            contracts.append({'id': str(i), 'valid': valid, 'request_sha256': digest(request), 'issues': []})
            tasks.append({'task_id': str(i), 'original_request': request, 'task_success': valid,
                          'required_hypotheses': ['synthetic_required_check'],
                          'completed_hypotheses': ['synthetic_required_check'] if valid else []})
        frozen = {name: {'numerator': n, 'denominator': d, 'rate': n/d} for name, n, d in
                  [('L3', 12, 62), ('L5', 2, 6), ('L3_real_model', 12, 37), ('L3_new_cutoff_model_disabled', 0, 25)]}
        frozen.update(ESR={}, official_external_reference_coverage={}, critical_anchor={}, hallucination={})
        return {'reports': entries}, {'cases': contracts, 'issue_taxonomy': {}}, {'tasks': tasks}, frozen

    def test_conditional_and_end_to_end_denominators_are_separate(self):
        result = dual_metrics(*self.inputs())
        groups = result['groups']
        self.assertEqual(groups['L3']['frozen_end_to_end_request_success']['denominator'], 62)
        self.assertEqual(groups['L3']['contract_valid_agent_task_success']['denominator'], 12)
        self.assertIsNone(groups['L3_new_cutoff_model_disabled']['contract_valid_agent_task_success']['rate'])
        self.assertEqual(result['task_count'], 68)
        self.assertEqual(result['original_review_units'], 952)

    def test_task_drop_cutoff_change_or_changed_old_score_rejected(self):
        for mutation in ('drop', 'cutoff', 'score'):
            inputs = copy.deepcopy(self.inputs())
            if mutation == 'drop':
                inputs[1]['cases'].pop()
            elif mutation == 'cutoff':
                inputs[2]['tasks'][0]['original_request'] = {'synthetic': 'changed cutoff'}
            else:
                inputs[3]['L3']['denominator'] -= 1
            with self.subTest(mutation=mutation), self.assertRaises(IntegrityError):
                dual_metrics(*inputs)


if __name__ == '__main__':
    unittest.main()
