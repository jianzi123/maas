#!/usr/bin/env python3
"""Strictly local diagnostic calculator. No authorization/accounting authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

BASE = Path(__file__).resolve().parent
TIMES = ("server_first_chunk_ms", "client_visible_ttft_ms",
         "client_scheduled_ttft_ms", "model_native_ttft_ms",
         "client_e2e_ms", "tpot_ms", "chunk_gap_ms")


class InputError(ValueError):
    """Safe error text must never include request bodies or schema values."""


def fail(condition, message):
    if not condition:
        raise InputError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def keys(obj, expected, label):
    fail(isinstance(obj, dict) and set(obj) == set(expected.split()), label)


def load_json(path):
    def pairs(items):
        obj = {}
        for key, value in items:
            fail(key not in obj, "duplicate JSON object key")
            obj[key] = value
        return obj
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"),
                          object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              InputError("nonfinite JSON number")))
    except (ValueError, OSError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("cannot read valid UTF-8 JSON") from None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def unique(records, field, label):
    fail(isinstance(records, list), "expected record array")
    result, duplicates = {}, 0
    for row in records:
        fail(isinstance(row, dict) and field in row, label)
        ident = row[field]
        fail(isinstance(ident, str), label)
        if ident in result:
            fail(canonical(result[ident]) == canonical(row), "conflicting " + label)
            duplicates += 1
        else:
            result[ident] = row
    return result, duplicates


def contract(name, definition=None):
    schema = load_json(BASE / "contracts" / name)
    def refs(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref":
                    fail(isinstance(value, str) and value.startswith("#/"),
                         "external schema reference forbidden")
                refs(value)
        elif isinstance(node, list):
            for item in node:
                refs(item)
    refs(schema)
    if definition:
        schema = dict(schema, **{"$ref": "#/$defs/" + definition})
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate(validator, record, label):
    fail(validator.is_valid(record), "invalid " + label + " contract")


def distribution(values, denominator):
    values = sorted(v for v in values if v is not None)
    def quantile(q):
        if not values:
            return None
        index = (len(values) - 1) * q
        lo, hi = math.floor(index), math.ceil(index)
        return values[lo] + (values[hi] - values[lo]) * (index - lo)
    return {"count": len(values), "denominator": denominator,
            "missing": denominator - len(values),
            "coverage": len(values) / denominator if denominator else None,
            "p50": quantile(.5), "p95": quantile(.95),
            "quantile_method": "linear_interpolation_n_minus_1",
            "tail_evidence": "descriptive_only" if len(values) < 200 else
            "sample_count_only_no_precision_guarantee"}


def sse_metrics(frames):
    """Frames are timestamped wire fragments, not assumed token boundaries."""
    buffer, contents, done, error, last_frame = "", [], False, False, None
    for frame in frames:
        keys(frame, "at_ms wire", "invalid SSE frame")
        fail(number(frame["at_ms"]) and isinstance(frame["wire"], str),
             "invalid SSE frame")
        fail(last_frame is None or frame["at_ms"] >= last_frame, "unordered SSE")
        last_frame = frame["at_ms"]
        buffer += frame["wire"]
        buffer = buffer.replace("\r\n", "\n")
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            payload, event = [], ""
            for line in block.split("\n"):
                if line.startswith(":"):
                    continue
                field, _, value = line.partition(":")
                if value.startswith(" "):
                    value = value[1:]
                if field == "data":
                    payload.append(value)
                if field == "event":
                    event = value
            if not payload and event != "error":
                continue
            fail(not done, "SSE data after DONE")
            data = "\n".join(payload)
            if event == "error":
                error = True
                continue
            if data == "[DONE]":
                done = True
                continue
            try:
                obj = json.loads(data)
            except (ValueError, TypeError):
                raise InputError("invalid SSE JSON") from None
            fail(isinstance(obj, dict), "invalid SSE object")
            if "error" in obj:
                error = True
            choices = obj.get("choices", [])
            fail(isinstance(choices, list), "invalid SSE choices")
            for choice in choices:
                fail(isinstance(choice, dict), "invalid SSE choice")
                delta = choice.get("delta", {})
                fail(isinstance(delta, dict), "invalid SSE delta")
                text = delta.get("content")
                fail(text is None or isinstance(text, str), "invalid content delta")
                if text and not error:
                    # One observation per event even if it has multiple choices.
                    if not contents or contents[-1] != frame["at_ms"]:
                        contents.append(frame["at_ms"])
    return {"content_times": contents, "done": done, "error": error,
            "truncated": bool(buffer.strip())}


def analyze(dataset):
    def finite_tree(value):
        if isinstance(value, float):
            fail(math.isfinite(value), "nonfinite number")
        elif isinstance(value, dict):
            for item in value.values():
                finite_tree(item)
        elif isinstance(value, list):
            for item in value:
                finite_tree(item)
    finite_tree(dataset)
    keys(dataset, "schema_version synthetic protocols window registry requests "
         "observations terminals runtime_metadata gateway_observations slo",
         "invalid dataset fields")
    fail(dataset["schema_version"] == "1.0" and type(dataset["synthetic"]) is bool,
         "unsupported dataset version")
    fail(dataset["protocols"] == {"ticket": 3, "terminal": "3.0", "observation": "1.0"} and
         type(dataset["protocols"]["ticket"]) is int,
         "unsupported protocol versions; no implicit downgrade")
    window, registry = dataset["window"], dataset["registry"]
    keys(window, "start_ms end_ms", "invalid measurement window")
    fail(number(window["start_ms"]) and number(window["end_ms"]) and
         window["end_ms"] > window["start_ms"], "invalid measurement window")
    keys(registry, "experiment_ref run_id cell_id replicate", "invalid run registry")
    fail(type(registry["replicate"]) is int and registry["replicate"] >= 1,
         "invalid replicate")
    for name in ("run_id", "cell_id"):
        fail(isinstance(registry[name], str) and
             re.fullmatch(r"[A-Za-z0-9._-]{1,128}", registry[name]), "invalid registry")
    slo = dataset["slo"]
    if slo is not None:
        keys(slo, "ttft_ms tpot_ms e2e_ms", "invalid SLO")
        fail(all(number(x) for x in slo.values()), "invalid SLO")
    reqs, dup_r = unique(dataset["requests"], "request_id", "request record")
    obs, dup_o = unique(dataset["observations"], "observation_id", "observation record")
    terminals, dup_t = unique(dataset["terminals"], "event_id", "terminal record")
    runtime, dup_m = unique(dataset["runtime_metadata"], "id", "runtime record")
    gateway, dup_g = unique(dataset["gateway_observations"], "id", "gateway record")
    obs_v = contract("observation.schema.json")
    runtime_v = contract("observation.schema.json", "RuntimeMetadata")
    gateway_v = contract("observation.schema.json", "GatewayObservation")
    terminal_v = contract("terminal.schema.json")
    by_req, terminal_by_req = defaultdict(list), {}
    for item in obs.values():
        validate(obs_v, item, "observation")
        fail(item["experiment_ref"] == registry["experiment_ref"], "experiment mismatch")
        fail(set(item["timing"]["missing_fields"]) ==
             {key for key in TIMES if item["timing"][key] is None},
             "timing missing_fields mismatch")
        for stage in item["stages"]:
            fail((stage["duration_ms"] is not None) ==
                 (stage["provenance"] == "measured"), "stage provenance mismatch")
        if item["event_type"] == "request.observation":
            fail(item["request_id"] in reqs, "orphan observation")
            by_req[item["request_id"]].append(item)
    for item in runtime.values():
        validate(runtime_v, item, "runtime metadata")
    for item in gateway.values():
        validate(gateway_v, item, "gateway observation")
    for item in terminals.values():
        validate(terminal_v, item, "terminal 3.0")
        rid = item["request_id"]
        fail(rid in reqs and rid not in terminal_by_req,
             "orphan or multiple terminal identities for request")
        terminal_by_req[rid] = item
        usage = item["usage"]
        i, o, total = (usage[key] for key in ("input_tokens", "output_tokens", "total_tokens"))
        if None not in (i, o, total):
            fail(i + o == total, "usage total mismatch")
        for subset, parent in (("input_cached_tokens", i), ("reasoning_tokens", o)):
            if usage[subset] is not None and parent is not None:
                fail(usage[subset] <= parent, "usage subset mismatch")
        accounting = item["budget_accounting"]
        for dim in ("request", "token", "money"):
            values = accounting[dim]
            if values is not None:
                fail(int(values["reserved"]) + int(values["overrun"]) ==
                     sum(int(values[k]) for k in ("known_used", "unknown_held", "released")),
                     "accounting conservation mismatch")
        binding = item["invocation_binding"]
        plan = item["reservation_plan"]
        fail(all(item[k] == plan[k] for k in ("source_id", "model_alias", "config_revision")),
             "reservation source/config mismatch")
        fail(plan["currency"] == accounting["currency"], "accounting currency mismatch")
        if accounting["token_actual"] is not None:
            expected_total = total if total is not None else (
                i + o if i is not None and o is not None else None)
            fail(expected_total is not None and int(accounting["token_actual"]) == expected_total,
                 "known token accounting mismatch")
        for snapshot in (item["reservation_plan"], accounting):
            fail(all(binding[k] == snapshot[k] for k in ("price_snapshot_id", "price_version")),
                 "price snapshot mismatch")
    rows, counts, stages = [], Counter(), defaultdict(list)
    # The batch window has one client monotonic coordinate system. Matching
    # each request to its own observation alone does not establish this.
    client_clock_scope = None
    for rid, request in reqs.items():
        keys(request, "request_id scheduled_ms sent_ms end_ms stream transport_result "
             "quality_pass visible_tokens tokenizer_sha256 engine_token_times_ms "
             "engine_clock_scope clock_scope frames rejection_code", "invalid request fields")
        fail(number(request["sent_ms"]) and number(request["scheduled_ms"]) and
             window["start_ms"] <= request["scheduled_ms"] <= request["sent_ms"] <= window["end_ms"],
             "request outside measurement window")
        end = request["end_ms"]
        fail(end is None or (number(end) and request["sent_ms"] <= end <= window["end_ms"]),
             "invalid termination time")
        fail(type(request["stream"]) is bool and (type(request["quality_pass"]) is bool or request["quality_pass"] is None),
             "invalid request flags")
        fail(request["rejection_code"] is None or
             isinstance(request["rejection_code"], str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", request["rejection_code"]), "invalid rejection code")
        fail(isinstance(request["clock_scope"], str) and request["clock_scope"],
             "invalid request clock scope")
        observations = by_req[rid]
        clients = [v for v in observations if v["producer"] == "client"]
        fail(len(clients) == 1, "requires one full-coverage client observation per request")
        client = clients[0]
        fail(client["sampling_fraction"] == 1 and
             client["clock_scope"] == request["clock_scope"], "client coverage/clock mismatch")
        if client_clock_scope is None:
            client_clock_scope = request["clock_scope"]
        fail(request["clock_scope"] == client_clock_scope,
             "mixed client clock scopes for common measurement window")
        disposition, binding = client["disposition"], client["invocation_binding"]
        terminal = terminal_by_req.get(rid)
        fail(disposition in ("admitted", "not_admitted"), "unknown admission disposition")
        if disposition == "not_admitted":
            fail(binding is None and terminal is None and client["outcome"] == "rejected" and
                 end is not None and request["rejection_code"] is not None, "invalid rejection")
            result = "rejected"
        else:
            fail(binding is not None, "admitted request missing binding")
            if terminal is None:
                fail(end is None and client["outcome"] == "pending", "missing terminal for ended request")
                result = "pending"
            else:
                fail(binding == terminal["invocation_binding"] and
                     client["terminal_event_ref"] == terminal["event_id"], "terminal revision/ref mismatch")
                result = terminal["result"]
                fail(end is not None, "terminal request has no termination time")
                expected = {"succeeded": "ok", "cancelled": "cancelled"}.get(result, "error")
                fail(client["outcome"] == expected, "terminal/outcome mismatch")
        for observation in observations:
            fail(observation["invocation_binding"] == binding and
                 observation["disposition"] == disposition, "request revision mismatch")
            if binding:
                fail(observation["cr_uid"] == binding["model_release_uid"] and
                     observation["active_revision"] == binding["release_revision"],
                     "observation active revision mismatch")
            meta = runtime.get(observation["runtime_metadata_ref"])
            fail(observation["runtime_metadata_ref"] is None or meta is not None,
                 "missing runtime metadata")
            if meta is not None:
                fail(binding is not None and meta["publication_id"] == binding["publication_id"],
                     "runtime publication mismatch")
            gate = gateway.get(observation["gateway_observation_ref"])
            fail(observation["gateway_observation_ref"] is None or gate is not None,
                 "missing gateway observation")
            if gate is not None:
                fail(binding is not None and gate["request_id"] == rid and
                     all(gate[k] == binding[k] for k in ("publication_id", "route_binding_sha256")),
                     "gateway binding mismatch")
            for stage in observation["stages"]:
                stages[stage["name"]].append(stage["duration_ms"])
        fail(isinstance(request["frames"], list), "invalid SSE frames")
        parsed = sse_metrics(request["frames"])
        for frame in request["frames"]:
            fail(request["sent_ms"] <= frame["at_ms"] <= (end if end is not None else window["end_ms"]),
                 "SSE outside request")
        transport = request["transport_result"]
        fail(transport in ("complete", "raw_eof", "error", "cancelled", "pending", "rejected"),
             "invalid transport result")
        if request["stream"]:
            if result == "succeeded":
                fail(transport == "complete" and parsed["done"] and not parsed["error"] and
                     not parsed["truncated"], "success without complete SSE")
            else:
                fail(not parsed["done"] or parsed["error"], "non-success with normal DONE")
                fail(not parsed["content_times"] or result != "rejected", "content on rejected request")
        else:
            fail(not request["frames"], "nonstream record contains SSE")
            if result == "succeeded":
                fail(transport == "complete", "nonstream success without complete response")
        fail((result == "pending") == (transport == "pending") and
             (result == "rejected") == (transport == "rejected"), "transport/result mismatch")
        content = parsed["content_times"] if request["stream"] else []
        n = request["visible_tokens"]
        fail(n is None or (type(n) is int and 0 <= n <= 9007199254740991), "invalid visible token count")
        meta = runtime.get(client["runtime_metadata_ref"])
        if n is not None:
            fail(meta is not None and meta["tokenizer_sha256"] is not None and
                 request["tokenizer_sha256"] == meta["tokenizer_sha256"], "unfrozen tokenizer count")
            fail(bool(content) == (n > 0) or not request["stream"], "token/content mismatch")
        engine_times = request["engine_token_times_ms"]
        engine_tpot = None
        if engine_times is not None:
            fail(isinstance(engine_times, list) and all(number(t) for t in engine_times) and
                 engine_times == sorted(engine_times) and
                 isinstance(request["engine_clock_scope"], str) and request["engine_clock_scope"],
                 "invalid engine token timing")
            if len(engine_times) >= 2:
                engine_tpot = (engine_times[-1] - engine_times[0]) / (len(engine_times) - 1)
        ttft = content[0] - request["sent_ms"] if content else None
        scheduled_ttft = content[0] - request["scheduled_ms"] if content else None
        proxy = (content[-1] - content[0]) / (n - 1) if content and n is not None and n >= 2 else None
        e2e = end - request["sent_ms"] if result == "succeeded" else None
        timing = client["timing"]
        for name, actual in (("client_visible_ttft_ms", ttft),
                             ("client_scheduled_ttft_ms", scheduled_ttft),
                             ("client_e2e_ms", e2e)):
            reported = timing[name]
            fail(reported is None or (actual is not None and math.isclose(reported, actual)),
                 "reported client timing mismatch")
        if timing["tpot_ms"] is not None:
            fail(timing["tpot_scope"] in ("visible_proxy", "engine_generated"),
                 "invalid TPOT scope")
            expected_count = n if timing["tpot_scope"] == "visible_proxy" else (
                len(engine_times) if engine_times is not None else None)
            fail(timing["token_sample_count"] == expected_count, "TPOT sample count mismatch")
            actual = proxy if timing["tpot_scope"] == "visible_proxy" else engine_tpot
            fail(actual is not None and math.isclose(actual, timing["tpot_ms"]), "reported TPOT mismatch")
        if terminal and timing["server_first_chunk_ms"] is not None:
            fail(timing["server_first_chunk_ms"] == terminal["first_chunk_ms"], "server first chunk mismatch")
        success = result == "succeeded"
        eligible = success and ttft is not None and e2e is not None and \
            request["quality_pass"] is not None and (n == 1 or proxy is not None)
        good = None if slo is None or not eligible else (
            request["quality_pass"] and ttft <= slo["ttft_ms"] and e2e <= slo["e2e_ms"] and
            (n == 1 or proxy <= slo["tpot_ms"]))
        counts[result] += 1
        rows.append({"request_id": rid, "result": result, "rejection_code": request["rejection_code"],
                     "invocation_binding": binding,
                     "runtime_metadata_ref": client["runtime_metadata_ref"],
                     "server_first_chunk_ms": timing["server_first_chunk_ms"],
                     "model_native_ttft_ms": timing["model_native_ttft_ms"],
                     "client_visible_ttft_ms": ttft, "client_scheduled_ttft_ms": scheduled_ttft,
                     "client_e2e_ms": e2e, "termination_ms": end - request["sent_ms"] if end is not None else None,
                     "visible_tpot_proxy_ms": proxy, "engine_generated_tpot_ms": engine_tpot,
                     "chunk_gap_ms": [b - a for a, b in zip(content, content[1:])],
                     "goodput_eligible": eligible, "within_slo_and_quality": good})
    sent = len(reqs)
    admitted = sent - counts["rejected"]
    duration = (window["end_ms"] - window["start_ms"]) / 1000
    def usage_summary(field):
        values = [t["usage"][field] for t in terminals.values()]
        known = [v for v in values if v is not None]
        total = sum(known) if known else None
        return {"known_sum": total, "known_requests": len(known),
                "missing_admitted": admitted - len(known),
                "coverage": len(known) / admitted if admitted else None,
                "known_per_second": total / duration if total is not None else None}
    groups = defaultdict(list)
    for row in rows:
        b = row["invocation_binding"]
        group = canonical(b) if b else "unbound_rejections"
        groups[group].append(row["request_id"])
    def metric_report(subset):
        return {key: distribution([r[key] for r in subset], len(subset)) for key in
                ("client_visible_ttft_ms", "client_e2e_ms", "termination_ms",
                 "visible_tpot_proxy_ms", "engine_generated_tpot_ms")}
    good_count = sum(r["within_slo_and_quality"] is True for r in rows)
    held = {dim: str(sum(int(t["budget_accounting"][dim]["unknown_held"])
                         for t in terminals.values() if t["budget_accounting"][dim] is not None))
            for dim in ("request", "token")}  # money is grouped by currency/price, never mixed
    money = defaultdict(list)
    for terminal in terminals.values():
        a = terminal["budget_accounting"]
        money[(a["currency"], a["price_snapshot_id"], a["price_version"])].append(a)
    return {"report_version": "1.0", "synthetic": dataset["synthetic"],
            "evidence_kind": "synthetic_fixture_calculation" if dataset["synthetic"] else "offline_import_unverified",
            "authority": "diagnostic_only_no_admission_settlement_refund_or_close_proof",
            "protocols": dataset["protocols"], "registry": registry, "window": window,
            "counts": {"sent": sent, "admitted": admitted, **{k: counts[k] for k in
                ("succeeded", "failed", "cancelled", "timed_out", "interrupted", "pending", "rejected")}},
            "rates": {"success_rps": counts["succeeded"] / duration,
                      "technical_error_over_sent": sum(counts[k] for k in ("failed", "timed_out", "interrupted")) / sent if sent else None,
                      "rejection_over_sent": counts["rejected"] / sent if sent else None,
                      "admitted_nonsuccess_over_admitted": sum(counts[k] for k in
                          ("failed", "cancelled", "timed_out", "interrupted")) / admitted if admitted else None},
            "goodput": {"slo": slo, "eligible": sum(r["goodput_eligible"] for r in rows),
                        "count": good_count if slo is not None else None,
                        "rps": good_count / duration if slo is not None else None,
                        "pass_over_sent": good_count / sent if sent and slo is not None else None},
            "distributions": {"all_sent_observed": metric_report(rows),
                              "success": metric_report([r for r in rows if r["result"] == "succeeded"])},
            "usage": {key: usage_summary(key) for key in ("input_tokens", "output_tokens", "total_tokens")},
            "diagnostic_reconciliation": {"admitted": admitted, "terminal_records": len(terminals),
                "pending": counts["pending"], "balanced": admitted == len(terminals) + counts["pending"],
                "unknown_held_not_actual": held,
                "money_by_frozen_price": [{"currency": key[0], "price_snapshot_id": key[1], "price_version": key[2],
                    "known_sum_atomic": str(sum(int(v["cost_actual_atomic"]) for v in vals if v["cost_actual_atomic"] is not None))
                        if any(v["cost_actual_atomic"] is not None for v in vals) else None,
                    "known_requests": sum(v["cost_actual_atomic"] is not None for v in vals),
                    "unknown_held_atomic": str(sum(int(v["money"]["unknown_held"]) for v in vals if v["money"] is not None))}
                    for key, vals in sorted(money.items(), key=lambda x: str(x[0]))],
                "limitation": "observed snapshot only; no database or slot release verified"},
            "duplicates_ignored": dup_r + dup_o + dup_t + dup_m + dup_g,
            "revision_groups": [{"invocation_binding": None if key == "unbound_rejections" else json.loads(key),
                                 "request_ids": value} for key, value in sorted(groups.items())],
            "stages_inclusive_only": {key: distribution(vals, len(vals)) for key, vals in sorted(stages.items())},
            "unattributed_ms": None, "inclusive_stage_sum_ms": None,
            "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        fail(args.input.resolve() != args.output.resolve(), "output cannot overwrite input")
        dataset = load_json(args.input)
        report = analyze(dataset)
        report["input_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False,
                                          allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    except (InputError, OSError):
        # Input may contain sensitive values; don't print exception/schema/SSE content.
        print("offline analysis rejected invalid input or inaccessible local file", file=sys.stderr)
        return 2
    print("synthetic fixture report written" if report["synthetic"] else
          "unverified offline diagnostic report written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
