"""Build two self-contained delivery ZIPs from ONE committed source/lock snapshot."""
import argparse, hashlib, json, shutil, sys, tempfile, zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"scripts"))
from unified_sources import ROOT, snapshot, verify

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def package(ref,out,source_mode="full"):
    out=Path(out).resolve()
    out.mkdir(parents=True,exist_ok=True)
    with snapshot(ROOT,ref) as (commit,source):
        code,checks=verify(ROOT,commit,source)
        version={"repositoryCommit":commit,"codeCommit":code,"imageTag":code[:12],"sourceChecks":checks,
                 "sourceLockSha256":{name:digest(source/name) for name in ("deploy/build-sources.lock.json","deploy/dependencies.lock.json","deploy/identities.json","deploy/charts/maas-platform/runtime-interface.json")},
                 "platform":"linux/amd64", "productEntry":"./cmd/maas-service", "modes":["migrate","serve"],
                 "sourceMode":source_mode,"scope":"same-source-two-installers-not-model-approval"}
        with tempfile.TemporaryDirectory(prefix="release-") as temp:
            for kind in ("compose","kubernetes"):
                root=Path(temp)/kind;root.mkdir()
                if source_mode=="full":
                    shutil.copytree(source,root/"source")
                else:
                    source_manifest={f.relative_to(source).as_posix():{"sha256":digest(f),"bytes":f.stat().st_size} for f in sorted(source.rglob("*")) if f.is_file()}
                    (root/"SOURCE.sha256.json").write_text(json.dumps(source_manifest,indent=2)+"\n",encoding="utf-8")
                    shutil.copy2(source/"deploy/release/fetch_source.py",root/"fetch_source.py")
                    for name in version["sourceLockSha256"]:
                        dest=root/"metadata"/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,dest)
                package_inputs=source/"deploy/release"/kind
                if not package_inputs.is_dir():raise ValueError("missing installer: "+kind)
                for f in package_inputs.iterdir():
                    dest=root/f.name
                    if f.is_dir():shutil.copytree(f,dest)
                    else:shutil.copy2(f,dest)
                shutil.copy2(source/"deploy/release/VALIDATION.md",root/"VALIDATION.md")
                (root/"VERSION.json").write_text(json.dumps(version,indent=2)+"\n",encoding="utf-8")
                for f in root.rglob("*"):
                    # Only installer tags are rendered; archived source bytes stay exact.
                    if f.is_file() and not set(f.relative_to(root).parts)&{"source","metadata"}:
                        f.write_text(f.read_text(encoding="utf-8").replace("__IMAGE_TAG__",code[:12]).replace("__SOURCE_COMMIT__",code),encoding="utf-8",newline="\n")
                if source_mode!="full":
                    readme=root/"README.md"
                    intro="源码获取型独立安装包：包含完整安装器、四锁和逐文件校验清单。先在本目录执行 `python fetch_source.py --root .`，它从固定Git提交获取并核对全部源码/四锁，再执行下方原生构建与安装命令。需要访问GitHub公开源码；不是全离线介质，也不依赖agent目录或预发布镜像。已有source不覆盖。\n\n"
                    readme.write_text(intro+readme.read_text(encoding="utf-8"),encoding="utf-8",newline="\n")
                manifest={f.relative_to(root).as_posix():digest(f) for f in sorted(root.rglob("*")) if f.is_file()}
                if source_mode!="full":manifest.update({"source/"+name:row["sha256"] for name,row in source_manifest.items()})
                (root/"MANIFEST.sha256.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
                target=out/("maas-"+kind+"-"+commit[:12]+("-fetch" if source_mode!="full" else "")+".zip")
                if target.exists():raise FileExistsError(target)
                with zipfile.ZipFile(target,"w",zipfile.ZIP_DEFLATED) as z:
                    for f in sorted(root.rglob("*")):
                        if f.is_file():
                            zi=zipfile.ZipInfo(f.relative_to(root).as_posix(),date_time=(2026,1,1,0,0,0))
                            zi.compress_type=zipfile.ZIP_DEFLATED
                            zi.external_attr=0o644<<16
                            z.writestr(zi,f.read_bytes())
    hashes={p.name:digest(p) for p in out.glob("maas-*-"+commit[:12]+("-fetch" if source_mode!="full" else "")+".zip")}
    (out/("SHA256-"+commit[:12]+".json")).write_text(json.dumps(hashes,indent=2)+"\n")
    print(json.dumps({"version":version,"packages":hashes}))
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ref",default="HEAD");p.add_argument("--output",required=True)
    p.add_argument("--source-mode",choices=["full","fetch"],default="full")
    a=p.parse_args();package(a.ref,a.output,a.source_mode)
