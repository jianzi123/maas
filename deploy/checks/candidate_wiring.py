"""Audit exact candidate source consumers; no database, Secret or cluster access."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from verify import ROOT


def inspect(repo):
    main=(repo/'cmd/control-api/main.go').read_text(encoding='utf-8')
    factory=(repo/'cmd/control-api/readers.go').read_text(encoding='utf-8')
    grants=(repo/'config/mysql/controlapi-projections.sql').read_text(encoding='utf-8')
    checks={
        'history_env_consumed': 'openReader("MAAS_HISTORY_READER_DSN")' in main,
        'operations_env_consumed': 'openReader("MAAS_OPERATIONS_DSN")' in main,
        'history_handle_injected': bool(re.search(r'history.Reader\{DB:\s*historyDB',main)),
        'operations_handle_injected': bool(re.search(r'management.Operations\{DB:\s*operationsDB',main)),
        'payload_separate_handle': 'os.Getenv("MAAS_HISTORY_PAYLOAD_DSN")' in main and 'hr.PayloadDB = payload' in main,
        'missing_projection_no_core_fallback': bool(re.search(r'if dsn == ""\s*\{\s*return nil, nil',factory)) and 'MAAS_MYSQL_DSN' not in factory,
        'management_requires_operations': 'if operationsDB == nil' in main and 'explicit management operation connection required' in main,
        'primary_not_in_public_readers': not re.search(r'(history.Reader|management.Operations)\{DB:\s*db\b',main),
        'payload_role_provided': 'CREATE ROLE IF NOT EXISTS maas_release_history_payload_reader;' in grants,
        'operations_runtime_role_provided': 'CREATE ROLE IF NOT EXISTS maas_release_operations_runtime;' in grants,
        'operations_writes_explicit': 'GRANT SELECT,INSERT ON __MAAS_DATABASE__.release_management_operations' in grants and 'UPDATE(state,reason,acknowledged,cr_uid,requested_generation,publication_id,updated_at)' in grants,
        'no_user_provisioning': not re.search(r'^\s*CREATE USER',grants,re.M|re.I),
    }
    return {'scope':'static-candidate-source-not-process-startup-or-effective-privileges',
            'checks':checks,'passed':all(checks.values()),
            'files_sha256':{p:hashlib.sha256((repo/p).read_bytes()).hexdigest() for p in ['cmd/control-api/main.go','cmd/control-api/readers.go','config/mysql/controlapi-projections.sql']},
            'gaps':['No publisher DSN consumer; mysqlstore.New still receives the primary handle (its ModelGate use must be distinguished from a publisher writer).',
                    'Explicit DSNs do not prevent an installer from configuring the same account; offline plan rejects shared principals/keys.',
                    'Empty history DSN yields nil Reader DB and request-time failure; empty operations is fatal only with management enabled.',
                    'Payload is optional at startup; missing rollback payload must remain unavailable.',
                    'Controlled loopback API has no production health/inference listener; full process startup and effective roles not tested here.']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend-root',required=True,type=Path)
    args=p.parse_args()
    report=inspect(args.backend_root)
    (ROOT/'evidence/candidate-wiring.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(report))
    raise SystemExit(0 if report['passed'] else 1)
