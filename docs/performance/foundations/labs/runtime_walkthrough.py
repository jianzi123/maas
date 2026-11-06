"""Deterministic TEACHING model; no GPU/SGLang scheduler or benchmark."""
import json
import math


def simulate():
    # Each round completes synchronously. Budget units are NOT GPU cost or time.
    requests = [
        {"id": "A", "arrival": 0, "input": 4, "output": 3, "prefill": 0, "decoded": 0},
        {"id": "B", "arrival": 1, "input": 2, "output": 3, "prefill": 0, "decoded": 0},
    ]
    traces = []
    for step in range(10):
        tokens = 2
        work = []
        # Final prefill samples the FIRST output; only O-1 additional decode forwards.
        for r in requests:
            if (tokens and r["arrival"] <= step and r["prefill"] == r["input"]
                    and r["decoded"] < r["output"] - 1):
                r["decoded"] += 1
                tokens -= 1
                work.append(r["id"] + ":decode")
        for r in requests:
            if tokens and r["arrival"] <= step and r["prefill"] < r["input"]:
                count = min(tokens, r["input"] - r["prefill"])
                r["prefill"] += count
                tokens -= count
                work.append(r["id"] + ":prefill+" + str(count))
        state = {}
        for r in requests:
            generated = 1 + r["decoded"] if r["prefill"] == r["input"] else 0
            if r["arrival"] > step:
                phase, pages = "not_arrived", 0
            elif generated == r["output"]:
                phase, pages = "finished", 0
            else:
                phase = "decode_ready" if r["prefill"] == r["input"] else "prefilling"
                # Last sampled token has NOT been fed into a subsequent forward.
                pages = math.ceil((r["prefill"] + r["decoded"]) / 2)
            state[r["id"]] = {"phase": phase, "prefill": r["prefill"],
                              "decoded": r["decoded"], "generated": generated, "pages": pages}
        traces.append({"step": step, "work": work, "state": state,
                       "resident_pages": sum(r["pages"] for r in state.values())})
        if all(r["decoded"] == r["output"] - 1 for r in requests):
            break
    return {"teaching_only": True, "real_time_or_token_throughput": None, "trace": traces,
            "assumptions": "synchronous logical rounds; final prefill samples first output; no GPU cost model"}


def page_lifetime():
    # Two users share an immutable FULL prefix page. A has outstanding device work.
    pages = {"P2": {"refs": 2, "inflight": 0}, "P5": {"refs": 1, "inflight": 1},
             "P7": {"refs": 1, "inflight": 0}}
    tables = {"A": ["P2", "P5"], "B": ["P2", "P7"]}
    for name in tables["A"]:
        pages[name]["refs"] -= 1
    after_detach = {name: value.copy() for name, value in pages.items()}
    free_before_event = [name for name, p in pages.items() if p["refs"] == p["inflight"] == 0]
    pages["P5"]["inflight"] = 0  # simulated completion, NOT an actual CUDA event
    free_after_event = [name for name, p in pages.items() if p["refs"] == p["inflight"] == 0]
    return {"after_A_detach": after_detach, "free_before_completion": free_before_event,
            "free_after_completion": free_after_event, "B_table": tables["B"],
            "production_completion_proof": False}


if __name__ == "__main__":
    print(json.dumps({"runtime": simulate(), "page_lifetime": page_lifetime()}, indent=2))
