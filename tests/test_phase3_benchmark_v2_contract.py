"""Synthetic v2 preregistration mechanisms, never financial source truth."""
import copy
import hashlib
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from research_fixtures import fixture
from study_fixtures import add_domain, study_request, with_event
from helpers import ts
from stock_research.errors import IntegrityError, PermissionDenied
from stock_research.models import AccessContext
from stock_research.research.scoped import ScopedReadService, SourceGrant

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from phase3_benchmark_v2_contract import DATE_ALIGNMENT, VERSION, freeze_benchmark, validate_cases


class BenchmarkV2ContractTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.f = fixture(self.root)
        self.source = self.root / 'synthetic-source.json'
        self.source.write_text('{"synthetic":true}', encoding='utf8')
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.context = lambda case: (self.f.service, self.f.access)

    def case(self, request=None):
        request = request or study_request(self.f, hypotheses=('financial_deterioration',))
        return {'id': 'synthetic-v2', 'case_id': 'synthetic-v2', 'version': 'synthetic-case/v2',
            'level': 'L3', 'research_question': 'SYNTHETIC: apply the declared descriptive rule',
            'split': 'development', 'novelty': {'synthetic': True, 'blind': False},
            'scope': self.f.access.scope, 'request': request.to_dict(),
            'source_scopes': {binding.dataset: self.f.access.scope for binding in request.bindings},
            'event': None, 'expected_behavior': {'hypotheses': {hid: {'rule': 'synthetic rule',
                'permitted_statuses': ['supported', 'unsupported', 'conflicted', 'insufficient']}
                for hid in request.hypotheses}, 'mandatory_fact_names': [], 'diagnostic_codes': []},
            'success_criteria': ['All preregistered checks are completed with linked evidence'],
            'contract_version': VERSION, 'source_hashes': {'synthetic-source.json': self.sha}}

    def event_case(self):
        request, record = with_event(self.f, date_only=True)
        case = self.case(request)
        case['level'] = 'L5'
        case['event'] = {'record_id': record.record_id, 'event_type': 'synthetic_financial_release',
            'dataset': 'financial_income', 'source': {key: record.to_dict()[key]
                for key in ('provider', 'source_url', 'source_key')},
            'version': {key: record.to_dict()[key] for key in ('provider_version', 'revision_id')},
            'release_precision': 'date_conservative_next_day',
            'before_window': ['2025-04-01', '2025-04-01'],
            'after_window': ['2025-04-03', '2025-04-14'],
            'market_dataset': 'market_daily', 'snapshot': request.bindings[0].snapshot}
        return case

    def validate(self, cases, context=None):
        return validate_cases(cases, context or self.context, repository_root=self.root)

    def freeze(self, cases, validation, context=None):
        return freeze_benchmark(self.root / 'benchmark.json', cases, validation,
            benchmark_version='synthetic-benchmark/v2', implementation_version='single-research-v4',
            parent_manifest_sha256='0' * 64, source_context=context or self.context,
            repository_root=self.root, protocol={'model': 'synthetic-disabled'})

    def test_valid_case_freezes_exclusively_without_agent_or_model(self):
        cases = [self.case()]
        validation = self.validate(cases)
        self.assertTrue(validation['all_cases_contract_valid'])
        self.assertEqual((validation['provider_network_calls'], validation['generation_model_calls']), (0, 0))
        manifest = self.freeze(cases, validation)
        self.assertEqual(manifest['cases'], cases)
        with self.assertRaises(FileExistsError):
            self.freeze(cases, validation)

    def test_case_missing_expected_behavior_or_question_is_rejected(self):
        for field in ('research_question', 'expected_behavior', 'success_criteria', 'novelty'):
            with self.subTest(field=field):
                case = self.case()
                del case[field]
                self.assertFalse(self.validate([case])['all_cases_contract_valid'])

    def test_missing_required_hypothesis_expectation_is_rejected(self):
        case = self.case()
        case['expected_behavior']['hypotheses'].clear()
        self.assertFalse(self.validate([case])['all_cases_contract_valid'])

    def test_bad_source_hash_or_changed_source_bytes_is_rejected(self):
        case = self.case()
        case['source_hashes']['synthetic-source.json'] = '0' * 64
        self.assertFalse(self.validate([case])['all_cases_contract_valid'])
        cases = [self.case()]
        validation = self.validate(cases)
        self.source.write_text('{"synthetic":"changed"}', encoding='utf8')
        with self.assertRaises(IntegrityError):
            self.freeze(cases, validation)
        self.assertFalse((self.root / 'benchmark.json').exists())

    def test_source_path_escape_and_wrong_scope_cannot_pass(self):
        case = self.case()
        case['source_hashes'] = {'../outside.json': self.sha}
        self.assertFalse(self.validate([case])['all_cases_contract_valid'])
        case = self.case()
        case['source_scopes']['market_daily'] = 'another-owner'
        self.assertFalse(self.validate([case])['all_cases_contract_valid'])

    def test_every_event_side_has_real_visible_price_and_endpoint(self):
        case = self.event_case()
        validation = self.validate([case])
        self.assertTrue(validation['all_cases_contract_valid'])
        event = validation['cases'][0]['outer_details']['event']
        self.assertEqual(event['runtime_before_endpoint'], '2025-04-01')
        self.assertEqual(event['runtime_after_endpoint'], '2025-04-03')

    def test_event_declared_version_source_and_precision_must_match(self):
        for field in ('version', 'source', 'release_precision'):
            with self.subTest(field=field):
                case = self.event_case()
                if field == 'version':
                    case['event'][field]['revision_id'] = '0' * 64
                elif field == 'source':
                    case['event'][field]['provider'] = 'another-provider'
                else:
                    case['event'][field] = 'timestamp'
                self.assertFalse(self.validate([case])['all_cases_contract_valid'])

    def test_event_window_cannot_include_disclosure_day_or_invent_prices(self):
        for field, window in (('before_window', ['2025-04-01', '2025-04-02']),
                              ('after_window', ['2025-04-04', '2025-04-14']),
                              ('after_window', ['2025-04-03', '2025-04-20'])):
            with self.subTest(field=field, window=window):
                case = self.event_case()
                case['event'][field] = window
                self.assertFalse(self.validate([case])['all_cases_contract_valid'])

    def test_exact_timestamp_post_window_cannot_equal_event_close(self):
        request, record = with_event(self.f)
        record = replace(record, published_at=ts('2025-04-02T07:00:00'),
                         available_at=ts('2025-04-02T07:00:00'))
        snapshot = self.f.repo.commit(self.f.access.scope, (*self.f.records, record))
        request = replace(request, event_record_id=record.record_id,
            bindings=tuple(replace(binding, snapshot=snapshot.snapshot_id) for binding in request.bindings))
        case = self.case(request)
        case['level'] = 'L5'
        case['event'] = self.event_case()['event']
        case['event'].update(record_id=record.record_id, release_precision='timestamp',
            source={key: record.to_dict()[key] for key in ('provider', 'source_url', 'source_key')},
            version={key: record.to_dict()[key] for key in ('provider_version', 'revision_id')},
            snapshot=request.bindings[0].snapshot, after_window=['2025-04-02', '2025-04-14'])
        validation = self.validate([case])
        self.assertFalse(validation['all_cases_contract_valid'])
        self.assertFalse(validation['cases'][0]['validation_checks']['event_window_order'])

    def test_event_not_required_must_not_be_invented_and_l5_cannot_omit_it(self):
        case = self.case()
        case['event'] = self.event_case()['event']
        self.assertFalse(self.validate([case])['all_cases_contract_valid'])
        case = self.case()
        case['level'] = 'L5'
        self.assertFalse(self.validate([case])['all_cases_contract_valid'])

    def test_exact_date_policy_must_be_preregistered_without_interpolation(self):
        request = study_request(self.f, hypotheses=('market_direction',))
        request, _ = add_domain(self.f, request, 'index_daily', values={'close': ['100', '110', '120']})
        case = self.case(request)
        self.assertFalse(self.validate([case])['all_cases_contract_valid'])
        case['date_alignment_policy'] = DATE_ALIGNMENT
        self.assertTrue(self.validate([case])['all_cases_contract_valid'])
        case['date_alignment_policy'] = 'choose-after-seeing-results'
        self.assertFalse(self.validate([case])['all_cases_contract_valid'])

    def test_batch_invalid_case_and_forged_validation_cannot_freeze_partial_set(self):
        good, bad = self.case(), self.case()
        bad.update(id='synthetic-bad', case_id='synthetic-bad', research_question='')
        cases = [good, bad]
        validation = self.validate(cases)
        self.assertEqual((validation['valid_case_count'], validation['invalid_case_count']), (1, 1))
        with self.assertRaises(IntegrityError):
            self.freeze(cases, validation)
        forged = copy.deepcopy(validation)
        forged['all_cases_contract_valid'] = True
        forged['cases'][1]['valid'] = True
        with self.assertRaises(IntegrityError):
            self.freeze(cases, forged)
        self.assertFalse((self.root / 'benchmark.json').exists())

    def test_freeze_reauthorizes_current_grants(self):
        case = self.case()
        request = study_request(self.f, hypotheses=('financial_deterioration',))
        recipient = AccessContext('synthetic-recipient', self.f.access.allowed_providers)
        grants = [SourceGrant(self.f.service, self.f.access, binding.snapshot,
                  request.data_request(binding), binding.provider) for binding in request.bindings]
        service = ScopedReadService(recipient.scope, lambda: tuple(grants))
        context = lambda item: (service, recipient)
        case['scope'] = recipient.scope
        validation = self.validate([case], context)
        self.assertTrue(validation['all_cases_contract_valid'])
        grants.clear()
        with self.assertRaises(PermissionDenied):
            self.freeze([case], validation, context)


if __name__ == '__main__':
    unittest.main()
