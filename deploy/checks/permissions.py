"""Compare source reader dependencies with checked-in grants, without MySQL access."""
import hashlib
import json
import re
from pathlib import Path
from verify import ROOT

def inspect():
    repo=ROOT.parent
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
            "remaining":["payload reader role is not provided by existing release-permissions.sql",
                         "operation Read may update completion projection; ordinary SELECT-only role is insufficient",
                         "control-api uses one primary DB for core/history/operations/publisher; distinct production wiring pending",
                         "default roles, inherited grants and positive/negative SQL checks need an authorized temporary MySQL test"]}
if __name__=="__main__":
    result=inspect()
    (ROOT/"evidence/permissions.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)