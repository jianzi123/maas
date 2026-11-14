"""Compare source reader dependencies with checked-in grants, without MySQL access."""
import hashlib
import argparse
import json
import re
from pathlib import Path
from verify import ROOT

COMPLETION_SELECT = {'cluster_id', 'operation_id', 'cr_uid', 'namespace', 'name', 'requested_generation', 'state', 'acknowledged', 'desired_state', 'action', 'spec_sha256'}
COMPLETION_UPDATE = {'state', 'reason', 'publication_id', 'updated_at'}
PUBLISHER_TABLES = {'release_links', 'release_revisions', 'publish_intents', 'publications', 'active_model_bindings', 'resource_inventory', 'release_operations', 'release_schema_migrations', 'retained_release_snapshots', 'release_history_owners', 'release_history_retention', 'release_management_operations'}

def publisher_contract(sql):
    text = re.sub(r'--[^\n]*', '', sql)
    rows, invalid = [], []
    for statement in text.split(';'):
        if not re.search(r'\bTO\s+maas_release_publisher\s*$', statement, re.I):
            continue
        match = re.fullmatch(r'\s*GRANT\s+(.+?)\s+ON\s+__MAAS_DATABASE__\.(\w+)\s+TO\s+maas_release_publisher\s*', statement, re.I | re.S)
        if match:
            rows.append((match[1].strip(), match[2]))
        else:
            invalid.append('unbounded-or-inherited-grant')
    management = [verbs for verbs, table in rows if table == 'release_management_operations']
    expected = {'SELECT': COMPLETION_SELECT, 'UPDATE': COMPLETION_UPDATE}
    actual = {}
    for verbs in management:
        match = re.fullmatch(r'(SELECT|UPDATE)\s*\(([^)]+)\)', verbs, re.I)
        if not match or match[1].upper() in actual:
            invalid.append('broad-or-duplicate-management-grant')
        else:
            actual[match[1].upper()] = {c.strip().lower() for c in match[2].split(',')}
    checks = {'completion_columns_exact': actual == expected,
              'publisher_tables_only': bool(rows) and all(table in PUBLISHER_TABLES for _, table in rows),
              'no_broad_or_inherited_grants': not invalid}
    return {'scope': 'SQL-template-policy-only-not-effective-database-privileges',
            'checks': checks, 'passed': all(checks.values()),
            'completion_select': sorted(actual.get('SELECT', [])), 'completion_update': sorted(actual.get('UPDATE', []))}

def inspect(repo=None):
    repo=repo or ROOT.parent
    sql=(repo/"config/mysql/release-permissions.sql").read_text(encoding="utf-8")
    role="maas_release_history_reader"
    grants=re.findall(r"GRANT\s+(.+?)\s+ON\s+__MAAS_DATABASE__\.(\w+)\s+TO\s+"+role+r"\s*;",sql,re.I)
    allowed={table for verbs,table in grants if verbs.strip().upper()=="SELECT"}
    source=repo/"internal/release/history/reader.go"
    text=source.read_text(encoding="utf-8")
    required=set(re.findall(r"(?:FROM|JOIN)\s+(release_\w+|publications)",text))
    missing=sorted(required-allowed)
    writes=[table for verbs,table in grants if verbs.strip().upper()!="SELECT"]
    publisher = publisher_contract(sql)
    return {"scope":"static-source-grant-comparison-not-effective-database-privileges",
            "source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
            "grant_sha256":hashlib.sha256((repo/"config/mysql/release-permissions.sql").read_bytes()).hexdigest(),
            "role":role,"required":sorted(required),"granted":sorted(allowed),"missing":missing,"non_select_grants":writes,
            "publisher_completion":publisher,
            "passed":bool(required) and not missing and not writes and publisher['passed'],
            "remaining":["candidate controlapi-projections.sql provides separate payload/operations templates; effective privileges remain unverified",
                         "operations runtime includes INSERT and acknowledgement/completion UPDATE; not a SELECT-only reader",
                         "OpenPublisher now consumes an explicit DSN in local workbench; control-api read gate still uses its primary DB and production publisher/operator wiring remains unverified",
                         "R3 effective default-role positives/1142/1143 negatives were independently tested at ac94 by QA50354a7; not rerun in this deployment turn",
                         "production default roles/inherited grants and publisher process wiring remain unverified"]}
if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-root", type=Path)
    args=parser.parse_args()
    result=inspect(args.backend_root)
    (ROOT/"evidence/permissions.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)
