"""Positive/negative SQL checks through the exact generated product runtime account."""
import argparse,configparser,json,os,re,subprocess
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--compose",type=Path,required=True);p.add_argument("--project",required=True);p.add_argument("--output",type=Path,required=True)
a=p.parse_args()
def linux(path):
    path=path.resolve();return "/mnt/"+path.drive[0].lower()+"/"+path.relative_to(path.anchor).as_posix() if os.name=="nt" else str(path)
prefix=["wsl","-d","Ubuntu-22.04","--exec","docker"] if os.name=="nt" else ["docker"]
client_file=a.compose.parent/".secrets/migration/runtime-client.cnf"
config=configparser.ConfigParser(interpolation=None)
config.read(client_file,encoding="utf-8")
if config.get("client","host",fallback="")!="mysql":raise SystemExit("SQL mutation probes require the bundled owned MySQL; external targets refused")
owned=subprocess.run(prefix+["compose","-p",a.project,"-f",linux(a.compose),"ps","-q","mysql"],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
if owned.returncode or not owned.stdout.strip():raise SystemExit("owned bundled MySQL is not running")
command=prefix+["compose","-p",a.project,"--project-directory",linux(a.compose.parent),"-f",linux(a.compose),"run","--rm","--no-deps","--entrypoint","mysql","migrate","--defaults-extra-file=/run/secrets/runtime-client.cnf","--batch","--skip-column-names","maas"]
def query(sql):return subprocess.run(command,input=sql,text=True,encoding="utf-8",errors="replace",capture_output=True,timeout=60)
r=query("SELECT CURRENT_USER(),CURRENT_ROLE();")
if r.returncode or not r.stdout.strip().startswith("maas_runtime@"):raise SystemExit("runtime account not verified; no permission mutations attempted")
rows=[{"check":"exact_account_and_default_roles","passed":True,"identity":r.stdout.strip()}]
cases=[
 ("session_select","SELECT session_id,owner_id,revision,document FROM agent_sessions_v1 LIMIT 0;",True),
 ("session_cas_columns","UPDATE agent_sessions_v1 SET revision=revision,document=document WHERE 1=0;",True),
 ("session_insert","INSERT INTO agent_sessions_v1(session_id,owner_id,revision,document) SELECT UUID(),'owned-probe',1,JSON_OBJECT() WHERE 1=0;",True),
 ("no_ddl","CREATE TABLE maas_owned_forbidden_probe(id INT);",False),
 ("no_global_credentials","SELECT User FROM mysql.user LIMIT 0;",False),
 ("no_admin_policy_write","UPDATE product_admins SET enabled=enabled WHERE 1=0;",False),
 ("no_history_metadata","SELECT * FROM release_history_projection LIMIT 0;",False),
 ("no_private_payload","SELECT spec_bytes FROM retained_release_snapshots LIMIT 0;",False),
 ("no_management_operations","SELECT * FROM release_management_operations LIMIT 0;",False),
]
for name,sql,allowed in cases:
    r=query(sql);code=re.search(r"ERROR\s+(\d+)",r.stderr)
    error=int(code.group(1)) if code else None
    passed=r.returncode==0 if allowed else r.returncode!=0 and error in (1044,1142,1143,1227)
    rows.append({"check":name,"allowed":allowed,"exitCode":r.returncode,"mysqlError":error,"passed":passed})
result={"scope":"owned-MySQL8.4-product-runtime-default-role-checks-not-production","passed":all(x["passed"] for x in rows),"checks":rows}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result));raise SystemExit(0 if result["passed"] else 1)
