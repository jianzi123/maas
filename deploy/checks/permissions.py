"""Compare source reader dependencies with checked-in grants, without MySQL access."""
import hashlib
import argparse
import json
import re
from pathlib import Path
from verify import ROOT

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
    return {"scope":"static-source-grant-comparison-not-effective-database-privileges",
            "source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
            "grant_sha256":hashlib.sha256((repo/"config/mysql/release-permissions.sql").read_bytes()).hexdigest(),
            "role":role,"required":sorted(required),"granted":sorted(allowed),"missing":missing,"non_select_grants":writes,
            "passed":bool(required) and not missing and not writes,
            "remaining":["candidate controlapi-projections.sql provides separate payload/operations templates; effective privileges remain unverified",
                         "operations runtime includes INSERT and acknowledgement/completion UPDATE; not a SELECT-only reader",
                         "control-api separates history/operations/payload but still constructs mysqlstore with the primary DB; no publisher DSN consumer",
                         "default roles, inherited grants and positive/negative SQL checks need an authorized temporary MySQL test"]}
if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-root", type=Path)
    args=parser.parse_args()
    result=inspect(args.backend_root)
    (ROOT/"evidence/permissions.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)
