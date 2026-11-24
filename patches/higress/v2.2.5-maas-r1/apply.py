"""Apply only to a NEW local output. Source and patch hashes must match manifest."""
import argparse,hashlib,json,pathlib,shutil,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=pathlib.Path);p.add_argument('--output',required=True,type=pathlib.Path);p.add_argument('--build',action='store_true');a=p.parse_args()
m=json.loads((ROOT/'manifest.json').read_text())
for name,digest in m['files'].items():
 f=a.source/name
 if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=digest:raise SystemExit('Source mismatch: '+name)
for name,digest in m['patches'].items():
 if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise SystemExit('Patch mismatch')
src=a.source.resolve();out=a.output.resolve()
if out.exists() or out==src or src in out.parents or out in src.parents:raise SystemExit('Choose a new independent output directory')
if any(f.is_symlink() for f in src.rglob('*')):raise SystemExit('Symlink input rejected')
shutil.copytree(src,out,ignore=shutil.ignore_patterns('.git'))
for name in m['patches']:
 patch=str((ROOT/name).resolve())
 subprocess.run(['git','apply','--check',patch],cwd=out,check=True)
 subprocess.run(['git','apply',patch],cwd=out,check=True)
print(json.dumps({'patchApplied':True,'scope':'selected source bytes and apply-check only','wasmBuildVerified':False}))
if a.build:
 compiler=shutil.which('tinygo')
 if compiler is None:raise SystemExit('BUILD BLOCKED: tinygo executable unavailable')
 if not m['toolchain']['approvedVersion'] or not m['toolchain']['approvedBinarySha256']:raise SystemExit('BUILD BLOCKED: approved tinygo version/binary digest missing')
 if hashlib.sha256(pathlib.Path(compiler).read_bytes()).hexdigest()!=m['toolchain']['approvedBinarySha256']:raise SystemExit('BUILD BLOCKED: compiler digest differs')
 version=subprocess.check_output([compiler,'version']).decode().strip()
 if m['toolchain']['approvedVersion'] not in version:raise SystemExit('BUILD BLOCKED: compiler version differs')
 if subprocess.check_output(['git','-C',str(src),'status','--porcelain','--untracked-files=all']).strip():raise SystemExit('BUILD BLOCKED: source checkout is dirty')
 commit=subprocess.check_output(['git','-C',str(src),'rev-parse','HEAD']).decode().strip()
 if commit!=m['commit']:raise SystemExit('BUILD BLOCKED: complete pinned source checkout required')
 for name,want in m['gitlinks'].items():
  actual=subprocess.check_output(['git','-C',str(src),'ls-tree','HEAD',name]).decode().split()
  if len(actual)<3 or actual[2]!=want:raise SystemExit('BUILD BLOCKED: gitlink differs')
 subprocess.run([compiler,'build','-scheduler=none','-target=wasi','-o','maas-ext-auth.wasm','.'],cwd=out/'plugins/wasm-go/extensions/ext-auth',check=True,timeout=180)