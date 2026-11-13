"""Verify downloaded fixed-SHA source bytes and AST anchors without importing it."""
import argparse,ast,hashlib,json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads(Path(__file__).with_name("sglang-source-map-v0.5.json").read_text(encoding="utf-8"))
    rows=[]
    for item in manifest["files"]:
        data=(args.source_root/item["path"]).read_bytes()
        matched=hashlib.sha256(data).hexdigest()==item["sha256"]
        tree=ast.parse(data.decode("utf-8"))
        positions={(node.name,node.lineno,node.end_lineno) for node in ast.walk(tree)
                   if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
        anchors=all((s["name"],s["line"],s["end_line"]) in positions for s in item["symbols"])
        rows.append({"path":item["path"],"sha256_matches":matched,"ast_anchors_match":anchors})
    report={"commit":manifest["commit"],"source_only_not_runtime_verified":True,"files":rows,
            "passed":all(r["sha256_matches"] and r["ast_anchors_match"] for r in rows)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({"source_files":len(rows),"passed":report["passed"]}))
    return 0 if report["passed"] else 1
if __name__=="__main__":raise SystemExit(main())
