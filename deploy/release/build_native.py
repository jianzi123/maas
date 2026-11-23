"""Rebuild Linux runtime binaries + production Vue from this package's complete source."""
import argparse, json, os, subprocess, shutil
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument("--root",type=Path,default=Path("."))
p.add_argument("--go-cache",type=Path)
p.add_argument("--npm-cache",type=Path)
a=p.parse_args();root=a.root.resolve();source=root/"source" if (root/"source").is_dir() else root
if (root/"VERSION.json").is_file():
    from verify_bundle import verify
    if not verify(root,source_only=True)["passed"]:raise SystemExit("Installer manifest/source verification failed")
version=json.loads((root/"VERSION.json").read_text()) if (root/"VERSION.json").is_file() else {"codeCommit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=source,text=True).strip()}
node=subprocess.check_output(["node","--version"],text=True).strip()
if tuple(map(int,node.lstrip("v").split(".")))<(22,22,2):raise SystemExit("Node22.22.2+ required by the lockfile; validated22.23.4")
out=source/"deploy/release/build";out.mkdir(parents=True,exist_ok=True)
env={**os.environ,"GOOS":"linux","GOARCH":"amd64","CGO_ENABLED":"0","GOTOOLCHAIN":"go1.26.0","GOMAXPROCS":"2","GOMEMLIMIT":"512MiB","GOCACHE":str(a.go_cache.resolve() if a.go_cache else source/".cache/go-build")}
for package,name in [("./cmd/maas-service","maas"),("./deploy/probe","maas-probe")]:
    subprocess.run(["go","build","-p=2","-trimpath","-buildvcs=false","-o",str(out/name),package],cwd=source,env=env,check=True)
npm="npm.cmd" if os.name=="nt" else "npm"
subprocess.run([npm,"ci","--prefix","console","--cache",str(a.npm_cache.resolve() if a.npm_cache else source/".cache/npm")],cwd=source,check=True)
subprocess.run([npm,"run","build","--prefix","console"],cwd=source,env={**os.environ,"NODE_OPTIONS":"--max-old-space-size=512"},check=True)
print("Linux binaries and production static assets built. Next select MAAS_DOCKERFILE=deploy/release/Dockerfile.native for Compose image build.")