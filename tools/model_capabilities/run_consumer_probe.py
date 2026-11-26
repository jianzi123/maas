"""Check exported Go ModelClient/Registry component assertions against a built probe."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


def evaluate(binary):
    matrix = json.loads((ROOT / 'http-vectors/consumer-cases.json').read_text(encoding='utf-8'))
    rows = []
    for case in matrix['cases']:
        raw = case.get('input_raw') or json.dumps(case['input'], ensure_ascii=False, separators=(',', ':'))
        result = subprocess.run([str(binary)], input=raw.encode(), capture_output=True, timeout=20)
        actual = json.loads(result.stdout) if result.returncode == 0 else {'probe_error': result.stderr.decode(errors='replace')}
        passed = result.returncode == 0 and all(actual.get(k) == v for k, v in case['expected'].items())
        if case['id'] == 'CP04_actual_two_tool_specs':
            passed &= [s['name'] for s in actual.get('specs', [])] == ['bounded_arithmetic', 'list_visible_models']
            passed &= all(s['version'] == '1' for s in actual.get('specs', []))
        rows.append({'id': case['id'], 'passed': passed, 'exit_code': result.returncode, 'actual': actual, 'expected': case['expected']})
    return {'version': '0.9', 'summary': {'total': len(rows), 'passed': sum(r['passed'] for r in rows), 'failed': sum(not r['passed'] for r in rows)},
            'checks': rows, 'probe_binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
            'scope': 'existing exported Go RelayModel protocol gates, ToolRegistry schemas and pure/read Tool.Execute; ModelDirectory data producer is controlled',
            'production_tools_bridge_verified': False, 'Go_AgentLoop_or_SQL_verified': False, 'real_supplier_calls': 0}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    report = evaluate(args.binary.resolve())
    if args.output.resolve() in {p.resolve() for p in ROOT.rglob('*') if p.is_file()}:
        raise ValueError('cannot overwrite capability inputs')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
    print(json.dumps(report['summary']))
    return 1 if report['summary']['failed'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
