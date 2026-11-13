"""Explicit fixed-URL source preparation only; no engine import or execution."""

import argparse, hashlib, json, urllib.request
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-root", required=True, type=Path)
    a = p.parse_args()
    lock = json.loads(
        Path(__file__).with_name("source-lock.json").read_text(encoding="utf-8")
    )
    for item in lock["files"]:
        url = f"https://raw.githubusercontent.com/sgl-project/sglang/{item['commit']}/{item['path']}"
        if (
            url != item["url"]
            or len(item["commit"]) != 40
            or ".." in item["path"].split("/")
        ):
            raise ValueError("invalid source lock")
        dest = (a.source_root / item["commit"] / item["path"]).resolve()
        if not dest.is_relative_to(a.source_root.resolve()):
            raise ValueError("source path")
        if dest.exists():
            data = dest.read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=25) as response:
                data = response.read(3000000)
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("fixed official source mismatch")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            dest.write_bytes(data)
    print(json.dumps({"verified_files": len(lock["files"]), "engine_imported": False}))


if __name__ == "__main__":
    main()
