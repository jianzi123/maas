"""Bounded, opt-in smoke for the normal MySQL offline profile; never a real model."""
import argparse
import hashlib
import http.cookiejar
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--url', required=True)
    p.add_argument('--config', required=True)
    p.add_argument('--password-file', required=True)
    p.add_argument('--username', default='admin')
    p.add_argument('--approve-safe-tools', action='store_true')
    p.add_argument('--record')
    p.add_argument('--verify-record')
    args = p.parse_args()
    origin = args.url.rstrip('/')
    parsed = urllib.parse.urlparse(origin)
    if parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.path:
        raise SystemExit('Only an explicitly owned loopback candidate is supported.')
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    if not config.get('offline_controlled', {}).get('enabled'):
        raise SystemExit('Refusing non-controlled profile; no generation POST sent.')
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    csrf = ''

    def request(method, path, body=None, etag=None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        headers = {'Origin': origin, 'Content-Type': 'application/json'}
        if csrf:
            headers['X-CSRF-Token'] = csrf
        if etag:
            headers['If-Match'] = etag
        req = urllib.request.Request(origin + path, data=data, headers=headers, method=method)
        try:
            with client.open(req, timeout=15) as response:
                raw = response.read()
                return (json.loads(raw) if raw else None), response.headers
        except urllib.error.HTTPError as exc:
            # Do not echo auth responses/secrets. Never retry a write.
            raise RuntimeError(f'{method} {path}: HTTP {exc.code}; preserve original operation IDs') from None

    ready, _ = request('GET', '/readyz')
    if ready.get('profile') != 'offline-controlled' or ready.get('persistence') != 'mysql':
        raise SystemExit('Server is not the normal MySQL offline profile.')
    login, _ = request('POST', '/api/admin/v1/session', {
        'username': args.username,
        'password': Path(args.password_file).read_text(encoding='utf-8').strip(),
    })
    csrf = login['csrf_token']

    def events(base):
        result, after = [], None
        while True:
            query = '?page_size=100' + ('&after=' + urllib.parse.quote(after) if after else '')
            page, _ = request('GET', base + '/events' + query)
            result.extend(page['data'])
            after = page['next_cursor']
            if after is None:
                return result

    def event_hash(items):
        return hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    if args.verify_record:
        record = json.loads(Path(args.verify_record).read_text(encoding='utf-8'))
        base = '/api/agent/v1/sessions/' + record['session_id'] + '/runs/' + record['run_id']
        current, _ = request('GET', base)
        assert current['child_request_ids'] == record['child_request_ids']
        assert current['state'] == record['state']
        assert event_hash(events(base)) == record['events_sha256']
        print(json.dumps({'profile': 'offline-controlled', 'restart_readonly_verified': True,
                          'new_run_posts': 0, 'run_id': record['run_id']}, ensure_ascii=False))
        return

    if not args.approve_safe_tools:
        raise SystemExit('Pass --approve-safe-tools explicitly to approve only the two builtin pure/read tools.')
    operation = str(uuid.uuid4())
    session, headers = request('POST', '/api/agent/v1/sessions', {
        'client_operation_id': operation, 'title': '离线MySQL演示', 'model_alias': 'offline-controlled',
    })
    sid = session['id']
    limits = config['agent']['limits']
    run, _ = request('POST', '/api/agent/v1/sessions/' + sid + '/runs', {
        'client_operation_id': str(uuid.uuid4()), 'mode': 'agent', 'operation': 'send',
        'text': '计算6乘7，读取当前可见模型并汇总结果', 'referenced_message_id': None,
        'model_alias': 'offline-controlled', 'limits': limits,
        'tools': [{'name': 'bounded_arithmetic', 'revision': '1'}, {'name': 'list_visible_models', 'revision': '1'}],
    }, headers['ETag'])
    rid = run['run']['id']
    base = '/api/agent/v1/sessions/' + sid + '/runs/' + rid
    deadline = time.monotonic() + 90
    decisions = set()
    while time.monotonic() < deadline:
        current, _ = request('GET', base)
        if current['state'] == 'waiting_approval':
            for event in events(base):
                if event['type'] != 'approval.required':
                    continue
                approval = event['data']
                if approval['id'] in decisions:
                    continue
                if approval['tool_name'] not in ('bounded_arithmetic', 'list_visible_models'):
                    raise RuntimeError('Refusing approval of any extension tool')
                request('POST', base + '/approvals/' + approval['id'] + '/decision', {
                    'decision_id': str(uuid.uuid4()), 'decision': 'allow',
                    'args_sha256': approval['args_sha256'], 'tool_revision': approval['tool_revision'],
                    'policy_revision': approval['policy_revision'],
                })
                decisions.add(approval['id'])
        if current['state'] == 'completed':
            assert len(current['child_request_ids']) == 2
            first = events(base)
            assert first == events(base)
            record = {'session_id': sid, 'run_id': rid, 'state': current['state'],
                      'child_request_ids': current['child_request_ids'], 'events_sha256': event_hash(first),
                      'profile': 'offline-controlled', 'usage_groups': current['usage_groups']}
            if args.record:
                Path(args.record).write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps(record, ensure_ascii=False))
            return
        if current['state'] in ('failed', 'cancelled', 'limit_reached', 'needs_confirmation'):
            raise RuntimeError(f'Run {rid} ended {current["state"]}: {current["reason"]}')
        time.sleep(0.1)
    raise RuntimeError(f'Bounded wait expired; inspect original Run {rid}; do not repeat POST')


if __name__ == '__main__':
    main()
