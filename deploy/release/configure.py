"""Fresh-install configuration generator. Keeps secrets outside archived source; never overwrites."""
import argparse, copy, json, os, secrets, uuid, re
from urllib.parse import urlsplit
from pathlib import Path
import yaml
p=argparse.ArgumentParser(description=__doc__)
p.add_argument("--format",choices=["compose","kubernetes"],required=True)
p.add_argument("--profile",choices=["external-api","offline-controlled"],default="external-api",help="Explicit offline opt-in; normal install never falls back to a demo")
p.add_argument("--directory",type=Path,default=Path("."))
p.add_argument("--source",type=Path)
p.add_argument("--origin")
p.add_argument("--port",type=int,default=18080)
p.add_argument("--project")
p.add_argument("--database-host",default="mysql")
p.add_argument("--root-password-file",type=Path,help="Existing authorized external-MySQL migration password; otherwise generated for bundled MySQL")
a=p.parse_args()
if not 1024<=a.port<=65535:p.error("port must be 1024..65535")
a.origin=a.origin or "http://localhost:"+str(a.port)
root=a.directory.resolve()
source=a.source.resolve() if a.source else root/"source"
state=root/".secrets"
if state.exists():raise SystemExit("Existing .secrets: retain installation identity/passwords; edit nonsecret config or use a new install directory.")
example=source/("config/product.offline.example.json" if a.profile=="offline-controlled" else "config/product.example.json")
if not example.is_file():raise SystemExit("Actual product config example is required from the same source snapshot")
config=json.loads(example.read_text(encoding="utf-8"))
public_candidates=[source/"console/public/console-config.json",source/"console/public/console-config.example.json"]
public=next((x for x in public_candidates if x.is_file()),None)
if public is None:raise SystemExit("Same-version public console-config.json example is required")
u=urlsplit(a.origin)
if u.scheme not in ("http","https") or not u.netloc or u.username or u.password or u.path not in ("","/") or u.query or u.fragment:raise SystemExit("Explicit HTTP(S) origin without path/userinfo required")
if not re.fullmatch(r"[A-Za-z0-9.-]+",a.database_host):raise SystemExit("Explicit DNS/IPv4 database host required")
root.mkdir(parents=True,exist_ok=True);state.mkdir(mode=0o700)
runtime=state/"runtime";migration=state/"migration"
runtime.mkdir(mode=0o755);migration.mkdir(mode=0o755)
def write_secret(path,value):
    path.write_text(value,encoding="utf-8",newline="\n")
    os.chmod(path,0o444) # enclosed by 0700 directory; non-root container file bind can read it.
root_password=a.root_password_file.read_text().strip() if a.root_password_file else secrets.token_hex(32)
runtime_password=secrets.token_hex(32)
bootstrap=secrets.token_urlsafe(24)
pepper=secrets.token_urlsafe(48);cursor=secrets.token_urlsafe(48)
runtime_dsn="maas_runtime:"+runtime_password+"@tcp("+a.database_host+":3306)/maas?parseTime=true&loc=UTC"
migration_dsn="root:"+root_password+"@tcp("+a.database_host+":3306)/maas?parseTime=true&loc=UTC"
write_secret(state/"mysql-root-password",root_password)
runtime_files={"maas_runtime_dsn":runtime_dsn,"maas_key_pepper":pepper,"maas_cursor_key":cursor}
migration_files={**runtime_files,"maas_migration_dsn":migration_dsn,"maas_bootstrap_password":bootstrap,"maas_runtime_password":runtime_password,
 "runtime-client.cnf":"[client]\nhost="+a.database_host+"\nprotocol=tcp\nuser=maas_runtime\npassword="+runtime_password+"\n",
 "mysql-client.cnf":"[client]\nhost="+a.database_host+"\nprotocol=tcp\nuser=root\npassword="+root_password+"\n"}
for name,value in runtime_files.items():write_secret(runtime/name,value)
for name,value in migration_files.items():write_secret(migration/name,value)
config.update(listen="0.0.0.0:8080",origin=a.origin,cluster_id=str(uuid.uuid4()),static_dir="/app/console",contract_file="/app/docs/contracts/agent-runtime/ar1-draft2/openapi.json")
config["auth"].update(admin_id=str(uuid.uuid4()),secure_cookie=a.origin.startswith("https://"))
config["models"]=[];config["gateway"]={}
migration_config=copy.deepcopy(config)
(root/"config").mkdir(exist_ok=True)
def json_file(path,value):path.write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8",newline="\n")
json_file(root/"config/product.json",config);json_file(root/"config/migration.json",migration_config)
public_json={"schema_version":"maas.console/1","chat":{"enabled":True,"limits":copy.deepcopy(config["agent"]["limits"]),"tools":[]}}
if a.profile=="offline-controlled":
    public_json["chat"]["tools"]=[{"name":name,"revision":"1"} for name in ("bounded_arithmetic","list_visible_models")]
json_file(root/"config/console-config.json",public_json)
if a.format=="compose":
    version=json.loads((root/"VERSION.json").read_text()) if (root/"VERSION.json").is_file() else {"imageTag":"ops-2307"}
    (root/".env").write_text("COMPOSE_PROJECT_NAME="+(a.project or "maas-"+config["cluster_id"][:8])+"\nCOMPOSE_PARALLEL_LIMIT=1\nHTTP_BIND=127.0.0.1\nHTTP_PORT="+str(a.port)+"\nMAAS_APP_IMAGE=maas-app:"+version["imageTag"]+"\nMAAS_WEB_IMAGE=maas-web:"+version["imageTag"]+"\nMAAS_MIGRATE_IMAGE=maas-migrate:"+version["imageTag"]+"\nMYSQL_IMAGE=mysql:8.4.7@sha256:0426ec38c7a10aa45ba383887df7878f74ee70e2fd589c7b69207f3577901903\n",encoding="utf-8")
    os.chmod(root/".env",0o600)
else:
    documents=[
      {"apiVersion":"v1","kind":"Secret","metadata":{"name":"maas-mysql","namespace":"maas"},"type":"Opaque","stringData":{"root-password":root_password}},
      {"apiVersion":"v1","kind":"Secret","metadata":{"name":"maas-runtime","namespace":"maas"},"type":"Opaque","stringData":runtime_files},
      {"apiVersion":"v1","kind":"Secret","metadata":{"name":"maas-migration","namespace":"maas"},"type":"Opaque","stringData":migration_files},
      {"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"maas-config","namespace":"maas"},"data":{"product.json":json.dumps(config),"migration.json":json.dumps(migration_config)}},
      {"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"maas-console","namespace":"maas"},"data":{"console-config.json":json.dumps(public_json)}}]
    (root/"config.yaml").write_text(yaml.safe_dump_all(documents,sort_keys=False),encoding="utf-8")
    os.chmod(root/"config.yaml",0o600)
print("Configuration generated; profile="+a.profile+". No real model is implicitly approved. Initial admin password is only in .secrets/migration/maas_bootstrap_password; keep all secrets and installation IDs across restart/upgrade.")
