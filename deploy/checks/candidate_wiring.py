"""Audit exact candidate source consumers; no database, Secret or cluster access."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from verify import ROOT
from identities import PAYLOAD_ROLE


def publisher_checks(runtime, local, identities):
    return {
        'publisher_explicit_dsn_and_evidence_required': 'if dsn == "" || k == nil' in runtime,
        'publisher_dsn_options_checked': all(x in runtime for x in ('mysql.ParseDSN(dsn)', 'cfg.User', '"root"', 'cfg.DBName', '!cfg.ParseTime', 'cfg.MultiStatements')),
        'publisher_role_checked': 'SELECT CURRENT_ROLE()' in runtime and '`maas_release_publisher`@`%`' in runtime,
        'publisher_completion_hook_enabled': 'Store: store.WithManagementOperations()' in runtime,
        'publisher_no_env_or_core_fallback': all(x not in runtime for x in ('os.Getenv', 'MAAS_MYSQL_DSN', 'MAAS_OPERATIONS_DSN')),
        'local_publisher_factory_consumed': 'mysqlstore.OpenPublisher(ctx, connections.PublisherDSN,' in local,
        'local_core_handle_separated': 'kernel.New(connections.Core,' in local,
        'local_reader_payload_handles_separated': 'DB: connections.History, PayloadDB: connections.Payload' in local,
        'local_operations_handle_separated': 'management.Operations{DB: connections.Operations' in local,
        'installer_owned_temp_guard': all(x in identities for x in ('//go:build localworkbench', 'cfg.DBName != "maas_workbench"', 'cfg.Net != "unix"', '"/tmp/maas-workbench."')),
        'installer_payload_role_current': '"'+PAYLOAD_ROLE+'"' in identities and '"maas_release_history_payload_reader"' not in identities,
    }


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
        'payload_role_provided': 'CREATE ROLE IF NOT EXISTS '+PAYLOAD_ROLE+';' in grants,
        'operations_runtime_role_provided': 'CREATE ROLE IF NOT EXISTS maas_release_operations_runtime;' in grants,
        'operations_writes_explicit': 'GRANT SELECT,INSERT ON __MAAS_DATABASE__.release_management_operations' in grants and 'UPDATE(state,reason,acknowledged,cr_uid,requested_generation,publication_id,updated_at)' in grants,
        'no_user_provisioning': not re.search(r'^\s*CREATE USER',grants,re.M|re.I),
    }
    runtime=(repo/'internal/release/mysqlstore/runtime.go').read_text(encoding='utf-8')
    local=(repo/'cmd/workbench/main.go').read_text(encoding='utf-8')
    identities=(repo/'cmd/workbench/identities.go').read_text(encoding='utf-8')
    checks.update(publisher_checks(runtime, local, identities))
    return {'scope':'static-candidate-source-not-process-startup-or-effective-privileges',
            'checks':checks,'passed':all(checks.values()),
            'files_sha256':{p:hashlib.sha256((repo/p).read_bytes()).hexdigest() for p in ['cmd/control-api/main.go','cmd/control-api/readers.go','config/mysql/controlapi-projections.sql','internal/release/mysqlstore/runtime.go','cmd/workbench/main.go','cmd/workbench/identities.go']},
            'gaps':['OpenPublisher consumes an explicit argument in local workbench; no production publisher/operator adapter or new environment variable is supplied. control-api still constructs a read gate on its primary DB.',
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
