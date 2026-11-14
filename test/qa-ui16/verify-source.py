from pathlib import Path
import sys,json,hashlib
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/"scripts"))
from unified_sources import snapshot,verify
candidate="b73d96be97e3666d3470106d5b6d13fd91c5c9f7"
with snapshot(root,candidate) as (commit,source):
    code,checks=verify(root,commit,source)
    lock=json.loads((source/"deploy/build-sources.lock.json").read_text(encoding="utf8"))
    result={"candidate":commit,"code_commit":code,"inventory_counts":{k:len(lock[k]["files"]) for k in ("backend","console")},"checks":checks}
(root/"test/qa-ui16/source-verification.json").write_text(json.dumps(result,ensure_ascii=True,indent=2),encoding="utf8")
print(json.dumps(result,ensure_ascii=True))