"""Read-only consumer for the existing pinned MAAS-7 Go/MySQL evidence archive.

No source instrumentation, Go execution, network or fabricated Observation records.
"""

from collections import Counter
from pathlib import Path
import hashlib, json, re, zipfile
from datetime import datetime

if __package__:
    from .validation import DiagnosticError, need, keys, canonical_sha, sha
else:
    from validation import DiagnosticError, need, keys, canonical_sha, sha
from analyze import contract, validate as contract_validate, distribution
from jsonschema import Draft202012Validator, FormatChecker

PRIMARY = "artifacts/qa-usage-evidence.json"
RETEST = "artifacts/qa-usage-partial-retest.json"
SUMMARY = "artifacts/qa-results.json"
WITNESS = "test/qa-usage/kernel_test.go.in"
ALLOWED = (PRIMARY, RETEST, SUMMARY, WITNESS)
DIAG_FIELDS = "schema_version record_type diagnostic_id request_id owner_instance_id owner_fence sequence observed_at snapshot_sha256 invocation_binding authority usage cause"
USAGE_FIELDS = (
    "input_tokens output_tokens total_tokens input_cached_tokens reasoning_tokens"
)


def atomic(value):
    need(
        isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value) is not None,
        "atomic integer",
    )
    return int(value)


def timestamp(value):
    need(isinstance(value, str), "UTC timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DiagnosticError("timestamp") from exc
    need(result.utcoffset() is not None, "timestamp timezone")
    return result


def safe_load(data):
    need(len(data) <= 8 * 1024 * 1024, "source file size")

    def unique(pairs):
        obj = {}
        for key, value in pairs:
            need(key not in obj, "duplicate source key")
            obj[key] = value
        return obj

    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda _: need(False, "source nonfinite"),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DiagnosticError("source JSON") from exc


def read_archive(path, expected_archive_sha256, expected_source_commit):
    sha(expected_archive_sha256)
    need(
        re.fullmatch("[a-f0-9]{40}", expected_source_commit) is not None,
        "source commit",
    )
    raw = Path(path).read_bytes()
    need(
        len(raw) <= 16 * 1024 * 1024
        and hashlib.sha256(raw).hexdigest() == expected_archive_sha256,
        "archive digest",
    )
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        need(len(names) == len(set(names)), "duplicate archive member")
        wanted = (*ALLOWED, "manifest-sha256.json")
        need(all(name in names for name in wanted), "archive source files")
        need(
            all(z.getinfo(name).file_size <= 8 * 1024 * 1024 for name in wanted),
            "bounded source files",
        )
        manifest = safe_load(z.read("manifest-sha256.json"))
        need(type(manifest) is dict, "source manifest")
        contents = {}
        for name in ALLOWED:
            data = z.read(name)
            need(
                name in manifest and hashlib.sha256(data).hexdigest() == manifest[name],
                "source artifact digest",
            )
            contents[name] = data
    summary = safe_load(contents[SUMMARY])
    need(summary["product_sha"] == expected_source_commit, "product SHA mismatch")
    timestamp(summary["observed_utc"])
    primary = safe_load(contents[PRIMARY])
    retest = safe_load(contents[RETEST])
    need(
        type(primary) is list
        and type(retest) is list
        and len(primary) + len(retest) <= 1000,
        "bounded source records",
    )
    # The test source is a provenance witness of what was exercised, not a source-level sampler patch.
    witness = contents[WITNESS].decode("utf-8")
    need(
        "relay.Forward(" in witness
        and "ReadDiagnostics(" in witness
        and "event_json FROM usage_events" in witness,
        "source execution witness",
    )
    return (
        contents,
        summary,
        [(PRIMARY, i, row) for i, row in enumerate(primary)]
        + [(RETEST, i, row) for i, row in enumerate(retest)],
    )


def usage_snapshot(value):
    keys(value, USAGE_FIELDS)
    for n in value.values():
        need(n is None or type(n) is int and n >= 0, "diagnostic usage integer/null")
    a, b, total = value["input_tokens"], value["output_tokens"], value["total_tokens"]
    if all(v is not None for v in (a, b, total)):
        need(a + b == total, "diagnostic total")
    return dict(value)


def normalize(records):
    terminal_validator = contract("terminal.schema.json")
    schema_path = (
        Path(__file__).with_name("source-contracts")
        / "diagnostic-0.1-draft.1.schema.json"
    )
    provenance = json.loads(
        schema_path.with_name("provenance.json").read_text(encoding="utf-8")
    )
    need(
        hashlib.sha256(schema_path.read_bytes()).hexdigest() == provenance["sha256"],
        "source contract snapshot",
    )
    diagnostic_validator = Draft202012Validator(
        json.loads(schema_path.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )
    rows = []
    seen = {}
    duplicates = 0
    for artifact, index, row in records:
        keys(
            row,
            "attempts case diagnostics expected_success money passed request_id terminal tokens",
        )
        need(
            isinstance(row["case"], str)
            and re.fullmatch("[a-z0-9_]{1,100}", row["case"]) is not None,
            "case label",
        )
        need(
            type(row["passed"]) is bool and type(row["expected_success"]) is bool,
            "oracle flags",
        )
        need(
            type(row["attempts"]) is int and 0 <= row["attempts"] <= 1,
            "fixed source attempts",
        )
        terminal = row["terminal"]
        contract_validate(terminal_validator, terminal, "source terminal")
        need(row["request_id"] == terminal["request_id"], "source request mismatch")
        need(
            timestamp(terminal["received_at"])
            <= timestamp(terminal["admitted_at"])
            <= timestamp(terminal["observed_at"]),
            "source UTC ordering",
        )
        need(
            type(terminal["duration_ms"]) is int and terminal["duration_ms"] >= 0,
            "source duration",
        )
        first = terminal["first_chunk_ms"]
        need(
            first is None
            or type(first) is int
            and 0 <= first <= terminal["duration_ms"],
            "source first boundary",
        )
        binding = terminal["invocation_binding"]
        budget = terminal["budget_accounting"]
        for dimension in ("request", "token", "money"):
            value = budget[dimension]
            if value is None:
                continue
            need(
                atomic(value["reserved"]) + atomic(value["overrun"])
                == atomic(value["known_used"])
                + atomic(value["unknown_held"])
                + atomic(value["released"]),
                "terminal budget reconciliation",
            )
        for field, dimension in (("tokens", "token"), ("money", "money")):
            ledger = row[field]
            keys(ledger, "Known Reserved Held")
            for value in ledger.values():
                atomic(value)
            need(
                ledger["Known"] == budget[dimension]["known_used"]
                and ledger["Held"] == budget[dimension]["unknown_held"],
                "source ledger/terminal mismatch",
            )
            # Ledger Reserved is the CURRENT inflight value, not the terminal's ORIGINAL reservation.
        need(
            type(row["diagnostics"]) is list and len(row["diagnostics"]) <= 256,
            "bounded diagnostic records",
        )
        receipt_ids = set()
        sequence = 0
        snapshots = []
        causes = []
        for d in row["diagnostics"]:
            keys(d, DIAG_FIELDS)
            contract_validate(diagnostic_validator, d, "source diagnostic")
            need(
                d["schema_version"] == "0.1-draft.1"
                and d["authority"] == "diagnostic_only",
                "diagnostic version/authority",
            )
            need(d["record_type"] in ("receipt", "termination"), "diagnostic type")
            need(
                d["request_id"] == row["request_id"]
                and d["invocation_binding"] == binding
                and d["owner_instance_id"] == terminal["owner_instance_id"]
                and d["owner_fence"] == terminal["owner_fence"],
                "diagnostic identity/revision",
            )
            need(d["diagnostic_id"] not in receipt_ids, "duplicate source diagnostic")
            receipt_ids.add(d["diagnostic_id"])
            need(
                type(d["sequence"]) is int and d["sequence"] > sequence,
                "diagnostic sequence",
            )
            sequence = d["sequence"]
            timestamp(d["observed_at"])
            sha(d["snapshot_sha256"])
            if d["record_type"] == "receipt":
                snapshots.append(
                    {
                        "sequence": sequence,
                        "usage": usage_snapshot(d["usage"]),
                        "declared_snapshot_sha256": d["snapshot_sha256"],
                    }
                )
                need(d["cause"] is None, "receipt cause")
            else:
                need(
                    d["usage"] is None
                    and d["cause"]
                    in (
                        "normal_completion",
                        "explicit_cancel",
                        "eof",
                        "usage_conflict",
                        "deadline_exceeded",
                        "client_write_error",
                        "parse_invalid",
                        "diagnostic_limit",
                    ),
                    "termination shape",
                )
                causes.append(d["cause"])
        rid = row["request_id"]
        signature = canonical_sha(row)
        if rid in seen:
            need(seen[rid] == signature, "conflicting duplicate request export")
            duplicates += 1
            continue
        seen[rid] = signature
        rows.append(
            {
                "request_id": rid,
                "source_case": row["case"],
                "source_artifact": artifact,
                "source_record_index": index,
                "test_oracle_passed": row["passed"],
                "expected_success_in_source_test": row["expected_success"],
                "terminal_event_id": terminal["event_id"],
                "terminal_result": terminal["result"],
                "terminal_schema_version": "3.0",
                "invocation_binding": binding,
                "owner_instance_id": terminal["owner_instance_id"],
                "source_type": terminal["source_type"],
                "source_id": terminal["source_id"],
                "config_revision": terminal["config_revision"],
                "go_duration_ms": terminal["duration_ms"],
                "go_legacy_first_chunk_ms": first,
                "go_first_chunk_semantics": "unconfirmed_legacy_before_write_boundary",
                "go_first_content_write_ms": None,
                "go_clock_scope": None,
                "client_clock_scope": None,
                "client_protocol_data_wait_ms": None,
                "client_visible_ttft_ms": None,
                "client_e2e_ms": None,
                "visible_tpot_proxy_ms": None,
                "worker_native_ttft_ms": None,
                "trace_id": None,
                "source_run_id": None,
                "instance_boot_id": None,
                "actual_usage": terminal["usage"],
                "token_actual": budget["token_actual"],
                "cost_actual_atomic": budget["cost_actual_atomic"],
                "currency": budget["currency"],
                "terminal_original_token_reserved": budget["token"]["reserved"],
                "current_token_ledger": dict(row["tokens"]),
                "current_money_ledger": dict(row["money"]),
                "upstream_attempts": row["attempts"],
                "receipt_snapshots": snapshots,
                "termination_causes": causes,
                "receipt_snapshot_hash_verified": False,
                "slot_recovery_state": "unknown_without_independent_observation",
                "actual_stop_observed": None,
                "client_sent_evidence": False,
            }
        )
    return rows, duplicates


def build_report(path, expected_archive_sha256, expected_source_commit):
    contents, summary, raw = read_archive(
        path, expected_archive_sha256, expected_source_commit
    )
    rows, duplicates = normalize(raw)
    source_files = [
        {"artifact_ref": name, "sha256": hashlib.sha256(body).hexdigest()}
        for name, body in contents.items()
    ]
    source_counts = {
        "observed_terminal_records": len(rows),
        "unique_requests": len(rows),
        "source_case_labels": len({r["source_case"] for r in rows}),
        "source_test_oracle_passed": sum(r["test_oracle_passed"] for r in rows),
        "source_test_oracle_failed": sum(not r["test_oracle_passed"] for r in rows),
        "terminal_results": dict(Counter(r["terminal_result"] for r in rows)),
        "complete_client_sent": None,
        "rejected_not_exported": None,
        "pending_not_exported": None,
        "duplicates_ignored": duplicates,
    }
    assets = json.loads(
        Path(__file__).with_name("assets.json").read_text(encoding="utf-8")
    )["assets"]
    stages = json.loads(
        Path(__file__).with_name("collection-map.json").read_text(encoding="utf-8")
    )["stages"]
    evidence_index = [
        {
            "id": "source-" + str(i),
            "kind": "controlled_export_unverified",
            "artifact_ref": r["artifact_ref"],
            "sha256": r["sha256"],
        }
        for i, r in enumerate(source_files)
    ]
    gaps = [
        {
            "stage": "source.d1_export",
            "owner": "MAAS-3",
            "missing_requests": None,
            "reason": "new source-side sampler/export still in progress",
            "next_input": "versioned body-free Go exporter with first protocol/content/write-success semantics and sampling overhead",
        },
        {
            "stage": "client.roster",
            "owner": "MAAS-10/MAAS-3",
            "missing_requests": None,
            "reason": "QA durable artifact is not a full client sent roster",
            "next_input": "actual client sent/refusal/failure/pending roster with monotonic scope",
        },
        {
            "stage": "identity.boot_trace",
            "owner": "MAAS-3/MAAS-8",
            "missing_requests": len(rows),
            "reason": "source run/trace/boot absent; not fabricated",
            "next_input": "actual collector run, trace, instance boot and allowed field mapping",
        },
        {
            "stage": "clock.calibration",
            "owner": "MAAS-8/MAAS-2",
            "missing_requests": None,
            "reason": "only local duration fields; UTC is not monotonic calibration",
            "next_input": "actual monotonic scope and independently reviewable calibration",
        },
        {
            "stage": "platform.path",
            "owner": "MAAS-3/MAAS-8",
            "missing_requests": None,
            "reason": "Redis/Higress/Worker not exercised as real components",
            "next_input": "actual protected path, approved adapters and per-component evidence",
        },
    ]
    coverage = [
        {
            "stage": s["id"],
            "owner": s["owner"],
            "known_requests": 0,
            "denominator": None,
            "coverage": None,
            "existing_metric_only_requests": (
                sum(r["go_duration_ms"] is not None for r in rows)
                if s["id"] == "go.request"
                else 0
            ),
            "combined_measurement_coverage": None,
            "source": s["source"],
            "scope": "exported terminal sample only; population denominator unknown",
        }
        for s in stages
    ]
    diagnostics = [
        {
            "request_id": r["request_id"],
            "result": r["terminal_result"],
            "client_protocol_data_wait_ms": None,
            "client_visible_ttft_ms": None,
            "go_server_first_chunk_ms": r["go_legacy_first_chunk_ms"],
            "worker_native_ttft_ms": None,
            "interval_count": 0,
        }
        for r in rows
    ]
    manifest_hash = canonical_sha(source_files)
    return {
        "report_version": "d1-import-report-1.0",
        "synthetic": True,
        "evidence_kind": "source_reported_controlled_go_mysql_execution_with_synthetic_upstream",
        "authority": "diagnostic_only_no_admission_settlement_refund_or_device_close_proof",
        "metric_report": None,
        "source_counts": source_counts,
        "source_rows": rows,
        "source_import": {
            "format": "qa-usage-evidence-pinned-v1",
            "product_commit": expected_source_commit,
            "source_observed_utc": summary["observed_utc"],
            "input_manifest_sha256": manifest_hash,
            "archive_sha256": expected_archive_sha256,
            "source_files": source_files,
            "source_execution": "QA reported actual Go Relay.Forward + MySQL/DiagnosticReader; this importer did not rerun Go",
            "independent_source_execution_attestation_this_run": False,
            "actual_components_reported": [
                "Go Relay.Forward",
                "Go admission/settlement",
                "MySQL",
                "controlled httptest upstream",
                "SQL DiagnosticReader",
            ],
            "fixtures_not_real_components": [
                "Redis permit provider",
                "H1-H4/gate/evidence",
            ],
            "not_exercised": [
                "actual Higress",
                "model Worker",
                "GPU",
                "production API deployment",
            ],
            "source_collection_command": "bash test/qa-usage/run.sh at QA faf1b64 with its documented approved toolchain/temp-DB prerequisites",
            "source_sampling_overhead_ns": None,
            "source_sampled_vs_unsampled_baseline": None,
            "consumer_overhead_location": "consumer-import-overhead.json; parse/validation/composition only",
        },
        "source_complete_sent": None,
        "observation_window": None,
        "rates": None,
        "goodput": None,
        "d1_overall_complete": False,
        "e1_executed": False,
        "real_execution_enabled": False,
        "benchmark_comparable": False,
        "benchmark_blockers": [
            "D1 source exporter/sampler semantics pending",
            "full client denominator and monotonic clocks absent",
            "real protected Higress path absent",
            "SLO/quality/authorization absent",
        ],
        "dataset_sha256": None,
        "sidecar_sha256": None,
        "registry": None,
        "protocols": {"ticket": 3, "terminal": "3.0", "observation": "1.0"},
        "asset_inventory": assets,
        "request_diagnostics": diagnostics,
        "coverage_by_stage": coverage,
        "collection_gaps": gaps,
        "manifest_missing": [
            "source_run_id",
            "client_sent_roster",
            "trace_id",
            "instance_boot_id",
            "monotonic_clock_scope",
            "go_first_protocol_write_success",
            "go_first_content_write_success",
            "source_sampling_overhead",
            "confirmed_slo",
            "quality_policy",
        ],
        "timeline": {
            "intervals": [],
            "interval_unions": [],
            "observed_dependency_chains": [],
            "blocked_edges": [],
            "end_to_end_critical_path_ms": None,
            "model_bottleneck": None,
            "unattributed_ms": None,
            "reason": "terminal duration cannot be expanded into an invented interval",
        },
        "recovery_groups": [],
        "recovery_missing_request_ids": [
            r["request_id"] for r in rows if r["terminal_result"] != "succeeded"
        ],
        "go_duration_descriptive_only": distribution(
            [r["go_duration_ms"] for r in rows], len(rows)
        ),
        "sampling_overhead_source": None,
        "evidence_index": evidence_index,
    }
