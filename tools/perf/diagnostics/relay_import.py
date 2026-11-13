"""Read-only adapter for maas-go-relay-export-1.0. No runtime or model execution."""

from collections import Counter
from pathlib import Path
from uuid import UUID
import hashlib, json, re, subprocess

if __package__:
    from .validation import need, keys, ident, number, sha, load_json
else:
    from validation import need, keys, ident, number, sha, load_json

SOURCE_PATHS = (
    "internal/kernel/relay_forward.go",
    "internal/kernel/relay.go",
    "internal/kernel/public_response.go",
    "internal/kernel/content.go",
    "internal/kernel/relay_sample.go",
    "internal/kernel/relay_sampling_mysql_test.go",
)
TIMES = (
    "first_protocol_ms",
    "first_content_received_ms",
    "first_content_write_ok_ms",
    "first_content_flush_attempt_ms",
)
MISSING_COMPONENTS = {
    "real_higress",
    "worker",
    "gpu",
    "client_receive",
    "cross_clock_calibration",
}
MISSING_IDENTITY = {"trace_id", "experiment_ref", "cell_id"}
RESULTS = {"succeeded", "failed", "interrupted", "cancelled", "timed_out", "unknown"}


def uuid(value):
    need(isinstance(value, str), "UUID string")
    try:
        need(str(UUID(value)) == value, "canonical UUID")
    except (ValueError, AttributeError):
        need(False, "UUID")


def verify_source_files(repo, commit, hashes):
    """Read only the six fixed paths; never execute commands from a manifest."""
    for path in SOURCE_PATHS:
        result = subprocess.run(
            ["git", "-C", str(repo), "show", commit + ":" + path],
            capture_output=True,
            timeout=15,
        )
        need(result.returncode == 0, "source commit unavailable")
        need(
            hashlib.sha256(result.stdout).hexdigest() == hashes[path],
            "source file digest",
        )


def normalize(export, manifest):
    keys(
        export,
        "schema_version evidence_kind export_id instance_fixture missing_components missing_identity run_id samples",
    )
    need(export["schema_version"] == "maas-go-relay-export-1.0", "export version")
    need(
        export["evidence_kind"] == "controlled_go_http_mysql"
        and export["instance_fixture"] is False,
        "controlled Go source scope",
    )
    uuid(export["export_id"])
    ident(export["run_id"])
    for field, expected in (
        ("missing_components", MISSING_COMPONENTS),
        ("missing_identity", MISSING_IDENTITY),
    ):
        need(
            type(export[field]) is list
            and len(export[field]) == len(expected)
            and all(type(v) is str for v in export[field])
            and set(export[field]) == expected,
            "declared source limitations",
        )
    need(
        type(export["samples"]) is list and 0 < len(export["samples"]) <= 10000,
        "bounded samples",
    )
    cases = manifest["case_to_request"]
    need(
        type(cases) is dict and len(cases) == len(export["samples"]),
        "case/sample population",
    )
    for case, rid in cases.items():
        need(re.fullmatch("[a-z0-9_]{1,100}", case) is not None, "case label")
        uuid(rid)
    need(len(set(cases.values())) == len(cases), "case mapping bijection")
    inverse = {v: k for k, v in cases.items()}
    rows = []
    seen = set()
    for s in export["samples"]:
        keys(
            s,
            "schema_version run_id request_id instance_id boot_id clock_scope source_revision publication_id release_revision first_protocol_ms first_content_received_ms first_content_write_ok_ms first_content_flush_attempt_ms end_ms result return_error",
        )
        need(
            s["schema_version"] == "maas-go-relay-source-1.0"
            and s["run_id"] == export["run_id"],
            "sample version/run",
        )
        for field in ("request_id", "instance_id", "boot_id", "publication_id"):
            uuid(s[field])
        rid = s["request_id"]
        need(rid not in seen and rid in inverse, "duplicate/unmapped request")
        seen.add(rid)
        need(
            s["clock_scope"]
            == "/".join(s[k] for k in ("instance_id", "boot_id", "request_id")),
            "per-request Forward clock identity",
        )
        sha(s["release_revision"])
        ident(s["source_revision"])
        end = number(s["end_ms"])
        for field in TIMES:
            if s[field] is not None:
                need(number(s[field]) <= end, "milestone after Forward end")
        protocol, content, write, flush = [s[k] for k in TIMES]
        if content is not None:
            need(
                protocol is not None and protocol <= content, "content before protocol"
            )
        for later in (write, flush):
            if later is not None:
                need(
                    content is not None and content <= later,
                    "write/flush without received content",
                )
        if write is not None and flush is not None:
            need(write <= flush, "flush before successful Write")
        # A failed Write may still be followed by Flush(): write=null, flush=finite is legal.
        need(
            type(s["return_error"]) is bool and s["result"] in RESULTS, "source result"
        )
        need(
            s["result"] != "succeeded" or not s["return_error"],
            "succeeded with returned error",
        )
        rows.append(
            {
                "source_case": inverse[rid],
                **s,
                "observed_result": s["result"],
                "terminal_result": None,
                "terminal_schema_version": None,
                "invocation_binding": None,
                "trace_id": None,
                "client_visible_ttft_ms": None,
                "client_clock_scope": None,
                "go_legacy_first_chunk_ms": None,
                "actual_usage": None,
                "current_token_ledger": None,
                "slot_recovery_state": "unknown_without_independent_observation",
                "content_received_to_write_ok_ms": (
                    None if write is None else write - content
                ),
                "source_revision_is_capture_commit_proof": False,
            }
        )
    return rows


def build_report(
    raw_path,
    manifest_path,
    expected_manifest_sha256,
    expected_source_commit,
    source_repo=None,
):
    sha(expected_manifest_sha256)
    need(
        isinstance(expected_source_commit, str)
        and re.fullmatch("[a-f0-9]{40}", expected_source_commit),
        "source commit",
    )
    manifest, manifest_hash = load_json(manifest_path)
    need(manifest_hash == expected_manifest_sha256, "manifest digest")
    keys(
        manifest,
        "source_commit_at_manifest source_worktree_dirty source_sha256 raw_file raw_sha256 collection_command case_to_request dropped_case component_scope unknown consumer_commit direct_diagnostic_sidecar_import_ready",
    )
    need(
        manifest["source_commit_at_manifest"] == expected_source_commit,
        "delivery commit",
    )
    need(
        manifest["source_worktree_dirty"] is False
        and manifest["direct_diagnostic_sidecar_import_ready"] is False,
        "pinned source manifest scope",
    )
    need(
        type(manifest["source_sha256"]) is dict
        and set(manifest["source_sha256"]) == set(SOURCE_PATHS),
        "source path allowlist",
    )
    for digest in manifest["source_sha256"].values():
        sha(digest)
    sha(manifest["raw_sha256"])
    need(
        manifest["raw_file"] == "artifacts/go-relay-d1.json"
        and manifest["collection_command"] == "bash scripts/collect-relay-d1.sh",
        "source command/version",
    )
    need(
        isinstance(manifest["consumer_commit"], str)
        and re.fullmatch("[a-f0-9]{40}", manifest["consumer_commit"]),
        "consumer revision",
    )
    need(
        manifest["dropped_case"]
        == "full_sampler (one additional execution, no exported summary)",
        "drop scenario",
    )
    need(
        manifest["component_scope"]
        == "Go Relay + temporary MySQL + controlled HTTP upstream; gateway proofs are test adapters",
        "component scope",
    )
    need(
        type(manifest["unknown"]) is list
        and set(manifest["unknown"])
        == {
            "client receive",
            "real Higress",
            "Worker",
            "GPU",
            "trace_id",
            "experiment_ref",
            "cell_id",
            "cross-clock calibration",
        }
        and len(manifest["unknown"]) == 8,
        "manifest limitations",
    )
    export, raw_hash = load_json(raw_path)
    need(raw_hash == manifest["raw_sha256"], "raw export digest")
    rows = normalize(export, manifest)
    if source_repo is not None:
        verify_source_files(
            source_repo, expected_source_commit, manifest["source_sha256"]
        )
    here = Path(__file__).parent
    assets = json.loads((here / "assets.json").read_text(encoding="utf-8"))["assets"]
    stages = json.loads((here / "collection-map.json").read_text(encoding="utf-8"))[
        "stages"
    ]
    counts = {
        "exported_summary_records": len(rows),
        "unique_requests": len(rows),
        "observed_source_results": dict(Counter(r["observed_result"] for r in rows)),
        "source_declared_additional_drop_scenarios": 1,
        "source_declared_scenario_execution_count": len(rows) + 1,
        "source_declared_summary_coverage": {
            "known": len(rows),
            "denominator": len(rows) + 1,
            "ratio": len(rows) / (len(rows) + 1),
            "basis": "manifest case mapping plus one additional full_sampler execution; NOT client sent or global drop counter",
        },
        "source_milestone_coverage": {
            field: {
                "known": sum(r[field] is not None for r in rows),
                "denominator": len(rows),
                "ratio": sum(r[field] is not None for r in rows) / len(rows),
                "scope": "exported summaries only; missing may be no-content, not collector loss",
            }
            for field in TIMES
        },
        "actual_usage_missing_records": len(rows),
        "held_missing_records": len(rows),
        "recovery_unobserved_non_success_records": sum(
            r["result"] != "succeeded" for r in rows
        ),
        "complete_client_sent": None,
        "rejected_not_exported": None,
        "pending_not_exported": None,
        "global_sampler_dropped_counter": None,
        "drop_rate": None,
    }
    source_files = [
        {"artifact_ref": "go-relay-d1.json", "sha256": raw_hash},
        {"artifact_ref": "go-relay-d1-manifest.json", "sha256": manifest_hash},
    ]
    gaps = [
        (
            "client.roster",
            "MAAS-10/MAAS-3",
            "no complete client sent/failure/refusal/pending roster or receive timestamps",
        ),
        (
            "identity.binding",
            "MAAS-3/MAAS-2",
            "publication/release only; full invocation binding, trace, experiment/cell/replicate absent",
        ),
        (
            "clock.calibration",
            "MAAS-8/MAAS-2",
            "per-request Forward origins; neither common client window nor cross-process mapping",
        ),
        (
            "business.ledger",
            "MAAS-3/MAAS-7",
            "no terminal ledger, held timeline or independently observed slot/resource recovery in this export",
        ),
        (
            "sampling.overhead",
            "MAAS-3/MAAS-10",
            "full-queue offer microbenchmark is not sampled/unsampled whole hot-path overhead or global drop counter",
        ),
        ("platform.path", "MAAS-3/MAAS-8", "real Higress, Worker and GPU absent"),
    ]
    diagnostics = [
        {
            "request_id": r["request_id"],
            "result": r["observed_result"],
            "client_protocol_data_wait_ms": None,
            "client_visible_ttft_ms": None,
            "go_server_first_chunk_ms": None,
            "go_forward_first_content_received_ms": r["first_content_received_ms"],
            "worker_native_ttft_ms": None,
            "interval_count": 0,
        }
        for r in rows
    ]
    return {
        "report_version": "d1-import-report-1.0",
        "synthetic": True,
        "evidence_kind": "actual_Go_controlled_HTTP_MySQL_source_export_consumed_not_rerun",
        "authority": "diagnostic_only_no_admission_settlement_refund_or_device_close_proof",
        "metric_report": None,
        "source_counts": counts,
        "source_rows": rows,
        "source_import": {
            "format": "maas-go-relay-export-1.0",
            "product_commit": expected_source_commit,
            "input_manifest_sha256": manifest_hash,
            "source_files": source_files,
            "source_files_verified_against_delivery_commit": source_repo is not None,
            "source_sha256": manifest["source_sha256"],
            "sampled_source_revisions": sorted({r["source_revision"] for r in rows}),
            "capture_commit_attested": False,
            "capture_revision_note": "working-tree-d1 preserved; clean delivery commit verified after capture is not runtime commit attestation",
            "source_execution": "backend reported actual Go + temporary MySQL + controlled HTTP; consumer did not rerun Go",
            "actual_components_reported": [
                "Go Relay.Forward",
                "temporary MySQL",
                "controlled HTTP upstream",
            ],
            "fixtures_not_real_components": [
                "Higress proofs/gate adapters",
                "controlled upstream payloads",
            ],
            "not_exercised": export["missing_components"],
            "instance_boot_scope": "actual local sampler IDs, not production registry or Worker boot",
            "latency_scope": "controlled tests inject 35/60ms delays; not a representative platform/model baseline",
            "clock_origin": "Forward entry=0 per request; legacy terminal first_chunk uses Received origin and is NOT imported here",
            "content_semantics": "first valid nonempty delta.content receive before diagnostic DB/write",
            "write_semantics": "complete Write returned nil error; not client receive",
            "flush_semantics": "Flusher.Flush attempted; not ACK; valid even when Write failed",
            "source_collection_command": manifest["collection_command"],
            "sampling_overhead_scope": "external full-queue offer microbenchmark only; whole-path sampled/unsampled pair missing",
            "source_sampled_vs_unsampled_baseline": None,
            "consumer_overhead_location": "consumer-import-overhead.json",
        },
        "source_complete_sent": None,
        "observation_window": None,
        "rates": None,
        "goodput": None,
        "d1_overall_complete": False,
        "e1_executed": False,
        "real_execution_enabled": False,
        "benchmark_comparable": False,
        "benchmark_blockers": [g[2] for g in gaps],
        "dataset_sha256": None,
        "sidecar_sha256": None,
        "registry": None,
        "protocols": {"ticket": 3, "terminal": "3.0", "observation": "1.0"},
        "asset_inventory": assets,
        "request_diagnostics": diagnostics,
        "coverage_by_stage": [
            {
                "stage": s["id"],
                "owner": s["owner"],
                "known_requests": 0,
                "denominator": None,
                "coverage": None,
                "existing_metric_only_requests": (
                    len(rows) if s["id"] == "go.request" else 0
                ),
                "combined_measurement_coverage": None,
                "source": s["source"],
                "scope": "exported Go milestones only; eligible population unknown",
            }
            for s in stages
        ],
        "collection_gaps": [
            {
                "stage": stage,
                "owner": owner,
                "missing_requests": None,
                "reason": reason,
                "next_input": reason,
            }
            for stage, owner, reason in gaps
        ],
        "manifest_missing": [
            "complete_client_sent_roster",
            "trace_id",
            "full_invocation_binding",
            "experiment_ref",
            "cell_id",
            "replicate_id",
            "cross_clock_calibration",
            "sampled_unsampled_whole_path_pair",
            "global_drop_counter",
            "independent_recovery_observation",
            "confirmed_slo",
            "quality_policy",
            "real_protected_path",
        ],
        "timeline": {
            "intervals": [],
            "interval_unions": [],
            "observed_dependency_chains": [],
            "blocked_edges": [],
            "end_to_end_critical_path_ms": None,
            "model_bottleneck": None,
            "unattributed_ms": None,
            "reason": "local milestone differences retained per request; no full binding/causal spans or common time window",
        },
        "recovery_groups": [],
        "recovery_missing_request_ids": [
            r["request_id"] for r in rows if r["result"] != "succeeded"
        ],
        "sampling_overhead_source": None,
        "evidence_index": [
            dict(id="source-" + str(i), kind="controlled_export_unverified", **f)
            for i, f in enumerate(source_files)
        ],
    }
