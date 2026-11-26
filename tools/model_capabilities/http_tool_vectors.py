"""Local-only HTTP/SSE replay of MAAS-9 vectors; not a production ModelClient."""
import argparse
import copy
import hashlib
import http.client
import importlib.util
import json
from pathlib import Path
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('maas9_tool_oracle', ROOT / 'tool_calls.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


class TransportFailure(ValueError):
    pass


def post_capture(port, path, body, *, limit=65536, total=3.0, idle=1.0, cancel_after=None):
    """No URL argument, proxies, redirects, credentials, retries, or provider access."""
    raw = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    start = time.monotonic()
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=min(total, idle))
    result = bytearray()
    try:
        conn.request('POST', path, body=raw, headers={'Content-Type': 'application/json', 'Connection': 'close'})
        response = conn.getresponse()
        if response.status != 200:
            raise TransportFailure('http_' + str(response.status))
        if response.getheader('Content-Type', '').split(';')[0].strip() != 'text/event-stream':
            raise TransportFailure('content_type')
        while True:
            if cancel_after is not None and len(result) >= cancel_after:
                raise TransportFailure('cancelled_transport_closed')
            if time.monotonic() - start >= total:
                raise TransportFailure('total_deadline')
            try:
                fragment = response.read(1)
            except (TimeoutError, socket.timeout) as exc:
                reason = 'total_deadline' if time.monotonic() - start >= total else 'idle_timeout'
                raise TransportFailure(reason) from exc
            if not fragment:
                break
            result.extend(fragment)
            if len(result) > limit:
                raise TransportFailure('body_limit')
        return bytes(result)
    finally:
        conn.close()


class FixtureServer:
    def __init__(self):
        self.routes = {}
        self.observations = []
        self.stop = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'

            def log_message(self, *_):
                pass

            def do_POST(self):
                route = owner.routes.get(self.path)
                size = int(self.headers.get('Content-Length', '0'))
                if route is None or not 0 < size <= 65536 or self.headers.get('Authorization'):
                    self.send_error(400)
                    return
                raw = self.rfile.read(size)
                try:
                    request = oracle.strict_json(raw)
                except ValueError:
                    self.send_error(400)
                    return
                owner.observations.append({'path': self.path, 'body_sha256': hashlib.sha256(raw).hexdigest(), 'request': request})
                if 'expected_request' in route and request != route['expected_request']:
                    self.send_error(409)
                    return
                self.send_response(route.get('status', 200))
                self.send_header('Content-Type', route.get('content_type', 'text/event-stream'))
                if route.get('status') == 302:
                    self.send_header('Location', '/redirect-trap')
                self.end_headers()
                try:
                    if route.get('mode') == 'idle':
                        owner.stop.wait(0.4)
                        return
                    if route.get('mode') == 'heartbeats':
                        for _ in range(100):
                            self.wfile.write(b': controlled heartbeat\n\n')
                            self.wfile.flush()
                            if owner.stop.wait(0.005):
                                break
                        return
                    raw = route.get('wire', '').encode('utf-8')
                    offset = 0
                    widths = (1, 5, 2, 13)
                    index = 0
                    while offset < len(raw) and not owner.stop.is_set():
                        width = widths[index % len(widths)]
                        self.wfile.write(raw[offset:offset + width])
                        self.wfile.flush()
                        offset += width
                        index += 1
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    # Client transport close is not a provider execution-stop receipt.
                    pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = False
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.02})

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    @property
    def port(self):
        return self.server.server_port


def replay_over_http(case, server):
    profile = oracle.load(oracle.DATA / 'capability.json')['controlled_profile']
    before = len(server.observations)

    def read(turn, position, messages):
        path = '/controlled/' + case['id'] + '/' + str(position + 1)
        request = {'model': profile['model'], 'messages': messages, 'stream': True, 'max_tokens': 32,
                   'tools': [{'type': 'function', 'function': {'name': tool['name'], 'parameters': tool['parameters']}} for tool in profile['tools']],
                   'thinking': {'type': 'disabled'}, 'stream_options': {'include_usage': True},
                   '_controlled_binding': turn['binding']}
        # The binding is fixture-only, NOT an upstream parameter suggestion.
        server.routes[path] = {'wire': turn['response']['wire'], 'expected_request': request}
        raw = post_capture(server.port, path, request)
        observed = copy.deepcopy(turn)
        observed['response']['wire'] = raw.decode('utf-8', errors='strict')
        return observed

    out = oracle.replay(case, turn_reader=read)
    observations = copy.deepcopy(server.observations[before:])
    expected = case['expected']
    passed = (out['status'] == expected['status'] and len(out['tool_executions']) == expected['tool_executions']
              and len(observations) == expected['fixture_model_turns_read']
              and ('reason' not in expected or out.get('reason') == expected['reason']))
    return {'id': case['id'], 'passed': passed, 'result': out, 'HTTP_requests': observations,
            'timing_scope': 'original fixture end/cancel/deadline labels; actual transport controls tested separately'}


def transport_checks(server):
    cases = [
        ('HTTP429', {'status': 429}, {}, 'http_429'),
        ('redirect_not_followed', {'status': 302}, {}, 'http_302'),
        ('content_type', {'content_type': 'application/json', 'wire': '{}'}, {}, 'content_type'),
        ('body_limit', {'wire': 'x' * 128}, {'limit': 64}, 'body_limit'),
        ('client_cancel', {'wire': 'data: ' + 'x' * 256 + '\n\n'}, {'cancel_after': 16}, 'cancelled_transport_closed'),
        ('absolute_deadline_heartbeats', {'mode': 'heartbeats'}, {'total': 0.08, 'idle': 0.2}, 'total_deadline'),
        ('idle_timeout', {'mode': 'idle'}, {'idle': 0.08, 'total': 1.0}, 'idle_timeout'),
    ]
    rows = []
    for name, route, limits, expected in cases:
        server.routes['/transport/' + name] = route
        start = time.monotonic()
        try:
            post_capture(server.port, '/transport/' + name, {'controlled': True}, **limits)
            actual = 'accepted'
        except TransportFailure as exc:
            actual = str(exc)
        rows.append({'id': name, 'passed': actual == expected, 'actual': actual, 'expected': expected,
                     'elapsed_ms': round((time.monotonic() - start) * 1000, 3), 'scope': 'real_local_HTTP_transport_only'})
    rows.append({'id': 'no_redirect_trap_request', 'passed': not any(x['path'] == '/redirect-trap' for x in server.observations), 'scope': 'zero_redirect_retries'})
    return rows


def provider_messages(messages, call_records, binding):
    """Controlled serialization oracle for existing AR-1 internal -> source IDs."""
    record_map = {}
    source_ids = set()
    for record in call_records:
        internal, source = record['id'], record['source_call_id']
        oracle.require(internal and source and internal not in record_map and source not in source_ids, 'ambiguous_call_mapping')
        oracle.require(all(record[k] == binding[k] for k in ['source_id', 'profile_revision']), 'foreign_source_mapping')
        record_map[internal] = record
        source_ids.add(source)
    output, pending, used = [], set(), set()
    for message in messages:
        role = message['role']
        if role == 'assistant':
            oracle.require(not pending, 'unresolved_tool_batch')
            calls, text = [], ''
            for part in message['parts']:
                if part['type'] == 'text':
                    text += part['text']
                elif part['type'] == 'tool_call':
                    record = record_map[part['call_id']]
                    oracle.require(record['name'] == part['name'] and record['run_id'] == message['run_id'] and record['arguments'] == part['arguments'], 'tool_name_or_argument_mapping')
                    oracle.require(record['source_call_id'] not in used, 'reused_source_call')
                    used.add(record['source_call_id'])
                    calls.append({'id': record['source_call_id'], 'type': 'function', 'function': {'name': part['name'], 'arguments': json.dumps(part['arguments'], separators=(',', ':'), sort_keys=True)}})
                    pending.add(record['source_call_id'])
                else:
                    raise oracle.Rejected('unsupported_part')
            row = {'role': role, 'content': text or None}
            if calls:
                row['tool_calls'] = calls
            output.append(row)
        elif role == 'tool':
            oracle.require(len(message['parts']) == 1, 'one_result_part')
            part = message['parts'][0]
            record = record_map[part['call_id']]
            source = record['source_call_id']
            oracle.require(part['type'] == 'tool_result' and record['state'] == 'completed' and source in pending and record['name'] == part['name'], 'unmatched_tool_result')
            oracle.require(record['run_id'] == message['run_id'] and record['result'] == part['text'], 'foreign_or_changed_result')
            pending.remove(source)
            output.append({'role': 'tool', 'tool_call_id': source, 'content': part['text']})
        elif role in {'user', 'system'}:
            oracle.require(not pending and all(p['type'] == 'text' for p in message['parts']), 'unsupported_history')
            output.append({'role': role, 'content': ''.join(p['text'] for p in message['parts'])})
        else:
            raise oracle.Rejected('unsupported_role')
    oracle.require(not pending, 'missing_tool_result')
    return output


def evaluate():
    with FixtureServer() as server:
        rows = [replay_over_http(case, server) for case in oracle.load(oracle.DATA / 'vectors.json')['cases']]
        controls = transport_checks(server)
        requests = len(server.observations)
    passed = sum(r['passed'] for r in rows + controls)
    return {'version': '0.9', 'summary': {'total': len(rows) + len(controls), 'passed': passed, 'failed': len(rows) + len(controls) - passed},
            'vectors': rows, 'transport_controls': controls, 'HTTP_requests_total': requests, 'real_supplier_calls': 0,
            'formal_ModelClient_accepted_tools': False, 'synthetic_gateway_or_ledger_claim': False,
            'not_executed': ['production tools-v1 bridge/approval', 'Higress/mTLS/Go Admit-Finalize over this fixture', 'MySQL writes or model quality', 'provider model/account/Secret access']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = evaluate()
    if args.output:
        oracle.require(args.output.resolve() not in {p.resolve() for p in ROOT.rglob('*') if p.is_file()}, 'input_overwrite')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
    print(json.dumps(report['summary']))
    return 1 if report['summary']['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
