"""Rebuild only synthetic local fixtures; no requests are sent."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def uid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def wire(at, obj=None, raw=None):
    return {"at_ms": at, "wire": raw if raw is not None else
            "data: " + json.dumps(obj, separators=(",", ":")) + "\n\n"}


def content(at, text):
    return wire(at, {"choices": [{"delta": {"content": text}}]})


def build():
    source = json.loads((HERE / "source-template.json").read_text(encoding="utf-8"))
    result = {"schema_version": "1.0", "synthetic": True,
              "protocols": {"ticket": 3, "terminal": "3.0", "observation": "1.0"},
              "window": {"start_ms": 0, "end_ms": 1000},
              "registry": {"experiment_ref": uid(60), "run_id": "synthetic-run",
                           "cell_id": "fixture-boundaries", "replicate": 1},
              "requests": [], "observations": [], "terminals": [],
              "runtime_metadata": [], "gateway_observations": [],
              "slo": {"ttft_ms": 150, "tpot_ms": 40, "e2e_ms": 250}}
    for generation in (1, 2):
        result["runtime_metadata"].append({
            "id": uid(80 + generation), "publication_id": uid(10 + generation),
            "runtime_instance_id": uid(90 + generation), "observed_at": "2026-11-04T08:00:00Z",
            "state": "observed", "weights_sha256": "8" * 64, "tokenizer_sha256": "9" * 64,
            "chat_template_sha256": "a" * 64, "engine_image_digest": "sha256:" + "b" * 64,
            "engine_commit": "synthetic-engine-v1", "effective_config_sha256": str(generation) * 64,
            "profile_revision": "synthetic-profile-v1", "rank_mapping_ref": uid(70 + generation)})
    cases = [
        ("succeeded", 200, 4, [
            wire(10, {"choices": [{"delta": {"role": "assistant"}}]}),
            wire(20, raw=": heartbeat\n\n"),
            wire(50, {"choices": [], "usage": {"total_tokens": 19}}),
            wire(60, {"choices": [{"delta": {"content": ""}}]}),
            content(100, "ab"), content(180, "cd"), wire(200, raw="data: [DONE]\n\n")]),
        ("succeeded", 100, 0, [wire(40, {"choices": [], "usage": {"total_tokens": 0}}),
                               wire(100, raw="data: [DONE]\n\n")]),
        ("rejected", 50, None, []),
        ("failed", 300, None, [content(120, "x"), wire(150, raw="data: {")]),
        ("failed", 90, None, [content(60, "x"), wire(90, raw='event: error\ndata: {"error":{}}\n\n')]),
        ("cancelled", 80, None, [wire(30, raw=": heartbeat\n\n")]),
        ("succeeded", 150, 1, [content(90, "x"), wire(150, raw="data: [DONE]\n\n")]),
        ("succeeded", 600, 4, [content(400, "ab"), content(500, "cd"),
                               wire(600, raw="data: [DONE]\n\n")]),
        ("pending", None, None, [wire(100, raw=": heartbeat\n\n")]),
    ]
    for index, (status, end, n, frames) in enumerate(cases, 1):
        rid = uid(300 + index)
        admitted = status != "rejected"
        generation = 2 if index == 8 else 1
        binding = copy.deepcopy(source["terminal"]["invocation_binding"]) if admitted else None
        if binding:
            binding.update(model_release_generation=generation, publication_id=uid(10 + generation),
                           activation_epoch=generation, release_revision=("c" if generation == 1 else "e") * 64)
        transport = {"succeeded": "complete", "cancelled": "cancelled", "pending": "pending",
                     "rejected": "rejected", "failed": "raw_eof" if index == 4 else "error"}[status]
        request = {"request_id": rid, "scheduled_ms": 0, "sent_ms": 0, "end_ms": end,
                   "stream": True, "transport_result": transport, "quality_pass": True if status == "succeeded" else None,
                   "visible_tokens": n, "tokenizer_sha256": "9" * 64 if n is not None else None,
                   "engine_token_times_ms": [0, 10, 20, 60, 100, 150, 180] if index == 1 else None,
                   "engine_clock_scope": "fixture-engine-monotonic" if index == 1 else None,
                   "clock_scope": "fixture-client-monotonic", "frames": frames,
                   "rejection_code": "token_budget_exceeded" if not admitted else None}
        result["requests"].append(request)
        terminal = None
        if admitted and status != "pending":
            terminal = copy.deepcopy(source["terminal"])
            terminal.update(event_id=uid(200 + index), request_id=rid, result=status,
                            source_type="internal", invocation_binding=binding, duration_ms=end,
                            first_chunk_ms={1: 60, 4: 80, 5: 40, 7: 70, 8: 350}.get(index),
                            error_code={"failed": "upstream_protocol_error", "cancelled": "client_cancelled"}.get(status))
            terminal["received_at"] = "2026-11-04T08:00:00Z"
            terminal["admitted_at"] = "2026-11-04T08:00:00.001Z"
            terminal["observed_at"] = (datetime(2026, 11, 4, 8, tzinfo=timezone.utc) +
                                       timedelta(milliseconds=end)).isoformat().replace("+00:00", "Z")
            terminal["slot_binding"]["slot_id"] = index
            if status in ("failed", "cancelled"):
                terminal["usage"] = dict.fromkeys(("input_tokens", "output_tokens", "total_tokens",
                                                   "input_cached_tokens", "reasoning_tokens"))
                terminal["usage"].update(source="unavailable",
                    missing_reason="cancelled_before_usage" if status == "cancelled" else "not_provided")
                terminal["metering_state"] = "incomplete"
                terminal["budget_accounting"] = copy.deepcopy(source["unknown_accounting"])
            if index in (2, 7):
                i, o = (0, 0) if index == 2 else (2, 1)
                cost = i * 2000 + o * 8000
                terminal["usage"].update(input_tokens=i, output_tokens=o, total_tokens=i + o,
                                         input_cached_tokens=0, reasoning_tokens=0)
                a = terminal["budget_accounting"]
                a["token_actual"], a["cost_actual_atomic"] = str(i + o), str(cost)
                a["token"].update(known_used=str(i + o), released=str(140 - i - o))
                a["money"].update(known_used=str(cost), released=str(520000 - cost))
            result["terminals"].append(terminal)
        observation = copy.deepcopy(source["observation"])
        observation.update(observation_id=uid(100 + index), producer="client", request_id=rid,
                           experiment_ref=uid(60), trace_id=f"{index:032x}", span_id=f"{index:016x}",
                           producer_revision="synthetic-fixture-v1", clock_scope=request["clock_scope"],
                           invocation_binding=binding, cr_uid=binding["model_release_uid"] if binding else None,
                           desired_generation=2 if admitted else None, observed_generation=generation if admitted else None,
                           desired_revision="e" * 64 if admitted else None,
                           active_revision=binding["release_revision"] if binding else None,
                           runtime_metadata_ref=uid(80 + generation) if admitted else None,
                           disposition="admitted" if admitted else "not_admitted",
                           outcome={"succeeded": "ok", "failed": "error", "cancelled": "cancelled",
                                    "pending": "pending", "rejected": "rejected"}[status],
                           terminal_event_ref=terminal["event_id"] if terminal else None, stages=[])
        observation["timing"]["server_first_chunk_ms"] = terminal["first_chunk_ms"] if terminal else None
        observation["timing"]["missing_fields"] = [
            key for key, value in observation["timing"].items()
            if key.endswith("_ms") and value is None]
        if index == 1:
            observation["stages"] = [
                {"name": "higress.ext_auth", "duration_ms": 150, "provenance": "measured"},
                {"name": "mysql.admission_commit", "duration_ms": 100, "provenance": "measured"},
                {"name": "engine.prefill", "duration_ms": 70, "provenance": "measured"}]
        if admitted:
            gate = {"id": uid(500 + index), "request_id": rid, "publication_id": binding["publication_id"],
                    "gateway_binding_id": "synthetic-gateway", "gateway_instance_id": uid(65),
                    "gateway_epoch": 1, "gateway_config_revision": "synthetic-gateway-v1",
                    "route_name": "synthetic-model", "route_binding_sha256": binding["route_binding_sha256"]}
            observation["gateway_observation_ref"] = gate["id"]
            result["gateway_observations"].append(gate)
        result["observations"].append(observation)
    return result


if __name__ == "__main__":
    (HERE / "synthetic.json").write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print("synthetic local fixture regenerated; no endpoint contacted")
