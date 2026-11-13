"""Timing counterexample using existing client SSE parser and pinned backend source."""

from pathlib import Path
import argparse, hashlib, importlib.util, json, re, subprocess

BACKEND = "e1bd5020887d092feb892992476bb810512a274e"
PATH = "internal/kernel/relay_forward.go"


def classify(events):
    # Mirrors the observed unguarded first assignment only, not the Go relay execution.
    accepted = [e for e in events if e["kind"] == "normalized_chunk"]
    content = [
        e
        for e in accepted
        if any(
            isinstance(c.get("delta", {}).get("content"), str)
            and bool(c["delta"]["content"])
            for c in e["value"].get("choices", [])
        )
    ]
    return {
        "legacy_first_normalized_event_ms": accepted[0]["at_ms"] if accepted else None,
        "go_content_write_boundary_ms_proposed": (
            content[0]["at_ms"] if content else None
        ),
    }


def cases():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("perf_analyze", root / "analyze.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events = [
        {
            "at_ms": 5,
            "kind": "normalized_chunk",
            "value": {"choices": [{"delta": {"role": "assistant"}}]},
        },
        {"at_ms": 10, "kind": "normalized_chunk", "value": {"choices": []}},
        {
            "at_ms": 15,
            "kind": "normalized_chunk",
            "value": {"choices": [{"delta": {"content": ""}}]},
        },
        {
            "at_ms": 30,
            "kind": "normalized_chunk",
            "value": {"choices": [{"delta": {"content": "合成"}}]},
        },
        {
            "at_ms": 60,
            "kind": "normalized_chunk",
            "value": {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        },
    ]
    frames = [
        {
            "at_ms": e["at_ms"],
            "wire": "data: " + json.dumps(e["value"], ensure_ascii=False) + "\n\n",
        }
        for e in events
    ]
    frames.append({"at_ms": 61, "wire": "data: [DONE]\n\n"})
    parsed = module.sse_metrics(frames)
    if parsed["content_times"] != [30]:
        raise RuntimeError("client first-content regression")
    no_content = events[:3] + events[4:]
    return {
        "synthetic": True,
        "scope": "Python reproduction of observed assignment predicate; Go relay NOT executed",
        "with_content": dict(
            classify(events),
            client_content_times_ms=parsed["content_times"],
            client_clock_scope="synthetic-client",
        ),
        "without_content": classify(no_content),
        "worker_native_ttft": {
            "value_ms": 7,
            "clock_scope": "synthetic-worker-independent",
            "cannot_subtract_from_client": True,
        },
        "product_patch_owner": "original MAAS-3 backend engineer",
        "required_regressions": [
            "role-only before content",
            "usage-only/empty delta",
            "finish-only no content -> null",
            "failed write before visible content",
            "split UTF8/multiline SSE",
            "content then cancel/EOF",
            "public usage finality unchanged",
        ],
    }


def source_record(repo):
    data = subprocess.check_output(
        ["git", "-C", str(repo), "show", BACKEND + ":" + PATH]
    )
    text = data.decode()
    pattern = r"if first == nil \{\s+ms := time.Since\(call.Input.Received\).Milliseconds\(\)\s+first = &ms\s+\}\s+if err = writeChunk\(out\); err != nil"
    match = re.search(pattern, text)
    if not match:
        raise ValueError("backend predicate changed; re-review")
    line = text[: match.start()].count("\n") + 1
    return {
        "commit": BACKEND,
        "path": PATH,
        "sha256": hashlib.sha256(data).hexdigest(),
        "first_assignment_line": line,
        "write_boundary_before_success": True,
        "source_predicate": match.group(0),
        "url": f"https://github.com/jianzi123/maas/blob/{BACKEND}/{PATH}#L{line}",
        "not_product_execution": True,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    r = cases()
    r["source"] = source_record(a.repo)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("x", encoding="utf-8") as f:
        json.dump(r, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(
        json.dumps(
            {
                "legacy_ms": 5,
                "client_content_ms": 30,
                "contentless_proposed": None,
                "backend_modified": False,
            }
        )
    )


if __name__ == "__main__":
    main()
