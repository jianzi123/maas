"""Export fixed Git bytes and original authenticated offline ZIP; no manifests executed."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo",type=Path,required=True)
    p.add_argument("--original-zip",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a = p.parse_args()
    target = a.output.resolve()
    target.mkdir(exist_ok=False,parents=True)
    def unpack(blob,dest):
        dest.mkdir()
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for name in z.namelist():
                assert (dest/name).resolve().is_relative_to(dest.resolve())
            z.extractall(dest)
    def export(ref,dest,paths):
        blob = subprocess.check_output(["git","-C",str(a.repo),"archive","--format=zip",ref,*paths])
        unpack(blob,dest)
        return hashlib.sha256(blob).hexdigest()
    m = {"product_head":"4ab8a277efe5edb9219d83cc9aea204add36af8e", "implementation":"3a2966225cd0102663687ad281a0264cb5e0822e",
         "source_lock":"029fd0528e99034de769d7fde6c24bee1e4a248e","delivery":"7c10e4d3397848de1f4508ec4295b7dc25324a45",
         "old_delivery":"5f8bd5d83968f9ed5e674593bb8d19078c4575ad"}
    tool = "tools/perf/operators/local_gpu"
    locks = ["deploy/build-sources.lock.json","deploy/charts/maas-platform/runtime-interface.json","deploy/dependencies.lock.json","deploy/identities.json"]
    m["product_export_sha256"] = export(m["product_head"],target/"product",[tool,*locks,"tools/perf/diagnostics/evidence/single-model-v0.23/delivery"])
    m["legacy_export_sha256"] = export(m["old_delivery"],target/"legacy",[tool])
    original = a.original_zip.read_bytes()
    m["original_attachment"] = "01a1dd40-3774-71ee-b270-238d67a77937"
    m["original_zip_sha256"] = hashlib.sha256(original).hexdigest()
    assert m["original_zip_sha256"] == "64e348ddb21eb84f6a4c4827c8c0aaedeb38c2e6f4add85e591ab0775539990f"
    unpack(original,target/"evidence")
    m["files"] = {str(f.relative_to(target)).replace("\\","/"):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(target.rglob("*")) if f.is_file()}
    (target/"input-manifest.json").write_text(json.dumps(m,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"root":str(target),"files":len(m["files"])}))

if __name__ == "__main__":
    main()
