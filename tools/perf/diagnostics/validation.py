"""Strict local sidecar identity and clock validation; shared protocols stay unchanged."""

from pathlib import Path
import hashlib, json, math, re, sys

PERF = Path(__file__).resolve().parents[1]
if str(PERF) not in sys.path:
    sys.path.insert(0, str(PERF))
from analyze import analyze
from analyze import InputError as InputError


class DiagnosticError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise DiagnosticError(message)


def keys(obj, expected):
    need(type(obj) is dict and set(obj) == set(expected.split()), "closed object shape")


def ident(value):
    need(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,150}", value) is not None,
        "identifier",
    )


def number(value):
    need(
        type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1e12,
        "finite nonnegative timestamp",
    )
    return value


def sha(value):
    need(
        isinstance(value, str) and re.fullmatch("[a-f0-9]{64}", value) is not None,
        "digest",
    )


def canonical_sha(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def load_json(path):
    data = Path(path).read_bytes()
    need(len(data) <= 16 * 1024 * 1024, "input limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(
                DiagnosticError("nonfinite JSON")
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DiagnosticError("JSON input") from exc
    return value, hashlib.sha256(data).hexdigest()


def first_data_event(frames):
    buffer = ""
    for frame in frames:
        buffer = (buffer + frame["wire"]).replace("\r\n", "\n")
        while "\n\n" in buffer:
            event, buffer = buffer.split("\n\n", 1)
            if any(
                line.startswith("data:") and line[5:].strip()
                for line in event.split("\n")
            ):
                return frame["at_ms"]
    return None


def validate(dataset, sidecar, dataset_hash):
    base = analyze(dataset)
    keys(
        sidecar,
        "schema_version synthetic evidence_kind dataset_sha256 registry manifest clocks mappings instances batches evidence intervals recovery_observations",
    )
    need(sidecar["schema_version"] == "diagnostic-sidecar-1.0", "sidecar version")
    need(
        type(sidecar["synthetic"]) is bool
        and sidecar["synthetic"] == dataset["synthetic"],
        "evidence flag",
    )
    need(
        sidecar["evidence_kind"]
        == (
            "synthetic_fixture"
            if sidecar["synthetic"]
            else "controlled_export_unverified"
        ),
        "evidence class",
    )
    need(sidecar["dataset_sha256"] == dataset_hash, "dataset hash join")
    need(sidecar["registry"] == dataset["registry"], "run/cell/replicate join")
    manifest = sidecar["manifest"]
    keys(
        manifest,
        "schema_version phase source_type execution_enabled model runtime hardware workload policy",
    )
    need(
        manifest["schema_version"] == "diagnostic-manifest-1.0"
        and manifest["execution_enabled"] is False,
        "disabled real plan",
    )
    need(
        manifest["phase"] in ("compile", "warmup", "cold", "steady")
        and manifest["source_type"] in ("self_hosted", "external_api", "unknown"),
        "phase/source",
    )
    sections = {
        "model": "model_alias weights_sha256 tokenizer_sha256 template_sha256 dtype quantization",
        "runtime": "framework_commit image_digest driver cuda libraries config_sha256",
        "hardware": "gpu_model gpu_count gpu_memory_bytes interconnect rank_map_ref cpu network resource_limits",
        "workload": "sequence_sha256 arrival_plan concurrency prefix_state seed deadline_rule",
        "policy": "confirmed_slo quality_policy_ref budget_price_ref resource_caps approval_ref",
    }
    for section, fields in sections.items():
        keys(manifest[section], fields)
        for value in manifest[section].values():
            need(
                value is None
                or isinstance(value, (str, int, float))
                and not isinstance(value, bool),
                "manifest scalar",
            )
            if isinstance(value, float):
                need(math.isfinite(value), "manifest finite")
    unknown = [
        section + "." + field
        for section in sections
        for field, value in manifest[section].items()
        if value is None
    ]
    need(
        type(sidecar["intervals"]) is list and len(sidecar["intervals"]) <= 2000,
        "bounded intervals",
    )
    for name in (
        "clocks",
        "mappings",
        "instances",
        "batches",
        "evidence",
        "recovery_observations",
    ):
        need(
            type(sidecar[name]) is list and len(sidecar[name]) <= 20000,
            "bounded registry",
        )
    evidence = {}
    artifact_hashes = {}
    for e in sidecar["evidence"]:
        keys(e, "id kind artifact_ref sha256")
        ident(e["id"])
        sha(e["sha256"])
        need(
            e["kind"]
            in (
                "synthetic",
                "source",
                "controlled_export_unverified",
                "calibration_declaration",
            ),
            "evidence kind",
        )
        ref = e["artifact_ref"]
        need(
            isinstance(ref, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,150}", ref) is not None
            and ".." not in ref.split("/"),
            "relative evidence",
        )
        need(
            e["artifact_ref"] not in artifact_hashes
            or artifact_hashes[e["artifact_ref"]] == e["sha256"],
            "conflicting artifact hash",
        )
        artifact_hashes[e["artifact_ref"]] = e["sha256"]
        need(e["id"] not in evidence, "duplicate evidence")
        evidence[e["id"]] = e
    instances = {}
    metas = {m["id"]: m for m in dataset["runtime_metadata"]}
    for inst in sidecar["instances"]:
        keys(inst, "id boot_id role runtime_metadata_ref runtime_instance_id rank")
        ident(inst["id"])
        ident(inst["boot_id"])
        need(
            inst["id"] not in instances
            and inst["role"] in ("client", "go", "gateway", "worker", "gpu", "release"),
            "instance",
        )
        need(
            inst["rank"] is None or type(inst["rank"]) is int and inst["rank"] >= 0,
            "rank",
        )
        meta = inst["runtime_metadata_ref"]
        if inst["role"] in ("worker", "gpu"):
            need(
                meta in metas
                and inst["runtime_instance_id"] == metas[meta]["runtime_instance_id"]
                and inst["rank"] is not None,
                "runtime instance/rank",
            )
        else:
            need(
                meta is None
                and inst["runtime_instance_id"] is None
                and inst["rank"] is None,
                "nonruntime identity",
            )
        instances[inst["id"]] = inst
    clocks = {}
    for c in sidecar["clocks"]:
        keys(c, "id instance_id boot_id kind")
        ident(c["id"])
        need(c["id"] not in clocks and c["instance_id"] in instances, "clock owner")
        need(
            c["boot_id"] == instances[c["instance_id"]]["boot_id"]
            and c["kind"] in ("monotonic", "device_event"),
            "clock boot/kind",
        )
        clocks[c["id"]] = c
    mappings = {}
    for m in sidecar["mappings"]:
        keys(
            m,
            "source target scale offset_ms max_error_ms valid_from_ms valid_to_ms evidence_ref",
        )
        need(
            m["source"] in clocks
            and m["target"] in clocks
            and m["source"] != m["target"]
            and m["source"] not in mappings,
            "mapping clocks",
        )
        need(
            type(m["scale"]) in (int, float)
            and math.isfinite(m["scale"])
            and m["scale"] > 0,
            "scale",
        )
        need(
            type(m["offset_ms"]) in (int, float) and math.isfinite(m["offset_ms"]),
            "offset",
        )
        number(m["max_error_ms"])
        number(m["valid_from_ms"])
        number(m["valid_to_ms"])
        need(m["valid_from_ms"] < m["valid_to_ms"], "calibration interval")
        need(
            m["evidence_ref"] in evidence
            and evidence[m["evidence_ref"]]["kind"]
            in ("synthetic", "calibration_declaration"),
            "calibration evidence",
        )
        mappings[m["source"]] = m
    need(
        all(m["target"] not in mappings for m in mappings.values()),
        "one-hop calibration only",
    )
    rows = {r["request_id"]: r for r in base["rows"]}
    rawreq = {r["request_id"]: r for r in dataset["requests"]}
    client = {
        o["request_id"]: o for o in dataset["observations"] if o["producer"] == "client"
    }
    batches = {}
    for b in sidecar["batches"]:
        keys(b, "id instance_id boot_id rank binding_sha256 request_ids")
        ident(b["id"])
        sha(b["binding_sha256"])
        need(b["id"] not in batches and b["instance_id"] in instances, "batch")
        inst = instances[b["instance_id"]]
        need(
            b["boot_id"] == inst["boot_id"] and b["rank"] == inst["rank"],
            "batch boot/rank",
        )
        need(
            type(b["request_ids"]) is list
            and bool(b["request_ids"])
            and len(b["request_ids"]) == len(set(b["request_ids"])),
            "batch members",
        )
        for rid in b["request_ids"]:
            need(
                rid in rows
                and canonical_sha(rows[rid]["invocation_binding"])
                == b["binding_sha256"],
                "batch revision",
            )
        batches[b["id"]] = b
    stage_map = json.loads(
        Path(__file__).with_name("collection-map.json").read_text(encoding="utf-8")
    )
    stages = {r["id"]: r for r in stage_map["stages"]}
    allowed_roles = {
        "client": ("client",),
        "go": ("go",),
        "redis": ("go",),
        "mysql": ("go",),
        "gateway": ("gateway",),
        "network": ("gateway", "client"),
        "worker": ("worker",),
        "gpu": ("gpu",),
        "release": ("release",),
        "provider": ("gateway",),
    }
    normalized = {}
    for e in sidecar["intervals"]:
        keys(
            e,
            "id request_id trace_id binding_sha256 runtime_metadata_ref stage instance_id boot_id rank batch_id clock_scope start_ms end_ms segment_kind attribution parent_id predecessors evidence_ref",
        )
        ident(e["id"])
        rid = e["request_id"]
        need(
            rid in rows and rid in client and e["id"] not in normalized,
            "request/interval",
        )
        need(e["trace_id"] == client[rid]["trace_id"], "trace join")
        need(
            e["binding_sha256"] == canonical_sha(rows[rid]["invocation_binding"]),
            "active binding join",
        )
        need(
            e["runtime_metadata_ref"] == client[rid]["runtime_metadata_ref"],
            "runtime artifact join",
        )
        need(e["stage"] in stages and e["instance_id"] in instances, "stage/instance")
        inst = instances[e["instance_id"]]
        need(
            e["boot_id"] == inst["boot_id"] and e["rank"] == inst["rank"],
            "boot/rank join",
        )
        need(inst["role"] in allowed_roles[stages[e["stage"]]["layer"]], "stage owner")
        if inst["role"] in ("worker", "gpu"):
            need(
                inst["runtime_metadata_ref"] == e["runtime_metadata_ref"],
                "worker artifact",
            )
            meta = metas[e["runtime_metadata_ref"]]
            for section, field, meta_field in [
                ("model", "weights_sha256", "weights_sha256"),
                ("model", "tokenizer_sha256", "tokenizer_sha256"),
                ("model", "template_sha256", "chat_template_sha256"),
                ("runtime", "framework_commit", "engine_commit"),
                ("runtime", "image_digest", "engine_image_digest"),
                ("runtime", "config_sha256", "effective_config_sha256"),
                ("hardware", "rank_map_ref", "rank_mapping_ref"),
            ]:
                value = manifest[section][field]
                need(
                    value is None or value == meta[meta_field],
                    "manifest/artifact version mismatch",
                )
            need(
                manifest["source_type"] != "external_api",
                "supplier internals unavailable to platform exporter",
            )
        if inst["role"] == "client":
            need(
                e["clock_scope"] == rawreq[rid]["clock_scope"],
                "client clock joins metrics",
            )
            if e["stage"] == "client.request":
                need(
                    e["start_ms"] == rawreq[rid]["sent_ms"]
                    and e["end_ms"] == rawreq[rid]["end_ms"],
                    "client request bounds",
                )
            if e["stage"] == "client.content":
                expected = rows[rid]["client_visible_ttft_ms"]
                need(
                    expected is not None
                    and e["start_ms"] == rawreq[rid]["sent_ms"]
                    and e["end_ms"] == rawreq[rid]["sent_ms"] + expected,
                    "client content boundary",
                )
        if e["stage"] == "client.protocol":
            expected = first_data_event(rawreq[rid]["frames"])
            need(
                expected is not None
                and e["start_ms"] == rawreq[rid]["sent_ms"]
                and e["end_ms"] == expected,
                "client protocol boundary",
            )
        clock = clocks.get(e["clock_scope"])
        need(
            clock is not None
            and clock["instance_id"] == inst["id"]
            and clock["boot_id"] == e["boot_id"],
            "clock instance",
        )
        need(
            e["segment_kind"] in ("inclusive", "activity")
            and e["attribution"] in ("request", "shared_batch"),
            "segment",
        )
        if e["attribution"] == "shared_batch":
            need(
                e["segment_kind"] == "inclusive" and e["batch_id"] is not None,
                "shared work cannot be exclusive",
            )
        if inst["role"] in ("worker", "gpu"):
            need(e["batch_id"] is not None, "worker batch")
        if e["batch_id"] is not None:
            need(e["batch_id"] in batches, "batch join")
            b = batches[e["batch_id"]]
            need(
                b["instance_id"] == inst["id"]
                and b["boot_id"] == e["boot_id"]
                and rid in b["request_ids"]
                and b["rank"] == e["rank"]
                and b["binding_sha256"] == e["binding_sha256"],
                "batch identity",
            )
        need(e["evidence_ref"] in evidence, "evidence join")
        number(e["start_ms"])
        if e["end_ms"] is not None:
            number(e["end_ms"])
            need(e["end_ms"] >= e["start_ms"], "interval order")
        need(e["parent_id"] is None or isinstance(e["parent_id"], str), "parent")
        need(
            type(e["predecessors"]) is list
            and len(e["predecessors"]) == len(set(e["predecessors"])),
            "predecessors",
        )
        if e["segment_kind"] == "inclusive":
            need(not e["predecessors"], "inclusive cannot be dependency task")
        start, end = e["start_ms"], e["end_ms"]
        domain = e["clock_scope"]
        calibration = None
        normal_start, normal_end = start, end
        m = mappings.get(domain)
        if (
            m
            and end is not None
            and m["valid_from_ms"] <= start <= end <= m["valid_to_ms"]
        ):
            calibration = {
                "target": m["target"],
                "estimated_start_ms": start * m["scale"] + m["offset_ms"],
                "estimated_end_ms": end * m["scale"] + m["offset_ms"],
                "max_error_ms": m["max_error_ms"],
                "authority": "declared_unverified_calibration",
            }
            need(
                all(
                    math.isfinite(calibration[k])
                    for k in ("estimated_start_ms", "estimated_end_ms")
                ),
                "mapped finite",
            )
            if m["max_error_ms"] == 0 and sidecar["synthetic"]:
                domain = m["target"]
                normal_start = calibration["estimated_start_ms"]
                normal_end = calibration["estimated_end_ms"]
        normalized[e["id"]] = dict(
            e,
            domain=domain,
            normalized_start_ms=normal_start,
            normalized_end_ms=normal_end,
            calibration=calibration,
            local_duration_ms=None if end is None else end - start,
        )
    for e in normalized.values():
        refs = ([e["parent_id"]] if e["parent_id"] is not None else []) + e[
            "predecessors"
        ]
        for ref in refs:
            need(ref in normalized and ref != e["id"], "missing/self reference")
            other = normalized[ref]
            need(
                other["request_id"] == e["request_id"]
                and other["trace_id"] == e["trace_id"],
                "cross-request edge",
            )
        if e["parent_id"] is not None:
            need(
                normalized[e["parent_id"]]["segment_kind"] == "inclusive",
                "inclusive parent",
            )
        for ref in e["predecessors"]:
            need(
                normalized[ref]["segment_kind"] == "activity"
                and normalized[ref]["attribution"] == "request",
                "dependency endpoint",
            )
    recovery_seen = set()
    for row in sidecar["recovery_observations"]:
        keys(
            row,
            "request_id observer_scope independent_observer cancel_ms stop_ms safe_ms evidence_ms release_ms successor_ms cutoff_ms evidence_ref",
        )
        need(
            row["request_id"] in rows
            and rows[row["request_id"]]["result"] not in ("succeeded", "rejected"),
            "recovery request",
        )
        need(row["request_id"] not in recovery_seen, "duplicate recovery observation")
        recovery_seen.add(row["request_id"])
        need(
            row["observer_scope"] in clocks and row["evidence_ref"] in evidence,
            "recovery clock/evidence",
        )
        number(row["cutoff_ms"])

    return {
        "base": base,
        "events": normalized,
        "instances": instances,
        "clocks": clocks,
        "mappings": mappings,
        "evidence": evidence,
        "stages": stages,
        "manifest": manifest,
        "manifest_missing": unknown,
        "raw_requests": rawreq,
    }
