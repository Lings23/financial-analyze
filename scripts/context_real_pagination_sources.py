"""Real immutable source task for pagination validation, not new financial data.

The new request is an explicit four-dataset subset of a retained public-source
case.  Original requests, snapshots, records and scores are never rewritten.
Byte projections are labelled diagnostics and cannot enter model dispatch.
"""
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from phase3_benchmark_v2 import CampaignSources
from phase3_benchmark_v2_contract import validate_cases
from phase4_demo import authorized_envelope
import phase3_benchmark_v2_oracle as independent
from stock_research.errors import IntegrityError
from stock_research.models import canonical_json, digest
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest, ParallelParentSpec, required_checks
from stock_research.research.dynamic_protocol import dynamic_messages, observe_tool
from stock_research.research.tools import read_domain
from stock_research.research.study import calculate_study_claims
from stock_research.research.hypotheses import test_hypotheses, diagnose_insufficiency
from stock_research.research.verification import verify
from stock_research.research.context_window import _prepared, _collection
from stock_research.research.context_window_metadata import decode_window_metadata_view

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / '.artifacts/phase3/benchmark-v2-20261004/benchmark-manifest.json'
BASE_CASE_ID = 'b2-l3-roster-301600'
CASE_ID = 'real-page-301600-claim-audit-20261008'
SCOPE = 'context-real-page-20261008/' + CASE_ID
DATASETS = frozenset({'financial_income', 'financial_cashflow', 'market_daily', 'adjustment_factor'})
TARGET_NAMES = ('factor_adjusted_price_change', 'observed_max_drawdown', 'revenue_yoy',
                'net_income_parent_yoy', 'financial_cashflow.cash_begin',
                'financial_cashflow.cash_end', 'financial_cashflow.cash_net_change')
GOAL = (
    '财务和行情独立取证，用两个既有Child并行。完成计算和假设检验后，完整核对复权价格变化、最大回撤、'
    '收入/归母净利润同比、期初/期末现金和现金净增加额七项Claim的数值、公式、期间及有序输入引用。'
    '先补读未显示的事实，把已定位的引用记入plan，再合并读取七项完整对象并沿当前续段入口读完；'
    '最后执行全量verification，保留全部事实、证据和缺口。'
)
VERSIONS = {'baseline': 'dynamic-parent-parallel-v5', 'candidate': 'dynamic-parent-parallel-v6.2'}


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    import json
    return json.loads(Path(path).read_bytes())


def spec_for(variant):
    if variant not in VERSIONS:
        raise IntegrityError('unregistered real pagination variant')
    return ParallelParentSpec(version=VERSIONS[variant])


def build_case():
    manifest = read(MANIFEST)
    base = next(case for case in manifest['cases'] if case['id'] == BASE_CASE_ID)
    if sha(ROOT / base['input_path']) != base['input_sha256']:
        raise IntegrityError('original real source input changed')
    case = deepcopy(base)
    request = deepcopy(base['request'])
    request['bindings'] = [binding for binding in request['bindings'] if binding['dataset'] in DATASETS]
    request['benchmark'] = None
    request['hypotheses'] = [hid for hid in request['hypotheses'] if hid != 'market_direction']
    if {binding['dataset'] for binding in request['bindings']} != DATASETS:
        raise IntegrityError('new pagination goal lacks an original real dataset')
    if any(hid not in {'financial_deterioration', 'cashflow_divergence', 'mechanical_adjustment', 'absolute_profit_change'}
           for hid in request['hypotheses']):
        raise IntegrityError('new narrowed task cannot retain a benchmark/event hypothesis')
    case.update(id=CASE_ID, case_id=CASE_ID, scope=SCOPE, request=request,
        research_question=GOAL, source_scopes={name: base['source_scopes'][name] for name in sorted(DATASETS)},
        parent_case_id=BASE_CASE_ID, split='validation',
        novelty={'new_case_id': True, 'new_request': True, 'new_security': False,
                 'new_source_records': False, 'blind': False,
                 'underlying_material_previously_development_or_quality_checked': True},
        pagination_goal={'target_names': list(TARGET_NAMES), 'complete_claim_objects': True,
                         'full_evidence_object_text_required': False,
                         'initial_ref_then_actual_cursor': True, 'minimum_actual_page_reads': 2},
        original_case_ref={'path': MANIFEST.relative_to(ROOT).as_posix(), 'sha256': sha(MANIFEST),
                           'case_id': BASE_CASE_ID, 'input_path': base['input_path'], 'input_sha256': base['input_sha256']},
        independent_new_task_count=1)
    # Those paths belong to the original request; never pretend the new request
    # is equal to its old input freeze or inherit its prior evaluation verdict.
    case.pop('input_path', None)
    case.pop('input_sha256', None)
    case['datasets'] = sorted(DATASETS)
    case['snapshots'] = {binding['dataset']: binding['snapshot'] for binding in request['bindings']}
    case['hypotheses'] = list(request['hypotheses'])
    case['expected_behavior']['hypotheses'] = {hid: value for hid, value in case['expected_behavior']['hypotheses'].items()
                                              if hid in request['hypotheses']}
    case['scope_derivation'] = {
        'new_nonblind_validation_task': True, 'new_financial_sample': False,
        'removed_from_new_task': ['index_daily binding', 'benchmark', 'market_direction hypothesis'],
        'reason': 'this new goal audits stock/financial calculations, not stock-to-index direction',
        'all_remaining_original_sources_cutoff_pit_windows_preserved': True,
        'old_request_and_score_unchanged': True}
    case['success_criteria'] = [
        'Complete four-dataset source-bound facts, evidence, requested hypotheses, counterevidence and lawful gaps.',
        'Real configured model selects registered refs then current continuation cursor; complete target object coverage.',
        'Actual original verification and finish within unchanged budgets; committed-page and completed recovery.',
        'No model substitution, synthetic row expansion, modified model response or old-source/PIT rewrite.']
    case['source_hashes'] = {path: value for path, value in base['source_hashes'].items()
                             if path != base['input_path']}
    return case


def context(case=None):
    case = build_case() if case is None else case
    case = case.get('case', case)
    sources = CampaignSources()
    return sources.context(case)


def catalogue_observations(service, access, request):
    outputs = {domain: read_domain(service, request, access, domain) for domain in ('financial', 'market')}
    datasets = {name: value for output in outputs.values() for name, value in output.items()}
    if set(datasets) != DATASETS:
        raise IntegrityError('declared four-dataset task was not completely read')
    computed = calculate_study_claims(datasets, request, profit_change='absolute_profit_change' in request.hypotheses)
    computed['hypotheses'] = test_hypotheses(computed, datasets, request)
    computed['insufficiency_diagnostics'] = diagnose_insufficiency(computed, datasets, request)
    verification = verify(computed, datasets, request)
    observations = {'O:' + domain: observe_tool(domain, output) for domain, output in outputs.items()}
    observations['O:calculation'] = observe_tool('calculation', {**computed, 'hypotheses': []})
    observations['O:hypotheses'] = observe_tool('hypotheses', computed)
    observations['O:verification'] = observe_tool('verification', verification)
    return observations, computed, datasets


def independent_oracle(case, inputs, computed):
    selected, bindings, checks = independent.select_inputs(case, inputs)
    if not all(checks.values()):
        raise IntegrityError('independent full snapshot/PIT/authorization selection failed')
    facts, evidence, anchor, _, _ = independent.expected_facts(selected, bindings, case['request'])
    hypotheses = independent.expected_hypotheses(facts, evidence, selected, case['request'], anchor)
    actual = {fact['name']: fact for fact in computed['facts']}
    if len(actual) != len(computed['facts']) or set(actual) != set(facts) or set(computed['evidence']) != set(evidence):
        raise IntegrityError('independent source oracle fact/evidence set differs')
    for name, expected in facts.items():
        fact = actual[name]
        exact = Fraction(*expected['fraction'])
        tolerance = (Fraction(0) if expected['formula'] == independent.FORMULAS['identity']
            or name == 'financial_income.absolute_profit_change' else
            max(Fraction(1, 10 ** 28), abs(exact) * Fraction(1, 10 ** 28)))
        if (abs(Fraction(fact['value']) - exact) > tolerance
                or any(fact[key] != expected[key] for key in ('name', 'unit', 'formula', 'window', 'available_at'))
                or fact['inputs'] != expected['inputs']
                or fact['id'] != digest({key: value for key, value in fact.items() if key != 'id'})):
            raise IntegrityError('independent Fraction oracle differs from complete source claim')
    for eid, expected in evidence.items():
        if computed['evidence'][eid] != expected:
            raise IntegrityError('independent original source Evidence metadata differs')
    actual_hypotheses = {hypothesis['id']: hypothesis for hypothesis in computed['hypotheses']}
    if set(actual_hypotheses) != set(hypotheses):
        raise IntegrityError('independent requested hypothesis set differs')
    for key, expected in hypotheses.items():
        actual_h = actual_hypotheses[key]
        fields = ('status', 'reason', 'required_evidence', 'test_rule', 'anchor_record_id',
                  'conclusion_strength', 'causal_claim', 'coverage')
        # Titles/rule prose are inherited immutable application metadata, not
        # financial truth. Source status, input references and counterevidence
        # are independently reconstructed; report projection is checked fully.
        fields = tuple(field for field in fields if field != 'test_rule')
        if (any(actual_h[field] != expected[field] for field in fields)
                or actual_h['claim_ids'] != [actual[name]['id'] for name in expected['claim_names']]
                or actual_h['counterevidence_claim_ids'] != [actual[name]['id'] for name in expected['counterevidence_claim_names']]):
            raise IntegrityError('independent complete hypothesis status/reason differs')
    return {'schema': 'real-pagination-independent-source-fraction/v1',
        'selection_checks': checks, 'facts': facts, 'evidence': evidence, 'hypotheses': hypotheses,
        'source_record_ids': {name: [independent.rid(row) for row in rows] for name, rows in selected.items()},
        'fact_count': len(facts), 'evidence_count': len(evidence), 'financial_ground_truth_claim': False,
        'scope': 'complete four-dataset source transformation and Fraction checks; retained raw artifacts separately verified'}


def build_task():
    case = build_case()
    sources = CampaignSources()
    service, access = sources.context(case)
    validation = validate_cases([case], sources.context)
    if not validation['all_cases_contract_valid']:
        raise IntegrityError('new real pagination task is not contract-valid')
    request = DynamicRequest.from_dict({**case['request'], 'question': GOAL})
    inputs = sources.inputs(case)
    observations, computed, datasets = catalogue_observations(service, access, request)
    oracle = independent_oracle(case, inputs, computed)
    claims = {ref: deepcopy(fact) for ref, fact in observations['O:hypotheses']['facts'].items()
              if fact['name'] in TARGET_NAMES}
    if {fact['name'] for fact in claims.values()} != set(TARGET_NAMES):
        raise IntegrityError('real source cannot support the preregistered reading targets')
    return {'schema': 'real-pagination-task-material/v1', 'case': case, 'request': request.to_dict(),
        'request_by_variant': {variant: request.to_dict() for variant in VERSIONS},
        'scope': access.scope, 'inputs': inputs, 'input_ref': digest(inputs), 'contract_validation': validation,
        'source_payload_sha256': digest(inputs),
        'authorization_envelope': authorized_envelope(service, access, request),
        'catalog_observations': observations, 'independent_oracle': oracle, 'oracle': oracle,
        'goal_refs': sorted('C:' + ref for ref in claims),
        'goal_claims': {'C:' + ref: value for ref, value in sorted(claims.items())},
        'goal_objects': {'C:' + ref: value for ref, value in sorted(claims.items())},
        'required_check_ids': required_checks(request),
        'expected_status': 'insufficient' if any(value['status'] == 'insufficient'
            for value in observations['O:hypotheses']['hypotheses'].values()) else 'completed',
        'target_names': list(TARGET_NAMES), 'new_task_not_original_five_binding_case': True,
        'model_calls': 0, 'financial_provider_network_calls': 0, 'checkpoint_appends': 0}


def state_projection(item, state, variant, *, diagnostic=False, context_refs=None, decision=None):
    runner = DynamicRuntime(None, None, None, spec_for(variant))
    request = DynamicRequest.from_dict(item['request'])
    access = type('BoundScope', (), {'scope': item['scope']})()
    arguments = runner._context_arguments(state, access,
        paid_decision=state['decisions'][-1] if state['phase'] == 'model_pending' else None)
    if context_refs is not None:
        arguments['context_refs'] = list(context_refs)
    tools = item.get('available_tools')
    if tools is None:
        import json
        tools = json.loads(item['messages'][1]['content'])['available_tools']
    return dynamic_messages(request, tools, list(state['observations'].values()), state['requirements'],
        state['plans'][-1]['steps'] if state['plans'] else [], 4_000_000 if diagnostic else 12000,
        decision=state['decisions'][-1]['turn'] if decision is None else decision, version=VERSIONS[variant],
        protocol_error=state.get('protocol_error'), finish_rejection=state.get('finish_rejection'),
        delegation_results=[{'tool': child['domain'] + '_child', 'domain': child['domain'],
            'status': child['status'], 'result_ref': child['result_ref']} for child in state['child_results']],
        **arguments)


def baseline_disclosure(item, state, *, context_refs=None, decision=None):
    """Pure diagnostic only; increasing this sizing bound never dispatches."""
    return state_projection(item, state, 'baseline', diagnostic=True,
        context_refs=item['goal_refs'] if context_refs is None else context_refs, decision=decision)


def exact_goal_collection(item, state):
    request = DynamicRequest.from_dict(item['request'])
    access = type('BoundScope', (), {'scope': item['scope']})()
    runner = DynamicRuntime(None, None, None, spec_for('candidate'))
    catalog = runner._build_catalog(state, request, access)
    prepared = _prepared(catalog, item['scope'], item['run_id'])
    collection = _collection(catalog, prepared, 'objects', item['goal_refs'])
    if {ref: prepared[2][ref] for ref in item['goal_refs']} != item['goal_claims']:
        raise IntegrityError('current target objects differ from frozen complete real claims')
    return catalog, collection


def assess_complete(item, report):
    expected = item['catalog_observations']['O:hypotheses']
    actual = observe_tool('hypotheses', report)
    checks = {'expected_status': report['status'] == item['expected_status'],
        'complete_fact_evidence_hypothesis_gap_lineage_equal': actual == expected,
        'original_full_verification_passed': report['verification']['status'] == 'verified',
        'actual_verification_executed_once': sum(event['event'] == 'tool_finished'
            and event.get('tool') == 'verification' for event in report['trace']) == 1,
        'no_uncompleted_required_checks': all(check['status'] != 'not_completed' for check in report['required_checks']),
        'independent_source_fraction_oracle_frozen': item['independent_oracle']['fact_count'] == len(report['facts'])}
    return {'functional_passed': all(checks.values()), 'checks': checks}


def raw_context(view):
    return decode_window_metadata_view(view)


def frozen_source_payload(task):
    return deepcopy(task['inputs'])


def preview(task, variant, run_id):
    service, access = context(task)
    return DynamicRuntime(service, None, None, spec_for(variant)).preview(
        DynamicRequest.from_dict(task['request']), access, run_id=run_id)


projection = state_projection
