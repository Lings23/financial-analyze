"""Independent, non-scoring full-text inventory for the preregistered v2 Judge.

No production calculation or renderer is imported. Mechanical JSON/Markdown
consistency is not source truth and never automatically yields semantic pass.
Every line remains available for a human Codex Judge to read in full.
"""
import argparse
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import html
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
HEX_REF = re.compile(r'`([0-9a-f]{64})`')
NUMBER = re.compile(r'(?<![\w])[-+]?\d[\d,]*(?:\.\d+)?(?:%)?')
CAUSAL = re.compile(r'导致|造成|推动|驱动|归因|因为|因此|引发|因果|事件影响|解释了')
GENERAL = re.compile(r'全市场|全部|所有|完整窗口|总体|必然|始终|普遍|总收益|认证')
CERTAINTY = re.compile(r'证明|确认|确定|必定|一定|显然|无疑|已完成|检验已完成')
INSUFF = re.compile(r'insufficient|证据不足|证据不全|缺失|缺口|无法|未观察|未满足')
UNKNOWN_NEGATION = re.compile(r'不是|不构成|不认证|未建立|尚未|无法|没有|未证明|不能|不证明|非因果|未认证')


def _hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _value_representations(fact):
    """Only an independent display-consistency transform, not financial truth."""
    value = Decimal(str(fact['value']))
    with localcontext() as context:
        context.prec = max(40, len(value.as_tuple().digits) + abs(value.adjusted()) + 12)
        context.rounding = ROUND_HALF_UP
        if fact['unit'] == 'ratio':
            return [f'{value * 100:.2f}%']
        if fact['unit'] == 'CNY':
            divisor, label = ((Decimal('100000000'), '亿元') if abs(value) >= Decimal('100000000')
                else (Decimal('10000'), '万元') if abs(value) >= Decimal('10000') else (Decimal('1'), '元'))
            return [f'{value / divisor:,.2f} {label}']
    return [str(fact['value']) + ' ' + str(fact['unit'])]


def _all_ids(report):
    values = set()
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(key, str) and re.fullmatch(r'[0-9a-f]{64}', key):
                    values.add(key)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value):
            values.add(value)
    visit(report)
    return values


def audit_markdown(report, markdown, *, case_id=None):
    known_ids = _all_ids(report)
    facts = {item['id']: item for item in report.get('facts', [])}
    lines = []
    flags = []
    section = None
    for number, raw in enumerate(markdown.splitlines(), 1):
        if raw.startswith('#'):
            section = raw.lstrip('#').strip()
        refs = HEX_REF.findall(raw)
        without_ids = HEX_REF.sub('', raw)
        numeric = NUMBER.findall(without_ids)
        triggers = []
        for name, expression in [('causal_language', CAUSAL), ('scope_or_generalization', GENERAL),
                                 ('certainty', CERTAINTY), ('insufficiency', INSUFF)]:
            if expression.search(raw):
                triggers.append(name)
        consistency = []
        # References adjacent to a shown Claim must be evaluated independently
        # against the source oracle later; this checks only displayed values.
        if numeric and section in {'概览', '可核查数值', '模型重点选择', '系统核对重点'}:
            for fid in refs:
                if fid in facts:
                    expected = _value_representations(facts[fid])
                    consistency.append({'claim_id': fid, 'expected_representations': expected,
                        'representation_found': any(item in html.unescape(raw) for item in expected),
                        'is_source_verification': False})
        unknown_refs = [ref for ref in refs if ref not in known_ids]
        if unknown_refs:
            triggers.append('unregistered_reference')
        if numeric and not refs and section not in {'执行账本', '请求与冻结快照'}:
            triggers.append('number_without_inline_hash_reference')
        if triggers or any(not item['representation_found'] for item in consistency):
            flags.append({'line': number, 'section': section, 'triggers': triggers,
                'explicit_negation_or_limitation': bool(UNKNOWN_NEGATION.search(raw)),
                'unknown_refs': unknown_refs, 'display_consistency': consistency,
                'semantic_verdict': 'pending_independent_full_text_review'})
        lines.append({'line': number, 'section': section, 'text': raw,
            'hash_references': refs, 'numeric_tokens': numeric,
            'display_consistency': consistency, 'manual_read': False})
    return {'case_id': case_id, 'markdown_sha256': _hash_bytes(markdown.encode('utf8')),
        'line_count': len(lines), 'all_lines_included': True, 'full_text_read': False,
        'semantic_pass': None, 'task_completion_supported': None,
        'mechanical_flags_are_not_failures_or_passes': True,
        'known_json_ids': sorted(known_ids), 'potential_additional_claims_or_language_issues': flags,
        'lines': lines}


def audit_campaign(manifest_path, results_path, output_path, *, repository_root=ROOT):
    root = Path(repository_root).resolve()
    manifest_bytes, result_bytes = Path(manifest_path).read_bytes(), Path(results_path).read_bytes()
    manifest, results = json.loads(manifest_bytes), json.loads(result_bytes)
    if results['manifest_sha256'] != _hash_bytes(manifest_bytes):
        raise ValueError('Agent results belong to another frozen manifest')
    cases = {case['id']: case for case in manifest['cases']}
    actual = {case['case_id']: case for case in results['cases']}
    if len(actual) != len(results['cases']) or set(cases) != set(actual):
        raise ValueError('All formal cases must be retained')
    inventories = []
    for case in manifest['cases']:
        result = actual[case['id']]
        report_path = (root / result['report_path']).resolve()
        md_path = (root / result['markdown_path']).resolve()
        if not report_path.is_relative_to(root) or not md_path.is_relative_to(root):
            raise ValueError('Report paths must remain inside the review root')
        report_bytes, md_bytes = report_path.read_bytes(), md_path.read_bytes()
        if (_hash_bytes(report_bytes) != result['report_sha256']
                or _hash_bytes(md_bytes) != result['markdown_sha256']):
            raise ValueError('Frozen report/Markdown bytes changed')
        report = json.loads(report_bytes)
        if report != result['output'] or report['request'] != case['request']:
            raise ValueError('Report payload or original request differs')
        inventory = audit_markdown(report, md_bytes.decode('utf8'), case_id=case['id'])
        inventory.update(research_question=case['research_question'],
            expected_behavior=case['expected_behavior'], success_criteria=case['success_criteria'],
            report_path=result['report_path'], report_sha256=result['report_sha256'],
            markdown_path=result['markdown_path'], markdown_sha256=result['markdown_sha256'])
        inventories.append(inventory)
    output = {'schema': 'phase3-v2-markdown-inventory/v1',
        'manifest_sha256': _hash_bytes(manifest_bytes), 'agent_results_sha256': _hash_bytes(result_bytes),
        'task_count': len(inventories), 'semantic_judge_completed': False,
        'mechanical_audit_does_not_set_task_success': True, 'tasks': inventories}
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf8') as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--results', required=True)
    parser.add_argument('--output', required=True)
    arguments = parser.parse_args()
    result = audit_campaign(arguments.manifest, arguments.results, arguments.output)
    print(json.dumps({'task_count': result['task_count'], 'semantic_judge_completed': False}))
