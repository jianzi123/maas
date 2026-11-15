"""Read-only review consistency check. It cannot authorize or configure a runtime."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from identities import DATABASE_ENV

ROOT = Path(__file__).resolve().parents[2]
CARD = ROOT / "deploy/intake/source-input-cards-20261115.json"
EXPECTED_IDS = {
    "external_api": {f"EXT-{n:02d}" for n in range(1, 7)},
    "self_hosted": {f"SELF-{n:02d}" for n in range(1, 7)},
}

def inspect(card, root=ROOT):
    errors = []
    checks = []
    def check(name, ok):
        checks.append({"check": name, "passed": bool(ok)})
        if not ok:
            errors.append(name)
    check("intake_is_not_runtime_configuration",
          card.get("artifact_kind") == "ops-review-intake-not-runtime-configuration")
    check("no_target_deployment_approval", card.get("deployment_approved") is False)
    count = 0
    for source, ids in EXPECTED_IDS.items():
        section = card.get(source, {})
        check(source + ".execution_disabled", section.get("real_execution_enabled") is False)
        rows = section.get("inputs", [])
        check(source + ".groups", len(rows) == len(ids) and {r.get("id") for r in rows} == ids)
        for row in rows:
            prefix = source + "." + row["id"]
            check(prefix + ".no_group_approval", row.get("value") is None)
            resolution = row.get("field_resolution", {})
            fields = row.get("fields", [])
            check(prefix + ".complete_field_resolution",
                  len(fields) == len(set(fields)) and set(fields) == set(resolution))
            for field in fields:
                item = resolution.get(field, {})
                count += 1
                check(prefix + "." + field, item.get("approved_value") is None
                      and bool(item.get("owner")) and bool(item.get("next_action"))
                      and item.get("status") in {"repository_defined_target_pending",
                          "candidate_not_approved", "production_entrypoint_missing",
                          "pending_approved_input", "awaiting_model_owner"})
    identities = json.loads((root / "deploy/identities.json").read_text(encoding="utf-8"))
    mapping = card.get("database_wiring", {})
    check("five_roles_match_existing_plan", len(mapping) == 5
          and set(mapping) == set(identities["connections"])
          and all(v["roles"] == identities["connections"][k]["roles"] for k, v in mapping.items()))
    check("publisher_is_explicit_argument",
          mapping.get("publisher", {}).get("environment_name") is None
          and mapping.get("publisher", {}).get("injection") == "explicit_function_argument")
    check("four_real_env_names",
          {k: v["environment_name"] for k, v in mapping.items() if v["environment_name"]} == DATABASE_ENV)
    for name, binding in mapping.items():
        check("target_reference_still_pending." + name,
              binding.get("secret_reference") == {"namespace": None, "name": None, "key": None}
              and binding.get("production_wiring_verified") is False)
    manifest = card.get("source_observations", [])
    check("source_observations_present", len(manifest) >= 10)
    for item in manifest:
        rel = Path(item["path"])
        safe = not rel.is_absolute() and ".." not in rel.parts
        path = root / rel
        ok = safe and path.is_file() and not path.is_symlink()
        if ok:
            raw = path.read_bytes()
            ok = hashlib.sha256(raw).hexdigest() == item["sha256"]
            text = raw.decode("utf-8")
            ok = ok and all(anchor in text for anchor in item["anchors"])
        check("source_bytes_and_excerpt." + item["id"], ok)
    resources = card.get("self_hosted", {}).get("ops_extension", {}).get("group_resources", {})
    check("no_invented_target_group_numbers",
          all(resources.get(k) is None for k in ("groups", "pods_per_group", "gpus_per_pod",
              "old_groups_at_peak", "new_groups_at_peak", "gpu_memory_peak_bytes_each")))
    return {"scope": "offline-review-consistency-and-source-excerpts-only",
            "passed": not errors, "errors": errors, "checks": checks, "field_count": count,
            "target_runtime_verified": False, "permissions_retested": False,
            "source_baseline": card.get("source_baseline"),
            "limitations": ["Hashes/excerpts are not Go semantic verification.",
                "No Secret bodies, network, Kubernetes, MySQL, model or GPU accessed.",
                "No runtime configuration or authorization is emitted."]}

def negative_cases(card, root=ROOT):
    mutations = [
        ("execution_enabled", lambda c: c["external_api"].update(real_execution_enabled=True)),
        ("unbacked_approved_field", lambda c: c["external_api"]["inputs"][2]["field_resolution"]["credential_delivery_channel"].update(approved_value="not-approved")),
        ("invented_publisher_env", lambda c: c["database_wiring"]["publisher"].update(environment_name="MAAS_PUBLISHER_DSN")),
        ("publisher_inherits_core", lambda c: c["database_wiring"]["publisher"]["roles"].append("maas_kernel_runtime")),
        ("source_hash_drift", lambda c: c["source_observations"][0].update(sha256="0"*64)),
        ("shared_env_replaces_reader", lambda c: c["database_wiring"]["historyReader"].update(environment_name="MAAS_MYSQL_DSN")),
        ("swapped_reader_envs", lambda c: (c["database_wiring"]["historyReader"].update(environment_name="MAAS_HISTORY_PAYLOAD_DSN"), c["database_wiring"]["payloadReader"].update(environment_name="MAAS_HISTORY_READER_DSN"))),
        ("invented_target_GPU_count", lambda c: c["self_hosted"]["ops_extension"]["group_resources"].update(gpus_per_pod=1)),
    ]
    rows = []
    for name, mutate in mutations:
        changed = copy.deepcopy(card)
        mutate(changed)
        result = inspect(changed, root)
        rows.append({"case": name, "rejected": not result["passed"], "errors": result["errors"]})
    return rows

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--card", type=Path, default=CARD)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--negative-cases", action="store_true", help="Also check isolated in-memory tamper cases.")
    args = parser.parse_args()
    card = json.loads(args.card.read_text(encoding="utf-8"))
    result = inspect(card)
    if args.negative_cases:
        result["negative_cases"] = negative_cases(card)
        result["passed"] = result["passed"] and all(row["rejected"] for row in result["negative_cases"])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in result.items() if k != "checks"}, ensure_ascii=True))
    raise SystemExit(0 if result["passed"] else 1)

if __name__ == "__main__":
    main()