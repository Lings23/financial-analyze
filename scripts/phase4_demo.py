"""Prepare, execute or replay three bounded M1 demonstrations on existing sources.

Preparation is an input/authorization audit, not a dynamic Agent execution. It
creates no model or Provider calls. The live strategy starts at the first model
decision and never consumes a precomputed workflow as its execution state.
"""
import argparse
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path
import re

from phase3_benchmark_v2 import CampaignSources, candidate, ROOT
from phase3_benchmark_v2_contract import validate_cases
from phase3_benchmark_gate import write_new
from phase3_contract_audit import read, sha
from stock_research.errors import DataError, IntegrityError, ValidationError
from stock_research.model_adapters.chat import ChatModelAdapter, load_model_config
from stock_research.models import canonical_json, digest, utcnow
from stock_research.research.checkpoints import CheckpointStore
from stock_research.research.contracts import DOMAINS
from stock_research.research.dynamic import DynamicRuntime
from stock_research.research.dynamic_contracts import DynamicRequest, DynamicSpec
from stock_research.research.dynamic_protocol import (SYSTEM, _plan, _unique_object, _validate_observation,
                                                     bound_required_checks, observe_tool)
from stock_research.research.hypotheses import test_hypotheses
from stock_research.research.report import markdown
from stock_research.research.runtime import validate_model_result
from stock_research.research.study import calculate_study_claims
from stock_research.research.tools import read_domain

OUT = ROOT / '.artifacts/phase4/m1-20261004'
PARENT = ROOT / '.artifacts/phase3/benchmark-v2-20261004/benchmark-manifest.json'
SPEC = DynamicSpec()
SELECTION = (
    ('complete-financial', 'b2-l3-roster-002363',
     '核对已绑定2025半年报与2024半年报的营业收入和归母净利润同比，检验两者是否同时下降；'
     '报告可核查数值、反证和本次实际观察行情。按Observation安排合法工具，完成必需检查后结束。'),
    ('replan-missing-prior', 'b2-l3-missing-prior-000531',
     '先读取2025Q1财务证据检查同比条件；若Observation表明缺少2024Q1基数，调整计划转向本次冻结行情取证，'
     '报告实际观察价格变化和回撤，同时明确财务同比证据不足。禁止用半年报替代或补零；完成可用检查后以不足结束。'),
    ('insufficient-missing-prior', 'b2-l3-missing-prior-601009',
     '核对2025Q1营业收入和归母净利润同比及本次实际观察行情；若本次合法快照缺2024Q1同期基数，'
     '明确报告财务证据不足，保留已核验当前金额与行情，不猜测缺失值，以受控不足结束。'),
)


def build_tasks(manifest):
    """New, preregistered tasks retain parent inputs; no old scores are rewritten."""
    parents = {case['id']: case for case in manifest['cases']}
    tasks = []
    for role, parent_id, question in SELECTION:
        original = parents[parent_id]
        request = deepcopy(original['request'])
        request['bindings'] = [binding for binding in request['bindings']
                               if binding['dataset'] in {'market_daily', 'financial_income'}]
        request.update(hypotheses=['financial_deterioration'], objective='single_stock_research', event_record_id=None,
                       benchmark=None)
        request.pop('hypothesis_version', None)
        identity = 'm1-' + role
        owners = {binding['dataset']: original['source_scopes'][binding['dataset']]
                  for binding in request['bindings']}
        case = candidate(identity, 'L3', question, request, owners, stratum=role,
                         mandatory=['financial_income.net_income_parent', 'observed_price_change', 'observed_max_drawdown'],
                         diagnostics=[] if role == 'complete-financial' else ['missing_report_period'],
                         allow_insufficient=role != 'complete-financial')
        case.update(scope='phase4-m1-20261004/' + identity, version='dynamic-demo/v1',
                    parent_case_id=parent_id, source_hashes=deepcopy(original['source_hashes']))
        case['novelty'].update(used_for_case_or_prompt_tuning=False, blind=False)
        case['expected_behavior']['model'] = 'Observation-driven JSON actions; no preconstructed action sequence.'
        case['success_criteria'] = [
            'Actual Model -> Tool -> typed Observation -> Model loop with independently verified numbers and references.',
            'All preregistered required checks remain visible; no source, snapshot, cutoff, PIT or permission expansion.',
            ('Completed financial_deterioration with a decisive supported/unsupported/conflicted state.'
             if role == 'complete-financial' else 'Source-proven missing prior Q1 remains insufficient; never substitute H1 or invent YoY.'),
            ('Financial source is read before market, then the visible plan changes after the financial Observation.'
             if role == 'replan-missing-prior' else 'Visible model plans and tool records are preserved.'),
        ]
        tasks.append(case)
    return tasks


def claim_signatures(derived):
    evidence = derived['evidence']
    return sorted(digest({**{key: value for key, value in fact.items() if key != 'evidence_ids'},
                          'input_values': sorted((evidence[eid] for eid in fact['evidence_ids']), key=canonical_json)})
                  for fact in derived['facts'].values())


def authorized_envelope(service, access, request):
    """Bound all possible outbound values for review; this is not a Runtime run."""
    outputs = {name: read_domain(service, request, access, name)
               for name in sorted({DOMAINS[b.dataset] for b in request.bindings})}
    datasets = {key: value for output in outputs.values() for key, value in output.items()}
    computed = calculate_study_claims(datasets, request)
    computed['hypotheses'] = test_hypotheses(computed, datasets, request)
    derived = observe_tool('hypotheses', computed)
    return {'kind': 'offline_authorization_envelope_not_agent_execution',
            'source_observations': {name: observe_tool(name, output) for name, output in outputs.items()},
            'all_bound_computable_values': derived,
            'claim_signatures': claim_signatures(derived),
            'evidence_signatures': sorted(digest(value) for value in derived['evidence'].values()),
            'provider_network_calls': 0, 'model_calls': 0}


def implementation_files():
    files = {path.relative_to(ROOT).as_posix(): sha(path) for path in (ROOT / 'src').rglob('*.py')}
    for name in ('phase4_demo.py', 'phase3_benchmark_v2.py', 'phase3_benchmark_v2_contract.py',
                 'phase3_benchmark_gate.py', 'phase3_contract_audit.py'):
        path = ROOT / 'scripts' / name
        files[path.relative_to(ROOT).as_posix()] = sha(path)
    return files


def prepare(output=OUT):
    output = Path(output)
    if output.exists():
        raise IntegrityError('M1 proposal directory already exists; use a new version')
    manifest = read(PARENT)
    sources = CampaignSources()
    selected = [next(case for case in manifest['cases'] if case['id'] == parent_id)
                for _, parent_id, _ in SELECTION]
    parent_validation = validate_cases(selected, sources.context)
    if not parent_validation['all_cases_contract_valid']:
        raise IntegrityError('selected parent input contracts no longer valid')
    tasks = build_tasks(manifest)
    previews = []
    for case in tasks:
        inputs = sources.inputs(case)
        input_path = output / 'inputs' / (case['id'] + '.json')
        write_new(input_path, inputs)
        case['input_path'] = input_path.relative_to(ROOT).as_posix()
        case['input_sha256'] = sha(input_path)
        case['source_hashes'][case['input_path']] = case['input_sha256']
        service, access = sources.context(case)
        request = DynamicRequest.from_dict({**case['request'], 'question': case['research_question']})
        envelope = authorized_envelope(service, access, request)
        status = envelope['all_bound_computable_values']['hypotheses']['financial_deterioration']['status']
        if (case['stratum'] == 'complete-financial') != (status != 'insufficient'):
            raise IntegrityError('preregistered source eligibility differs; do not replace or relabel tasks')
        periods = envelope['source_observations']['financial']['datasets']['financial_income']['periods']
        missing_gaps = {'revenue:yoy_prior_year_period_not_visible', 'net_income_parent:yoy_prior_year_period_not_visible'}
        if case['stratum'] != 'complete-financial' and (
                not periods or max(periods) != '2025-03-31' or '2024-03-31' in periods
                or not missing_gaps <= set(envelope['all_bound_computable_values']['gaps'])):
            raise IntegrityError('insufficient demonstration must have source-proven missing prior Q1 for both metrics')
        messages = DynamicRuntime(service, None, None, SPEC).preview(request, access)
        previews.append({'case_id': case['id'], 'request': request.to_dict(), 'messages': messages,
                         'messages_sha256': digest(messages), 'authorization_envelope': envelope,
                         'source_eligibility': {'status': status, 'income_periods': periods,
                                               'missing_prior_q1_for_both_metrics': case['stratum'] != 'complete-financial'}})
    validation = validate_cases(tasks, sources.context)
    if not validation['all_cases_contract_valid']:
        raise IntegrityError('new M1 demonstration contracts must all be valid')
    proposal = {'schema': 'phase4-m1-demonstration-proposal/v1', 'phase': 'prepared_not_executed',
                'parent_manifest_sha256': sha(PARENT), 'parent_contract_validation': parent_validation,
                'contract_validation': validation, 'tasks': tasks, 'previews': previews,
                'spec': {**asdict(SPEC), 'allowed_tools': sorted(SPEC.allowed_tools),
                         'visible_tools': sorted(SPEC.visible_tools)}, 'spec_identity': SPEC.identity,
                'implementation_files': implementation_files(),
                'authorization': {'scope': 'Configured endpoint and fixed model only; no financial Provider calls or data collection.',
                    'current_session_user_authorization': '2026-10-04 user approves LLM data transfer in this session without another confirmation.',
                    'model': SPEC.model, 'task_count': 3, 'max_decisions': 24, 'max_tokens_accounted': 144000,
                    'per_task_max_decisions': 8, 'per_task_max_tokens': 48000,
                    'first_messages_exact': True, 'later_messages': 'Strict typed Observation and control template, frozen bound Claim/Evidence values only.',
                    'source_text_included': False, 'unknown_usage_reservation_retained': True},
                'quality_scope': 'Three functional demonstrations, reused validation sources; no Fixed/Dynamic comparison or broad quality certification.',
                'model_calls': 0, 'provider_network_calls': 0}
    write_new(output / 'proposal.json', proposal)
    return {'prepared': True, 'proposal': str((output / 'proposal.json').resolve()),
            'proposal_sha256': sha(output / 'proposal.json'), 'tasks': 3, 'model_calls': 0, 'provider_network_calls': 0}


def checked_proposal(output=OUT, expected_sha=None):
    output = Path(output)
    proposal = read(output / 'proposal.json')
    if expected_sha is not None and sha(output / 'proposal.json') != expected_sha:
        raise IntegrityError('explicit proposal SHA differs')
    if (proposal.get('schema') != 'phase4-m1-demonstration-proposal/v1' or proposal['spec_identity'] != SPEC.identity
            or len(proposal['tasks']) != 3 or proposal['parent_manifest_sha256'] != sha(PARENT)):
        raise IntegrityError('M1 proposal identity differs')
    for path, expected in proposal['implementation_files'].items():
        if sha(ROOT / path) != expected:
            raise IntegrityError('frozen M1 implementation changed; prepare a new proposal version')
    for case in proposal['tasks']:
        if sha(ROOT / case['input_path']) != case['input_sha256']:
            raise IntegrityError('frozen M1 source inputs changed')
    sources = CampaignSources()
    if validate_cases(proposal['tasks'], sources.context) != proposal['contract_validation']:
        raise IntegrityError('M1 source authorization or contracts changed')
    for case, item in zip(proposal['tasks'], proposal['previews']):
        if case['id'] != item['case_id'] or digest(sources.inputs(case)) != digest(read(ROOT / case['input_path'])):
            raise IntegrityError('M1 bound input values changed')
        service, access = sources.context(case)
        request = DynamicRequest.from_dict(item['request'])
        if (request.to_dict() != {**case['request'], 'question': case['research_question']}
                or DynamicRuntime(service, None, None, SPEC).preview(request, access) != item['messages']
                or authorized_envelope(service, access, request) != item['authorization_envelope']):
            raise IntegrityError('M1 frozen request, first messages or value envelope changed')
    return proposal, sources


def validate_outbound(messages, item, decision):
    """Every exact payload is checked before persistence and paid dispatch."""
    if (not isinstance(messages, list) or len(messages) != 2
            or any(set(message) != {'role', 'content'} for message in messages)
            or messages[0] != {'role': 'system', 'content': SYSTEM} or messages[1]['role'] != 'user'
            or sum(len(message['content'].encode('utf-8')) for message in messages) > SPEC.context_bytes):
        raise IntegrityError('outbound M1 message template differs')
    if decision == 1 and messages != item['messages']:
        raise IntegrityError('outbound first M1 messages differ')
    payload = json.loads(messages[1]['content'], object_pairs_hook=_unique_object)
    first = json.loads(item['messages'][1]['content'])
    mutable = {'control', 'observations', 'completed_tools', 'derived_state'}
    if set(payload) != set(first) or any(payload[key] != first[key] for key in set(first) - mutable):
        raise IntegrityError('outbound immutable M1 scope differs')
    control = payload['control']
    if (not isinstance(control, dict) or set(control) - {'question', 'plan', 'decision', 'previous_action_error'}
            or control.get('question') != item['request']['question'] or control.get('decision') != decision
            or control.get('previous_action_error') not in {None, 'invalid_action', 'duplicate_no_progress', 'tool_failed', 'dependency_not_ready'}):
        raise IntegrityError('outbound dynamic control differs')
    if control.get('plan'):
        _plan(control['plan'])
    elif decision != 1:
        # Schema errors may leave the accepted plan empty on a correction decision.
        if control.get('plan') != []:
            raise IntegrityError('outbound dynamic plan differs')
    request = DynamicRequest.from_dict(item['request'])
    envelope = item['authorization_envelope']
    observations = payload['observations']
    if (not isinstance(observations, list) or len(observations) > 12
            or payload['completed_tools'] != sorted({observation['tool'] for observation in observations})
            or len({observation['tool'] for observation in observations}) != len(observations)):
        raise IntegrityError('outbound typed tool state differs')
    for observation in observations:
        if observation.get('kind') == 'source_read':
            if observation != envelope['source_observations'].get(observation['tool']):
                raise IntegrityError('outbound source Observation differs from frozen inputs')
        elif observation.get('kind') == 'derived':
            if (set(observation) != {'tool', 'kind', 'state_ref', 'result_ref', 'gaps'}
                    or observation['state_ref'] != 'derived_state'
                    or not re.fullmatch('[0-9a-f]{64}', observation['result_ref'])):
                raise IntegrityError('outbound derived state reference differs')
            expanded = {'tool': observation['tool'], 'kind': 'derived', 'gaps': observation['gaps'], **payload['derived_state']}
            _validate_observation(expanded, request)
            if (not set(claim_signatures(expanded)) <= set(envelope['claim_signatures'])
                    or not {digest(value) for value in expanded['evidence'].values()} <= set(envelope['evidence_signatures'])):
                raise IntegrityError('outbound financial values exceed the frozen authorization envelope')
        else:
            _validate_observation(observation, request)
    if payload['derived_state'] is not None and not any(o['kind'] == 'derived' for o in observations):
        raise IntegrityError('outbound derived state has no tool owner')


class RootLedger:
    def __init__(self, max_decisions=24, max_tokens=144000):
        self.max_decisions, self.max_tokens = max_decisions, max_tokens
        self.intents, self.accounted, self.cumulative_reserved = [], 0, 0

    def reserve(self, task, messages, output_tokens):
        amount = sum(len(message['content'].encode('utf-8')) for message in messages) + 256 + output_tokens
        if len(self.intents) >= self.max_decisions or self.accounted + amount > self.max_tokens:
            raise ValidationError('M1 root model or Token budget exceeded before dispatch')
        intent = {'number': len(self.intents) + 1, 'task_id': task, 'messages_sha256': digest(messages),
                  'reservation': amount, 'usage_status': 'unknown', 'total_tokens': None}
        self.intents.append(intent)
        self.accounted += amount
        self.cumulative_reserved += amount
        return intent

    def settle(self, intent, response):
        if not any(existing is intent for existing in self.intents) or intent['usage_status'] != 'unknown':
            raise IntegrityError('M1 receipt was already accounted')
        try:
            validate_model_result(response, SPEC, intent['reservation'])
        except (ValidationError, TypeError, ValueError, AttributeError):
            return
        self.accounted += response.total_tokens - intent['reservation']
        intent.update(usage_status='known', prompt_tokens=response.prompt_tokens,
                      completion_tokens=response.completion_tokens, total_tokens=response.total_tokens)

    def snapshot(self):
        return {'decisions': len(self.intents), 'tokens_accounted': self.accounted,
                'cumulative_tokens_reserved': self.cumulative_reserved,
                'known_tokens': sum(item['total_tokens'] or 0 for item in self.intents),
                'unknown_usage_calls': sum(item['usage_status'] == 'unknown' for item in self.intents),
                'max_decisions': self.max_decisions, 'max_tokens_accounted': self.max_tokens,
                'intents': deepcopy(self.intents)}


def contains_secret(value, secret):
    if not secret:
        return False
    if isinstance(value, str):
        return secret in value
    if isinstance(value, dict):
        return any(contains_secret(key, secret) or contains_secret(item, secret) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_secret(item, secret) for item in value)
    return False


def receipt_reflects_secret(receipt, secret):
    if contains_secret(receipt, secret):
        return True
    content = receipt.get('content', '')
    if isinstance(content, str):
        decoded_escapes = re.sub(r'\\u([0-9a-fA-F]{4})', lambda match: chr(int(match.group(1), 16)), content)
        if contains_secret(decoded_escapes, secret):
            return True
    try:
        # Preserve duplicate keys while decoding escapes; even a rejected raw JSON
        # response cannot smuggle a credential into the retained receipt.
        decoded = json.loads(content, object_pairs_hook=lambda pairs: pairs)
    except (ValueError, TypeError, RecursionError):
        return False
    return contains_secret(decoded, secret)


class RecordingModel:
    def __init__(self, adapter, item, ledger, directory, deadline=None):
        self.adapter, self.config, self.item = adapter, adapter.config, item
        self.ledger, self.directory, self.calls = ledger, Path(directory), 0
        self.deadline = deadline

    def complete(self, messages, **kwargs):
        if self.deadline is not None:
            remaining = (self.deadline - utcnow()).total_seconds()
            if remaining <= 0:
                raise ValidationError('M1 root deadline exceeded before dispatch')
            kwargs['timeout'] = min(kwargs.get('timeout', remaining), remaining)
        validate_outbound(messages, self.item, self.calls + 1)
        key = self.config.api_key
        if key and key in canonical_json(messages):
            raise IntegrityError('credential reflection in outbound messages rejected')
        if kwargs.get('max_tokens') != SPEC.output_tokens or self.calls >= SPEC.max_decisions:
            raise IntegrityError('M1 model output or decision budget differs')
        intent = self.ledger.reserve(self.item['case_id'], messages, SPEC.output_tokens)
        self.calls += 1
        prefix = f"{intent['number']:02d}-{self.item['case_id']}"
        write_new(self.directory / ('messages-' + prefix + '.json'), messages)
        write_new(self.directory / ('intent-' + prefix + '.json'), intent)
        try:
            response = self.adapter.complete(messages, **kwargs)
        except Exception as exc:
            write_new(self.directory / ('receipt-' + prefix + '.json'), {'status': 'unknown_outcome', 'error_type': type(exc).__name__})
            write_new(self.directory / ('ledger-' + prefix + '.json'), self.ledger.snapshot())
            raise
        receipt = asdict(response)
        if len(canonical_json(receipt).encode('utf-8')) > 65536 or receipt_reflects_secret(receipt, key):
            receipt = {'status': 'withheld', 'reason': 'oversize_or_credential_reflection',
                       **{name: value if type(value) is int and 0 <= value <= intent['reservation'] else None
                          for name, value in ((name, getattr(response, name)) for name in
                                              ('prompt_tokens', 'completion_tokens', 'total_tokens'))}}
        self.ledger.settle(intent, response)
        write_new(self.directory / ('receipt-' + prefix + '.json'), receipt)
        write_new(self.directory / ('ledger-' + prefix + '.json'), self.ledger.snapshot())
        return response


def assess(case, report):
    facts = {fact['name'] for fact in report['facts']}
    hypotheses = {item['id']: item for item in report['hypotheses']}
    calls = [event for event in report['trace'] if event['event'] == 'tool_finished']
    tool_order = [event['tool'] for event in calls]
    financial = next((event for event in calls if event['tool'] == 'financial'), None)
    starts = {event['tool_call_id']: event['turn'] for event in report['trace'] if event['event'] == 'tool_started'}
    financial_turn = starts.get(financial.get('tool_call_id')) if financial else None
    expected_checks = bound_required_checks(DynamicRequest.from_dict({**case['request'], 'question': case['research_question']}))
    replan = (financial is not None and 'market' in tool_order and 'financial' in tool_order
              and tool_order.index('financial') < tool_order.index('market')
              and financial_turn is not None
              and any(plan['turn'] > financial_turn and plan['steps'] != report['plans'][0]['steps']
                      for plan in report['plans']))
    checks = {'multi_step_loop': report['usage']['model_attempts'] >= 2 and report['usage']['tool_calls'] >= 2,
              'independent_claim_verification': report['verification']['status'] == 'verified',
              'required_checks_retained': [item['id'] for item in report['required_checks']] == expected_checks,
              'mandatory_facts_present': set(case['expected_behavior']['mandatory_fact_names']) <= facts,
              'decisions_within_limit': report['usage']['model_attempts'] <= SPEC.max_decisions,
              'provider_network_calls_zero': report['usage']['financial_provider_network_calls'] == 0}
    hypothesis = hypotheses.get('financial_deterioration', {})
    if case['stratum'] == 'complete-financial':
        checks.update(completed=report['status'] == 'completed', decisive_financial_result=hypothesis.get('status') in {'supported', 'unsupported', 'conflicted'},
                      required_checks_passed=all(item['status'] == 'passed' for item in report['required_checks']))
    else:
        checks.update(insufficient=report['status'] == 'insufficient', missing_prior_preserved=hypothesis.get('status') == 'insufficient',
                      no_invented_yoy=not {'revenue_yoy', 'net_income_parent_yoy'} & facts,
                      all_required_execution_completed=all(item['status'] == 'passed' for item in report['required_checks']
                                                           if not item['id'].startswith('hypothesis:')),
                      missing_prior_gaps_preserved={'revenue:yoy_prior_year_period_not_visible',
                                                   'net_income_parent:yoy_prior_year_period_not_visible'} <= set(report['gaps']))
        if case['stratum'] == 'replan-missing-prior':
            checks['observation_driven_plan_adjustment'] = replan
    return {'task_id': case['id'], 'checks': checks, 'functional_passed': all(checks.values()),
            'status': report['status'], 'stop_reason': report['stop_reason'], 'usage': report['usage'],
            'quality_scope': 'Functional demonstration only; no broad quality or causal certification.'}


def live(output=OUT, expected_sha=None):
    output = Path(output)
    proposal, sources = checked_proposal(output, expected_sha)
    directory = output / 'live'
    directory.mkdir(exist_ok=False)
    config = load_model_config()
    if config.model != SPEC.model:
        raise IntegrityError('configured model differs from frozen M1 model')
    ledger, results = RootLedger(), []
    deadline = utcnow() + timedelta(seconds=3 * SPEC.max_seconds)
    for case, item in zip(proposal['tasks'], proposal['previews']):
        service, access = sources.context(case)
        request = DynamicRequest.from_dict(item['request'])
        model = RecordingModel(ChatModelAdapter(config), item, ledger, directory, deadline)
        report = DynamicRuntime(service, CheckpointStore(directory / 'runs'), model, SPEC).run(request, access)
        write_new(directory / (case['id'] + '.json'), report)
        with (directory / (case['id'] + '.md')).open('x', encoding='utf-8') as stream:
            stream.write(markdown(report))
        results.append(assess(case, report))
    summary = {'schema': 'phase4-m1-live-demonstrations/v1', 'proposal_sha256': sha(output / 'proposal.json'),
               'tasks': results, 'functional_passed': all(result['functional_passed'] for result in results),
               'ledger': ledger.snapshot(), 'provider_network_calls': 0, 'model': config.model,
               'root_deadline': deadline.isoformat(),
               'unknown_results_automatically_replayed': False}
    write_new(directory / 'summary.json', summary)
    return summary


def replay(output=OUT, expected_sha=None):
    output = Path(output)
    proposal, sources = checked_proposal(output, expected_sha)
    results = []
    class NoNetworkModel:
        class config:
            model = SPEC.model
        def complete(self, *args, **kwargs):
            raise AssertionError('replay attempted a paid model call')
    for case, item in zip(proposal['tasks'], proposal['previews']):
        report_path = output / 'live' / (case['id'] + '.json')
        if not report_path.exists():
            continue
        saved = read(report_path)
        service, access = sources.context(case)
        replayed = DynamicRuntime(service, CheckpointStore(output / 'live/runs'), NoNetworkModel(), SPEC).run(
            DynamicRequest.from_dict(item['request']), access, resume=saved['run_id'])
        if replayed != saved:
            raise IntegrityError('M1 completed/stopped replay report differs')
        results.append(assess(case, replayed))
    return {'proposal_sha256': sha(output / 'proposal.json'), 'source_contracts_valid': True,
            'replayed_tasks': len(results), 'tasks': results, 'model_calls': 0, 'provider_network_calls': 0,
            'phase': 'prepared_not_executed' if not results else 'authorized_reports_replayed'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Three existing-source M1 demonstrations; default is offline preparation')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--live', action='store_true', help='execute the current-session authorized bounded model demonstrations')
    mode.add_argument('--replay', action='store_true', help='reauthorize sources and replay retained runs without network')
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--authorized-sha', help='optional integrity binding to the reviewed proposal SHA-256')
    args = parser.parse_args(argv)
    try:
        result = live(args.output, args.authorized_sha) if args.live else (
            replay(args.output, args.authorized_sha) if args.replay else prepare(args.output))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (DataError, OSError, ValueError, KeyError, TypeError):
        # Paths/adapter errors are not echoed; no credential or source-text reflection.
        print(json.dumps({'status': 'failed', 'error': 'M1 preparation/execution integrity or input check failed'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
