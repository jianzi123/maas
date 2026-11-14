"""Compose diagnostics around the existing metric calculator without altering its format."""

from collections import defaultdict
from pathlib import Path
import json

if __package__:
    from .validation import validate, canonical_sha, first_data_event
    from .timeline import summarize
else:
    from validation import validate, canonical_sha, first_data_event
    from timeline import summarize


def compose(dataset, sidecar, dataset_sha256):
    joined = validate(dataset, sidecar, dataset_sha256)
    base = joined["base"]
    events = joined["events"]
    from runtime_metrics import recovery_summary

    timeline = summarize(events)
    by_stage = {stage: [] for stage in joined["stages"]}
    for e in events.values():
        by_stage[e["stage"]].append(e)
    source = joined["manifest"]["source_type"]
    phase = joined["manifest"]["phase"]
    rows = {r["request_id"]: r for r in base["rows"]}
    coverage = []
    gaps = []
    for stage, description in joined["stages"].items():
        applies = description["applies"]
        relevant = [
            r
            for r in rows.values()
            if applies == "all_sent"
            or applies == "admitted"
            and r["result"] != "rejected"
            or applies == "private"
            and source == "self_hosted"
            and r["result"] != "rejected"
            or applies == "external"
            and source == "external_api"
            and r["result"] != "rejected"
            or applies == "cold_only"
            and phase == "cold"
            and r["result"] != "rejected"
        ]
        ids = {r["request_id"] for r in relevant}
        observed = {
            e["request_id"] for e in by_stage[stage] if e["end_ms"] is not None
        } & ids
        metric_ids = set()
        if stage == "client.content":
            metric_ids = {
                rid for rid in ids if rows[rid]["client_visible_ttft_ms"] is not None
            }
        if stage == "client.protocol":
            metric_ids = {
                rid
                for rid in ids
                if first_data_event(joined["raw_requests"][rid]["frames"]) is not None
            }
        if stage == "client.request":
            metric_ids = {
                rid for rid in ids if joined["raw_requests"][rid]["end_ms"] is not None
            }
        known = len(observed)
        denominator = len(ids)
        coverage.append(
            {
                "stage": stage,
                "owner": description["owner"],
                "obs_mapping": description["obs"],
                "boundary": description["boundary"],
                "source": description["source"],
                "denominator": denominator,
                "known_requests": known,
                "missing_requests": denominator - known,
                "coverage": known / denominator if denominator else None,
                "coverage_scope": "complete sidecar intervals only",
                "existing_metric_only_requests": len(metric_ids - observed),
                "combined_measurement_coverage": (
                    len(metric_ids | observed) / denominator if denominator else None
                ),
                "applicability": (
                    "applicable"
                    if denominator
                    else "not_applicable_for_declared_source_or_phase"
                ),
            }
        )
        if denominator and known < denominator:
            gaps.append(
                {
                    "stage": stage,
                    "owner": description["owner"],
                    "missing_requests": denominator - known,
                    "reason": "no_complete_exported_interval; never zero-filled",
                    "next_input": description["source"],
                }
            )
    per_request = []
    for rid, r in rows.items():
        raw = joined["raw_requests"][rid]
        first = first_data_event(raw["frames"]) if raw["stream"] else None
        per_request.append(
            {
                "request_id": rid,
                "result": r["result"],
                "binding_sha256": canonical_sha(r["invocation_binding"]),
                "client_protocol_data_wait_ms": (
                    None if first is None else first - raw["sent_ms"]
                ),
                "client_visible_ttft_ms": r["client_visible_ttft_ms"],
                "go_server_first_chunk_ms": r["server_first_chunk_ms"],
                "worker_native_ttft_ms": r["model_native_ttft_ms"],
                "visible_tpot_proxy_ms": r["visible_tpot_proxy_ms"],
                "engine_generated_tpot_ms": r["engine_generated_tpot_ms"],
                "protocol_note": "client SSE data, client content, Go write and Worker token boundaries are distinct",
                "interval_count": sum(e["request_id"] == rid for e in events.values()),
                "missing_end_intervals": sum(
                    e["request_id"] == rid and e["end_ms"] is None
                    for e in events.values()
                ),
            }
        )
    recovery_groups = defaultdict(list)
    observed_recovery = set()
    for row in sidecar["recovery_observations"]:
        observed_recovery.add(row["request_id"])
        recovery_groups[(row["observer_scope"], row["cutoff_ms"])].append(row)
    recovery = []
    for (scope, cutoff), samples in sorted(recovery_groups.items()):
        records = [
            {
                k: v
                for k, v in row.items()
                if k not in ("request_id", "cutoff_ms", "evidence_ref")
            }
            for row in samples
        ]
        summary = recovery_summary(records, cutoff)
        recovery.append(
            {
                "observer_scope": scope,
                "request_ids": [r["request_id"] for r in samples],
                "evidence_refs": [r["evidence_ref"] for r in samples],
                "summary": summary,
                "observer_independence": "exporter-declared, not an authority proof",
            }
        )
    recovery_missing = [
        rid
        for rid, row in rows.items()
        if row["result"] not in ("succeeded", "rejected")
        and rid not in observed_recovery
    ]
    assets = json.loads(
        Path(__file__).with_name("assets.json").read_text(encoding="utf-8")
    )
    return {
        "asset_inventory": assets["assets"],
        "asset_inventory_scope": "availability/evidence inventory, not a rerun or current production certification",
        "report_version": "diagnostic-report-1.0",
        "synthetic": sidecar["synthetic"],
        "evidence_kind": sidecar["evidence_kind"],
        "authority": "diagnostic_only_no_admission_settlement_refund_or_device_close_proof",
        "dataset_sha256": dataset_sha256,
        "sidecar_sha256": canonical_sha(sidecar),
        "sidecar_hash_scope": "canonical_json",
        "registry": base["registry"],
        "protocols": base["protocols"],
        "metric_report": base,
        "request_diagnostics": per_request,
        "manifest_sha256": canonical_sha(sidecar["manifest"]),
        "manifest_missing": joined["manifest_missing"],
        "real_execution_enabled": False,
        "benchmark_comparable": False,
        "benchmark_blockers": [
            "approved environment/SLO/quality/resource manifest and actual collection required"
        ],
        "coverage_by_stage": coverage,
        "collection_gaps": gaps,
        "timeline": timeline,
        "evidence_index": list(joined["evidence"].values()),
        "recovery_groups": recovery,
        "recovery_missing_request_ids": recovery_missing,
        "candidate_bottleneck_cards": [
            {
                "layer": "operator/runtime/platform",
                "state": "awaiting_real_profile",
                "conclusion": None,
                "next_action": "collect correlated request/batch/rank/boot timing and profiler evidence; use single-factor comparisons",
            }
        ],
    }
