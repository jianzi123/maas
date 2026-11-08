#!/usr/bin/env python3
"""Compare local reviewed source exports with the packaged deployment interface; no network."""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from verify import CHART, ROOT

def inspect(backend_root, console_root):
    interface = json.loads((CHART / 'runtime-interface.json').read_text(encoding='utf-8'))
    rows = []
    for component, root in [('backend', backend_root), ('console', console_root)]:
        for name, expected in interface[component]['files'].items():
            p = root / name
            actual = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
            rows.append({'component': component, 'path': name, 'expected_sha256': expected, 'actual_sha256': actual, 'passed': actual == expected})
    return rows

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend-root', required=True, type=Path)
    p.add_argument('--console-root', required=True, type=Path)
    args = p.parse_args()
    rows = inspect(args.backend_root, args.console_root)
    result = {'generated_at': datetime.now(timezone.utc).isoformat(), 'scope': 'source-byte-comparison-only', 'checks_passed': sum(r['passed'] for r in rows), 'checks_total': len(rows), 'checks': rows}
    (ROOT / 'evidence').mkdir(exist_ok=True)
    (ROOT / 'evidence/source-inspection.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'checks'}))
    raise SystemExit(0 if all(r['passed'] for r in rows) else 1)

if __name__ == '__main__':
    main()
