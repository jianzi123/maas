"""Offline MAAS-20 tool-call contract oracle. No HTTP, credential, or ledger client."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'tool-calls'
spec = importlib.util.spec_from_file_location('maas9_text_usage', ROOT / 'deepseek_milestone.py')
text_usage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(text_usage)


class Rejected(ValueError):
    pass


def require(test, reason):
    if not test:
        raise Rejected(reason)


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def strict_json(text):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, 'duplicate_json_key')
            out[key] = value
        return out
    def constant(_):
        raise Rejected('non_finite_json')
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError) as exc:
        raise Rejected('invalid_json') from exc


def registry():
    return {tool['name']: tool for tool in load(DATA / 'capability.json')['controlled_profile']['tools']}


def inspect_turn(turn, profile, widths=(1, 7, 3)):
    """Assemble one original source capture; never run tools during deltas."""
    binding, response = turn['binding'], turn['response']
    require(binding['mode'] == 'non-thinking', 'mode')
    require(binding['profile_revision'] == profile['revision'], 'profile_binding')
    require(binding['model'] == profile['model'], 'model_binding')
    require(binding['model_revision'] == profile['model_revision'] and binding['source_id'] == profile['source_id'], 'controlled_source_revision')
    require(response['content_type'] == 'text/event-stream', 'content_type')
    wire = response['wire']
    require(len(wire.encode('utf-8')) <= profile['test_limits']['wire_bytes'], 'wire_limit')
    calls, content, finish, usage = {}, '', None, None
    done, role_seen, metadata = False, False, None
    for event, data in text_usage.kv.sse_events(wire.encode('utf-8'), widths):
        require(not done, 'after_DONE')
        if data == '[DONE]':
            require(event == 'message' and finish is not None, 'DONE_order')
            done = True
            continue
        chunk = strict_json(data)
        require(event == 'message' and isinstance(chunk, dict) and 'error' not in chunk, 'source_error')
        require(finish is None, 'data_after_finish')
        require(chunk.get('object') == 'chat.completion.chunk', 'source_object')
        require(chunk.get('id') == binding['upstream_response_id'] and chunk.get('model') == binding['model'], 'source_identity')
        require(type(chunk.get('created')) is int and type(chunk.get('system_fingerprint')) is str, 'source_metadata')
        identity = (chunk['created'], chunk['system_fingerprint'])
        require(metadata is None or identity == metadata, 'metadata_drift')
        metadata = identity
        choices = chunk.get('choices')
        require(isinstance(choices, list) and len(choices) == 1, 'single_choice')
        choice = choices[0]
        require(type(choice.get('index')) is int and choice['index'] == 0, 'choice_index')
        delta = choice.get('delta')
        require(isinstance(delta, dict) and set(delta) <= {'role', 'content', 'tool_calls'}, 'undeclared_delta')
        if 'role' in delta:
            require(delta['role'] == 'assistant' and not role_seen, 'assistant_role')
            role_seen = True
        require(role_seen, 'missing_role')
        part = delta.get('content')
        require(part is None or isinstance(part, str), 'text_type')
        content += part or ''
        require(len(content.encode('utf-8')) <= profile['test_limits']['output_bytes'], 'content_limit')
        fragments = delta.get('tool_calls', [])
        require(isinstance(fragments, list), 'tool_array')
        for fragment in fragments:
            index = fragment.get('index')
            require(type(index) is int and 0 <= index < profile['test_limits']['calls_per_turn'], 'call_index')
            function = fragment.get('function')
            require(isinstance(function, dict), 'function_shape')
            if index not in calls:
                require(set(fragment) == {'index', 'id', 'type', 'function'}, 'first_call_metadata')
                require(fragment['type'] == 'function' and isinstance(fragment['id'], str) and 0 < len(fragment['id']) <= 128, 'call_identity')
                require(set(function) <= {'name', 'arguments'} and isinstance(function.get('name'), str) and function['name'], 'first_function')
                require(fragment['id'] not in {c['id'] for c in calls.values()}, 'duplicate_call_id')
                calls[index] = {'id': fragment['id'], 'type': 'function', 'function': {'name': function['name'], 'arguments': ''}}
            else:
                require(set(fragment) == {'index', 'function'} and set(function) == {'arguments'}, 'call_metadata_repeated_or_changed')
            arguments = function.get('arguments', '')
            require(isinstance(arguments, str), 'argument_fragment_type')
            calls[index]['function']['arguments'] += arguments
            require(len(calls[index]['function']['arguments'].encode('utf-8')) <= profile['test_limits']['arguments_bytes'], 'arguments_limit')
        finish = choice.get('finish_reason')
        raw_usage = chunk.get('usage')
        if finish is None:
            require(raw_usage is None, 'progress_is_not_final')
        else:
            require(not part and not fragments, 'finish_contains_new_data')
            if raw_usage is not None:
                usage = text_usage.normalized(raw_usage)
    timing = response['fixture_timing_ms']
    require(all(type(timing[k]) is int and timing[k] >= 0 for k in ['end', 'hard_deadline']), 'fixture_time')
    if not done or response['transport_end'] != 'clean' or timing['end'] > timing['hard_deadline']:
        return {'status': 'interrupted', 'message': None, 'usage_snapshot': None, 'finish_reason': finish}
    require(finish in {'stop', 'tool_calls', 'length', 'content_filter', 'insufficient_system_resource', 'aborted'}, 'finish_reason')
    ordered = [calls[i] for i in sorted(calls)]
    require(sorted(calls) == list(range(len(calls))), 'sparse_indexes')
    if finish == 'tool_calls':
        require(ordered, 'missing_tool_calls')
    elif finish == 'stop':
        require(not ordered, 'stop_with_calls')
    message = {'role': 'assistant', 'content': content or None}
    if ordered:
        message['tool_calls'] = ordered
    normalized = {'contract_version': 'maas.model-tool-turn/0.1-draft', 'model_client_protocol': 'tools-v1', 'binding': binding, 'finish_reason': finish,
                  'message': message, 'usage_snapshot': usage, 'termination': 'controlled_clean_DONE', 'accounting_authority': False}
    Draft202012Validator(load(DATA / 'turn.schema.json')).validate(normalized)
    return {'status': 'truncated' if finish == 'length' else 'model_failed' if finish not in {'stop', 'tool_calls'} else 'ready', **normalized}


def validate_batch(message, profile, allowed):
    definitions = registry()
    prepared = []
    for call in message.get('tool_calls', []):
        name = call['function']['name']
        require(name in definitions, 'unknown_tool')
        require(name in allowed, 'tool_not_authorized')
        definition = definitions[name]
        require(definition['effect'] == 'pure' and definition['approval'] == 'controlled_fixture_only', 'tool_policy')
        arguments = strict_json(call['function']['arguments'])
        require(isinstance(arguments, dict), 'arguments_object')
        require(Draft202012Validator(definition['parameters']).is_valid(arguments), 'arguments_schema')
        prepared.append((call, arguments))
    require(len(prepared) <= profile['test_limits']['calls_per_turn'], 'calls_limit')
    return prepared


def execute_pure(name, arguments):
    if name == 'sum_ints':
        return {'sum': arguments['a'] + arguments['b']}
    if name == 'echo_text':
        return {'text': arguments['text']}
    raise Rejected('unknown_tool')


def validate_feedback(message, feedback):
    calls = message.get('tool_calls', [])
    require(len(feedback) == len(calls), 'missing_result')
    expected = [c['id'] for c in calls]
    seen = []
    for result in feedback:
        require(set(result) == {'role', 'tool_call_id', 'content'} and result['role'] == 'tool', 'result_role')
        require(result['tool_call_id'] in expected and result['tool_call_id'] not in seen, 'result_binding')
        require(isinstance(result['content'], str), 'result_content')
        seen.append(result['tool_call_id'])
    require(seen == expected, 'deterministic_result_order')


def replay(case, widths=(1, 7, 3), turn_reader=None):
    profile = load(DATA / 'capability.json')['controlled_profile']
    out = {'id': case['id'], 'status': 'rejected', 'fixture_model_turns_read': 0, 'tool_executions': [], 'model_usage_snapshots': [],
           'transcript': copy.deepcopy(case['messages']), 'supplier_calls': 0, 'ledger_write_authority': False, 'model_support_verified': False}
    try:
        require(case['synthetic'] is True and case['actual_provider_run'] is False, 'controlled_only')
        require(case.get('model_client_protocol') == 'tools-v1', 'explicit_tools_protocol_required')
        if case['capability'] != profile['id']:
            out['status'] = 'capability_unsupported'
            return out
        require(case['execution'] == 'serial', 'parallel_execution_not_approved')
        require(all(m.get('role') in {'system', 'user'} and set(m) == {'role', 'content'} and isinstance(m['content'], str) for m in case['messages']), 'untrusted_history')
        require(0 < len(case['turns']) <= profile['test_limits']['model_turns'], 'step_limit')
        session = None
        request_ids = set()
        turn_count = len(case['turns'])
        for pos, turn in enumerate(case['turns']):
            if case.get('cancel_before_step') == pos + 1:
                out['status'] = 'interrupted'
                return out
            binding = turn['binding']
            scope = (binding['session_id'], binding['run_id'], binding['source_id'], binding['profile_revision'], binding['model_revision'], binding['mode'])
            require(session is None or session == scope, 'run_binding_drift')
            session = scope
            require(binding['child_request_id'] not in request_ids, 'duplicate_child_request')
            require(binding['step_id'] == f'step-{pos + 1}', 'step_order')
            request_ids.add(binding['child_request_id'])
            out['fixture_model_turns_read'] += 1
            observed = turn_reader(turn, pos, copy.deepcopy(out['transcript'])) if turn_reader else turn
            result = inspect_turn(observed, profile, widths)
            out['model_usage_snapshots'].append({'child_request_id': binding['child_request_id'], 'usage': result['usage_snapshot'], 'authority': False})
            if result['status'] != 'ready':
                out['status'] = result['status']
                return out
            message = result['message']
            out['transcript'].append(message)
            if result['finish_reason'] == 'stop':
                require(pos + 1 == turn_count, 'extra_model_turn')
                out['status'] = 'completed'
                return out
            prepared = validate_batch(message, profile, case['allowed_tools'])
            require(pos + 1 < turn_count, 'missing_followup_turn')
            generated = []
            for call, arguments in prepared:
                value = execute_pure(call['function']['name'], arguments)
                content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
                require(len(content.encode('utf-8')) <= profile['test_limits']['output_bytes'], 'tool_output_limit')
                identity = [binding[k] for k in ['run_id', 'step_id', 'child_request_id']] + [call['id']]
                out['tool_executions'].append({'identity': identity, 'tool': call['function']['name'], 'arguments_sha256': hashlib.sha256(call['function']['arguments'].encode('utf-8')).hexdigest(), 'result': value})
                generated.append({'role': 'tool', 'tool_call_id': call['id'], 'content': content})
            feedback = case.get('feedback_override', generated) if pos == 0 else generated
            validate_feedback(message, feedback)
            require(feedback == generated, 'untrusted_result_content')
            out['transcript'].extend(feedback)
        raise Rejected('missing_final_answer')
    except Exception as exc:
        out['reason'] = str(exc) if isinstance(exc, Rejected) else type(exc).__name__
        return out


def evaluate(widths=(1, 7, 3)):
    checks, results = [], []
    def check(name, passed, scope):
        checks.append({'name': name, 'passed': bool(passed), 'scope': scope})
    for case in load(DATA / 'vectors.json')['cases']:
        result = replay(case, widths)
        results.append(result)
        expected = case['expected']
        check(case['id'], result['status'] == expected['status'] and len(result['tool_executions']) == expected['tool_executions']
              and result['fixture_model_turns_read'] == expected['fixture_model_turns_read']
              and ('reason' not in expected or result.get('reason') == expected['reason']), 'controlled_protocol_and_pure_tool_replay')
    api = load(ROOT / 'evidence/current-openapi.json')
    public = Draft202012Validator({'$ref': '#/components/schemas/ChatRequest', 'components': api['components']})
    normal = {'model': 'controlled-tool-model', 'messages': [{'role': 'user', 'content': '17+23'}], 'stream': True, 'max_tokens': 32}
    check('current_public_text_shape_valid', public.is_valid(normal), 'existing_schema_only_not_HTTP_attempt')
    for name, bad in [('tools', {**normal, 'tools': []}), ('tool_role', {**normal, 'messages': [{'role': 'tool', 'content': '{}', 'tool_call_id': 'call-a'}]}), ('assistant_calls', {**normal, 'messages': [{'role': 'assistant', 'content': None, 'tool_calls': []}]})]:
        check('current_public_rejects_' + name, not public.is_valid(bad), 'existing_schema_rejection_not_gateway_test')
    candidate = load(DATA / 'capability.json')['external_candidate']
    check('no_tool_approval_inherited', candidate['execution_enabled'] is False and candidate['approved_tool_profile'] is None
          and candidate['approved_public_agent_protocol'] is None, 'approval_boundary')
    return {'version': '0.8', 'summary': {'total': len(checks), 'passed': sum(x['passed'] for x in checks), 'failed': sum(not x['passed'] for x in checks)},
            'checks': checks, 'results': results, 'real_supplier_calls': 0, 'real_model_support_verified': False, 'shared_contract_status': 'proposal_pending_MAAS-2_and_MAAS-20',
            'not_executed': ['Go/Higress agent bridge or public HTTP rejection', 'provider account/model calls', 'SQL checkpoint/idempotency/cancel integration', 'real provider parallel calls or model quality']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--require-real-approval', action='store_true')
    args = parser.parse_args()
    try:
        report = evaluate()
        if args.require_real_approval or report['summary']['failed']:
            print('controlled checks failed or real tool capability remains unapproved', file=sys.stderr)
            return 2
        if args.output:
            require(args.output.resolve() not in {p.resolve() for p in ROOT.rglob('*') if p.is_file()}, 'input_overwrite')
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
        print(json.dumps(report['summary']))
        return 0
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
