"""Validate complete exported inputs and create a fresh build context. Never starts services."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from verify import ROOT


def inventory(root, component):
    files = {}
    for p in root.rglob('*'):
        name = p.relative_to(root).as_posix()
        if component == 'backend' and name.split('/')[0] in ('console', 'deploy'):
            continue
        if component == 'console' and not name.startswith('console/'):
            continue
        if p.is_symlink():
            raise ValueError('symlink build input: ' + name)
        if p.is_file():
            files[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return files


def compare(root, expected, component):
    actual = inventory(root, component)
    return {'component': component, 'expected': len(expected),
            'matched': sum(actual.get(p) == digest for p, digest in expected.items()),
            'missing': sorted(set(expected) - set(actual)),
            'unexpected': sorted(set(actual) - set(expected)),
            'changed': sorted(p for p in set(expected) & set(actual) if expected[p] != actual[p]),
            'passed': actual == expected}


def assemble(backend, console, output, lock):
    rows = [compare(root, lock[c]['files'], c) for c, root in [('backend', backend), ('console', console)]]
    if not all(row['passed'] for row in rows):
        raise ValueError('source input mismatch: ' + json.dumps(rows))
    output = output.resolve()
    for source in (backend.resolve(), console.resolve(), ROOT.resolve()):
        if output == source or source in output.parents:
            raise ValueError('output must be outside input trees')
    # Refuse reuse/overwrite, including any existing workbench directory.
    output.mkdir(parents=True, exist_ok=False)
    for component, source in [('backend', backend), ('console', console)]:
        for name in lock[component]['files']:
            rel = PurePosixPath(name)
            if rel.is_absolute() or '..' in rel.parts:
                raise ValueError('invalid source inventory path')
            dest = output / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, dest)
    overlay = {}
    for p in ROOT.rglob('*'):
        rel = p.relative_to(ROOT)
        if p.is_file() and not set(rel.parts) & {'evidence', '__pycache__'}:
            dest = output / 'deploy' / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
            overlay[rel.as_posix()] = hashlib.sha256(dest.read_bytes()).hexdigest()
    final = [compare(output, lock[c]['files'], c) for c in ('backend', 'console')]
    if not all(row['passed'] for row in final):
        raise ValueError('assembled context mismatch')
    return {'scope': 'complete-source-context-only-no-build-or-deployment', 'inputs': rows, 'assembled': final,
            'backendCommit': lock['backend']['sourceCommit'], 'consoleCommit': lock['console']['sourceCommit'],
            'qaCoreCommit': lock['qa']['targetCommit'], 'qaScope': lock['qa']['scope'],
            'deploymentOverlaySha256': overlay,
            'currentWorkbenchModified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-root', required=True, type=Path)
    parser.add_argument('--console-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    lock = json.loads((ROOT / 'build-sources.lock.json').read_text(encoding='utf-8'))
    report = assemble(args.backend_root, args.console_root, args.output, lock)
    (ROOT / 'evidence/assembly-inspection.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(report))
