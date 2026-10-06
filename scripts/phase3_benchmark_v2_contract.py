"""Benchmark v2 preregistration gate, independent of Agent execution/results.

The legacy source gate remains unchanged. This wrapper validates the new case
schema, pinned files, declared source scopes and explicit event subwindows. It
does not calculate expected Hypothesis outcomes, select replacement events,
contact providers or accept an Agent response as an input.
"""
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re

from stock_research.errors import IntegrityError, PermissionDenied, ValidationError
from stock_research.models import AccessContext, QueryContext, digest
from stock_research.research.study_contracts import StudyRequest

from phase3_benchmark_gate import precheck_cases, snapshot_metadata, write_new


VERSION = 'phase3-benchmark-contract/v2'
ROOT = Path(__file__).resolve().parents[1]
CN = timezone(timedelta(hours=8))
HEX = re.compile(r'[0-9a-f]{64}\Z')
CASE_FIELDS = frozenset({'id', 'case_id', 'version', 'level', 'research_question',
    'split', 'novelty', 'scope', 'request', 'source_scopes', 'event',
    'expected_behavior', 'success_criteria', 'contract_version', 'source_hashes'})
STATUSES = frozenset({'supported', 'unsupported', 'conflicted', 'insufficient'})
DATE_ALIGNMENT = 'exact-date-only-no-interpolation'
CONTRACT_CATEGORY = 'benchmark_or_request_contract_defect'


def _nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def _dates(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError('explicit two-date inclusive window required')
    start, end = (date.fromisoformat(item) for item in value)
    if start > end:
        raise ValueError('reversed explicit window')
    return start, end


def _close(row):
    values = [m['value'] for m in row.get('metrics', []) if m.get('name') == 'close']
    if len(values) != 1 or values[0] is None:
        return None
    try:
        value = Decimal(str(values[0]))
    except InvalidOperation:
        return None
    return value if value.is_finite() and value > 0 else None


def _pinned_files(case, root):
    mapping = case.get('source_hashes')
    if not isinstance(mapping, dict) or not mapping:
        return False
    for name, expected in mapping.items():
        if not _nonempty_text(name) or not isinstance(expected, str) or not HEX.fullmatch(expected):
            return False
        path = Path(name)
        # Inputs are public/source artifacts and review scripts, never credentials.
        if path.is_absolute() or path.name.lower() in {'test_api.txt', 'tushare.txt', '.env'}:
            return False
        target = (root / path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return False
        sha = hashlib.sha256()
        with target.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                sha.update(block)
        if sha.hexdigest() != expected:
            return False
    return True


def _outer(case, source_context, repository_root):
    checks, issues = {}, []
    details = {'event': None, 'source_scopes': {}, 'date_alignment_policy': None}

    def check(name, valid, detail):
        checks[name] = bool(valid)
        if not valid:
            issues.append({'category': CONTRACT_CATEGORY, 'code': name,
                           'detail': detail, 'blocks_freeze': True})

    check('case_schema_complete', CASE_FIELDS <= case.keys(), 'Required v2 case fields are missing')
    check('case_identity', _nonempty_text(case.get('id')) and case.get('case_id') == case.get('id')
          and _nonempty_text(case.get('version')), 'Case ID and explicit version must agree')
    check('research_question', _nonempty_text(case.get('research_question')),
          'A concrete research question must be preregistered')
    check('level_and_split', case.get('level') in {'L3', 'L5'}
          and case.get('split') in {'development', 'validation', 'independent_test'},
          'Explicit L3/L5 and development/validation/independent_test are required')
    check('novelty_declared', isinstance(case.get('novelty'), dict) and bool(case['novelty']),
          'Novelty and prior use must be declared without claiming unsupported blindness')
    check('contract_version', case.get('contract_version') == VERSION,
          'Case must declare the explicit v2 contract version')
    check('source_files_pinned', _pinned_files(case, repository_root),
          'Every declared source file must exist within the input root and match its SHA256')
    criteria = case.get('success_criteria')
    check('success_criteria', isinstance(criteria, list) and bool(criteria)
          and all(_nonempty_text(item) for item in criteria),
          'Nonempty auditable success criteria must exist before execution')
    try:
        request = StudyRequest.from_dict(case['request'])
    except (KeyError, TypeError, ValueError, ValidationError):
        check('request_schema', False, 'StudyRequest cannot be parsed')
        return checks, issues, details
    expected = case.get('expected_behavior')
    expected_hypotheses = expected.get('hypotheses') if isinstance(expected, dict) else None
    expected_valid = (isinstance(expected_hypotheses, dict)
        and set(expected_hypotheses) == set(request.hypotheses)
        and all(isinstance(item, dict) and bool(item) for item in expected_hypotheses.values())
        and isinstance(expected.get('mandatory_fact_names'), list)
        and all(_nonempty_text(item) for item in expected['mandatory_fact_names'])
        and isinstance(expected.get('diagnostic_codes'), list)
        and all(_nonempty_text(item) for item in expected['diagnostic_codes']))
    if expected_valid:
        for item in expected_hypotheses.values():
            if 'status' in item:
                expected_valid &= isinstance(item['status'], str) and item['status'] in STATUSES
            if 'permitted_statuses' in item:
                statuses = item['permitted_statuses']
                expected_valid &= (isinstance(statuses, list) and bool(statuses)
                    and all(isinstance(status, str) and status in STATUSES for status in statuses))
    check('expected_behavior', expected_valid,
          'Each required Hypothesis and the mandatory facts/diagnostics need preregistered expectations')
    if 'market_direction' in request.hypotheses:
        check('date_alignment_policy', case.get('date_alignment_policy') == DATE_ALIGNMENT,
              'Current bounded Runtime supports only preregistered exact-date comparison without interpolation')
        details['date_alignment_policy'] = case.get('date_alignment_policy')
    service, access = source_context(case)
    check('source_scope', access.scope == case.get('scope'),
          'The trusted application recipient scope must match the case')
    owners = case.get('source_scopes')
    check('source_scopes_complete', isinstance(owners, dict)
          and set(owners) == {binding.dataset for binding in request.bindings}
          and all(_nonempty_text(value) for value in owners.values()),
          'Each bound Dataset needs an explicit source owner scope')
    source_rows = {}
    for binding in request.bindings:
        if binding.provider not in access.allowed_providers:
            raise PermissionDenied('v2 benchmark provider is not authorized')
        narrowed = AccessContext(access.scope, frozenset({binding.provider}))
        context = QueryContext(narrowed, binding.snapshot, request.as_of, request.mode)
        # Ordinary reauthorized reads; no repository-only financial values.
        result = service.query(request.data_request(binding), context)
        if result.snapshot_id != binding.snapshot or result.as_of_date != context.as_of_date:
            raise IntegrityError('v2 source query identity differs')
        source_rows[binding.dataset] = [(row.record_id, row.to_dict()) for row in result.records]
        metadata = snapshot_metadata(service, request, binding, narrowed)
        owner_scope = metadata['owner_scope']
        details['source_scopes'][binding.dataset] = owner_scope
        check('owner_scope_' + binding.dataset, isinstance(owners, dict)
              and owners.get(binding.dataset) == owner_scope,
              'Declared owner scope differs from the current trusted source grant')
    required_event = 'event_chronology' in request.hypotheses
    if not required_event:
        check('event_not_invented', case.get('event') is None and case.get('level') != 'L5',
              'A non-event task must not invent an event; every L5 must require event chronology')
        return checks, issues, details
    event = case.get('event')
    fields = {'record_id', 'event_type', 'dataset', 'source', 'version',
              'release_precision', 'before_window', 'after_window', 'market_dataset', 'snapshot'}
    check('event_schema', isinstance(event, dict) and fields <= event.keys(),
          'Event identity/source/version/precision and explicit market subwindows are required')
    if not isinstance(event, dict) or not fields <= event.keys():
        return checks, issues, details
    check('event_record_id', request.event_record_id == event['record_id'],
          'Manifest event ID differs from the exact StudyRequest event ID')
    check('event_type', _nonempty_text(event['event_type']), 'Event type must be explicit')
    matched = [(name, row) for name, rows in source_rows.items() for rid, row in rows
               if rid == request.event_record_id]
    check('event_visible_unique', len(matched) == 1,
          'Exact target event must be uniquely present in normally authorized PIT-visible data')
    if len(matched) != 1:
        return checks, issues, details
    dataset, row = matched[0]
    check('event_dataset', event['dataset'] == dataset, 'Manifest event Dataset differs from source')
    source = {name: row.get(name) for name in ('provider', 'source_url', 'source_key')}
    version = {name: row.get(name) for name in ('provider_version', 'revision_id')}
    check('event_source', event['source'] == source, 'Manifest event source differs from the pinned record')
    check('event_version', event['version'] == version,
          'Manifest event version differs from the visible selected source version')
    precision = {'verified_release_date': 'date_conservative_next_day',
                 'verified_release': 'timestamp'}.get(row.get('availability_basis'))
    check('event_release_precision', precision is not None and event['release_precision'] == precision,
          'Event precision must match qualified release evidence, never capture time')
    market_binding = next(binding for binding in request.bindings if binding.dataset == 'market_daily')
    check('event_market_binding', event['market_dataset'] == 'market_daily'
          and event['snapshot'] == market_binding.snapshot,
          'Event price snapshot must match the bound market Dataset')
    try:
        before_start, before_end = _dates(event['before_window'])
        after_start, after_end = _dates(event['after_window'])
        in_binding = (market_binding.start <= before_start <= before_end <= market_binding.end
                      and market_binding.start <= after_start <= after_end <= market_binding.end)
        check('event_windows_in_binding', in_binding,
              'Explicit before/after windows must be inside the immutable market binding')
        if precision == 'date_conservative_next_day':
            release = date.fromisoformat(row['release_date'])
            before_rule = lambda day: day < release
            after_rule = lambda day: day >= release + timedelta(days=1)
            strict_after_rule = after_rule
        elif precision == 'timestamp':
            release = datetime.fromisoformat(row['published_at'])
            if release.utcoffset() is None:
                raise ValueError('aware event release required')
            before_rule = lambda day: datetime.combine(day, time(15), CN) < release
            after_rule = lambda day: datetime.combine(day, time(15), CN) >= release
            strict_after_rule = lambda day: datetime.combine(day, time(15), CN) > release
        else:
            raise ValueError('qualified event precision required')
        check('event_window_order', before_rule(before_end) and strict_after_rule(after_start)
              and before_end < after_start,
              'The entire before window must precede and after window follow the qualified event boundary')
        prices = [row for _, row in source_rows['market_daily'] if _close(row) is not None
                  and datetime.combine(date.fromisoformat(row['period']), time(15), CN) <= request.as_of]
        before = sorted(row['period'] for row in prices if before_rule(date.fromisoformat(row['period'])))
        after = sorted(row['period'] for row in prices if after_rule(date.fromisoformat(row['period'])))
        before_in = [day for day in before if before_start <= date.fromisoformat(day) <= before_end]
        after_in = [day for day in after if after_start <= date.fromisoformat(day) <= after_end]
        check('actual_event_market_observations', bool(before_in) and bool(after_in),
              'Each explicit event side requires a real positive PIT-visible closing price at or before cutoff')
        check('runtime_event_endpoints_in_declared_windows', bool(before) and bool(after)
              and before[-1] in before_in and after[-1] in after_in,
              'Current Runtime uses last pre/post endpoints; those endpoints must satisfy the declared subwindows')
        details['event'] = {'record_id': request.event_record_id, 'dataset': dataset,
            'source': source, 'version': version, 'release_precision': precision,
            'observed_before': before_in, 'observed_after': after_in,
            'runtime_before_endpoint': before[-1] if before else None,
            'runtime_after_endpoint': after[-1] if after else None}
    except (KeyError, TypeError, ValueError):
        check('event_windows_parseable', False, 'Explicit event windows or qualified release cannot be parsed')
    return checks, issues, details


def validate_cases(cases, source_context, *, repository_root=ROOT):
    """Run the existing source gate first, then v2 preregistration checks."""
    cases = list(cases)
    root = Path(repository_root).resolve()
    legacy = precheck_cases(cases, source_context)
    results = []
    for case, verdict in zip(cases, legacy['cases']):
        checks, issues, details = _outer(case, source_context, root)
        valid = False if issues or verdict['valid'] is False else verdict['valid']
        results.append({'id': case['id'], 'case_id': case.get('case_id'),
            'valid': valid, 'contract_valid': valid,
            'request_sha256': verdict['request_sha256'], 'validation_checks': checks,
            'issues': verdict['issues'] + issues, 'legacy_validation': verdict,
            'outer_details': details})
    return {'schema': VERSION, 'candidate_sha256': digest(cases), 'case_count': len(cases),
        'valid_case_count': sum(row['valid'] is True for row in results),
        'invalid_case_count': sum(row['valid'] is False for row in results),
        'not_assessable_case_count': sum(row['valid'] is None for row in results),
        'all_cases_contract_valid': all(row['valid'] is True for row in results),
        'issue_taxonomy': dict(Counter(issue['code'] for row in results for issue in row['issues'])),
        'provider_network_calls': 0, 'generation_model_calls': 0, 'cases': results}


def freeze_benchmark(path, cases, validation, *, benchmark_version, implementation_version,
                     parent_manifest_sha256, source_context, repository_root=ROOT, protocol=None):
    """Reauthorize and validate the whole v2 batch immediately before exclusive write."""
    fresh = validate_cases(cases, source_context, repository_root=repository_root)
    if fresh != validation or not fresh['all_cases_contract_valid']:
        raise IntegrityError('v2 freeze blocked: whole batch must be freshly contract-valid')
    if (not _nonempty_text(benchmark_version) or not _nonempty_text(implementation_version)
            or not isinstance(parent_manifest_sha256, str) or not HEX.fullmatch(parent_manifest_sha256)):
        raise IntegrityError('new v2 benchmark and implementation lineage are required')
    manifest = {'schema': 'phase3-contract-gated-benchmark-v2', 'benchmark_version': benchmark_version,
        'implementation_version': implementation_version, 'contract_version': VERSION,
        'parent_manifest_sha256': parent_manifest_sha256, 'candidate_sha256': digest(cases),
        'contract_validation_sha256': digest(fresh), 'original_scores_modified': False,
        'cases': list(cases), 'contract_validation': fresh}
    if protocol is not None:
        manifest['evaluation_protocol'] = protocol
    write_new(path, manifest)
    return manifest
