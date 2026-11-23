"""Cancel one actually admitted child on an explicitly owned offline MySQL site."""
import argparse
import copy
import hashlib
import http.cookiejar
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--password-file', required=True, type=Path)
    parser.add_argument('--username', default='admin')
    parser.add_argument('--record', required=True, type=Path)
    args = parser.parse_args()
    origin = args.url.rstrip('/')
    parsed = urllib.parse.urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise SystemExit('Only an explicitly owned loopback origin is supported')
    if args.record.exists():
        raise SystemExit('Existing record: inspect its original IDs; never retry a write')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), NoRedirect())
    csrf = ''
    def request(method, path, body=None, etag=None):
        headers = {'Origin': origin, 'Content-Type': 'application/json'}
        if csrf:
            headers['X-CSRF-Token'] = csrf
        if etag:
            headers['If-Match'] = etag
        data = None if body is None else json.dumps(body).encode()
        with client.open(urllib.request.Request(origin + path, data=data, headers=headers, method=method), timeout=10) as response:
            raw = response.read()
            return (json.loads(raw) if raw else None), response.headers
    ready, _ = request('GET', '/readyz')
    if ready.get('profile') != 'offline-controlled' or ready.get('persistence') != 'mysql':
        raise SystemExit('Refusing non-controlled profile before login/generation')
    public, _ = request('GET', '/console-config.json')
    limits = copy.deepcopy(public['chat']['limits'])
    limits.update(max_model_calls=1, max_tool_calls=0)
    record = {'creationOperationId': str(uuid.uuid4()), 'runs': []}
    def save():
        args.record.parent.mkdir(parents=True, exist_ok=True)
        args.record.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    login, _ = request('POST', '/api/admin/v1/session', {'username': args.username, 'password': args.password_file.read_text().strip()})
    csrf = login['csrf_token']
    try:
        save()
        session, headers = request('POST', '/api/agent/v1/sessions', {'client_operation_id': record['creationOperationId'], 'title': 'Offline admitted cancellation', 'model_alias': 'offline-controlled'})
        sid = session['id']; record['sessionId'] = sid; save()
        record['pendingCommand'] = {'client_operation_id': str(uuid.uuid4())}; save()
        run, _ = request('POST', '/api/agent/v1/sessions/' + sid + '/runs', {'client_operation_id': record['pendingCommand']['client_operation_id'], 'mode': 'chat', 'operation': 'send', 'text': 'Controlled cancellation only', 'referenced_message_id': None, 'model_alias': 'offline-controlled', 'limits': limits, 'tools': []}, headers['ETag'])
        rid = run['run']['id']; record['pendingCommand']['run_id'] = rid; save()
        base = '/api/agent/v1/sessions/' + sid + '/runs/' + rid
        deadline = time.monotonic() + 20
        child = None
        while time.monotonic() < deadline:
            current, _ = request('GET', base)
            if current['state'] in ('completed', 'failed', 'cancelled', 'needs_confirmation', 'limit_reached'):
                raise RuntimeError('Run terminated before an admitted cancellation; inspect original IDs. Use an explicitly slower offline step_delay_ms (e.g. 5000), restart the owned app, then use a NEW record; never repeat this command.')
            for candidate in current['child_request_ids']:
                usage, _ = request('GET', '/api/admin/v1/usage/requests?request_id=' + urllib.parse.quote(candidate))
                if len(usage['data']) == 1 and usage['data'][0]['status'] == 'in_progress':
                    child = candidate
                    break
            if child:
                break
            time.sleep(.05)
        if child is None:
            raise RuntimeError('No actually admitted child; no cancellation success claimed')
        request('POST', base + '/cancel', {})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current, _ = request('GET', base)
            if current['state'] == 'cancelled':
                break
            time.sleep(.05)
        assert current['state'] == 'cancelled' and current['child_request_ids'] == [child]
        def hashed(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        events, _ = request('GET', base + '/events?page_size=100')
        tools, _ = request('GET', base + '/tool-calls?page_size=100')
        usage, _ = request('GET', '/api/admin/v1/usage/requests?request_id=' + child)
        assert len(usage['data']) == 1 and usage['data'][0]['status'] != 'in_progress'
        record['runs'] = [{'id': rid, 'mode': 'chat', 'state': 'cancelled', 'eventsHash': hashed(events), 'toolsHash': hashed(tools), 'children': [child], 'usageHashes': [hashed(usage['data'])], 'lastSeq': current['last_event_seq']}]
        record.pop('pendingCommand'); save()
        print(json.dumps({'passed': True, 'admitted_before_cancel': True, 'session_id': sid, 'run_id': rid, 'state': current['state'], 'child_request_ids': [child], 'usage_records': 1}))
    finally:
        request('DELETE', '/api/admin/v1/session')


if __name__ == '__main__':
    main()
