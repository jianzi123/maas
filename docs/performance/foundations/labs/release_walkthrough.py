"""Pure TEACHING controller/journal model. No K8s/MySQL/Go/Higress APIs."""
import json


def toy_can_switch(binding, evidence):
    # Equality/coverage exercise only: does NOT verify identity, signature, freshness or authority.
    if not evidence.get("serving_instances"):
        return False
    if not evidence.get("workload_ready") or not evidence.get("accounting_ready") or not evidence.get("validation_done"):
        return False
    return (binding == evidence.get("binding") and
            set(evidence.get("covered_instances", [])) == set(evidence.get("serving_instances", [])))


def walkthrough():
    binding = {"cr_uid": "M1", "generation": 7, "revision": "r7",
               "publication": "p7", "activation_epoch": 12}
    store = {"journal": {}, "active": None, "activation_writes": 0, "tombstone": False}
    events = []
    command = "cmd-M1-p7-e12"  # stable identity, not a signed production command
    def apply(evidence, intent=None):
        intent = binding if intent is None else intent
        if store["tombstone"]:
            return "closed"
        if command in store["journal"]:
            record = store["journal"][command]
            if record["intent"] != intent:
                return "conflict"
            return record["result"]  # same payload recovers original commit; never re-executes
        if not toy_can_switch(binding, evidence):
            return "pending"
        store["active"] = binding.copy()
        store["activation_writes"] += 1
        store["journal"][command] = {"intent": intent.copy(), "result": "applied"}
        return "applied"
    evidence = {"workload_ready": True, "accounting_ready": True, "validation_done": True,
                "binding": binding.copy(), "serving_instances": ["gw1", "gw2"],
                "covered_instances": ["gw1"]}
    events.append({"event": "partial_receipt", "result": apply(evidence)})
    evidence["covered_instances"].append("gw2")
    events.append({"event": "commit_then_ack_unknown", "result_in_store": apply(evidence),
                   "client_ack": "unknown"})
    events.append({"event": "read_same_command", "result": store["journal"][command]["result"]})
    events.append({"event": "retry_same_command", "result": apply(evidence)})
    events.append({"event": "same_id_different_intent",
                   "result": apply(evidence, dict(binding, generation=8))})
    stale = dict(evidence, binding=dict(binding, generation=6))
    events.append({"event": "stale_evidence", "toy_switch_allowed": toy_can_switch(binding, stale)})
    store["tombstone"] = True
    events.append({"event": "late_owner_after_delete", "result": apply(evidence)})
    # Three dimensions are deliberately separate; financial held is not a slot count.
    drain = [{"in_progress": 1, "unsafe_slots": 1, "financial_held": 140},
             {"in_progress": 0, "unsafe_slots": 0, "financial_held": 140}]
    return {"teaching_only": True, "production_callable": False, "trace": events,
            "activation_writes": store["activation_writes"],
            "drain_can_cleanup": [r["in_progress"] == r["unsafe_slots"] == 0 for r in drain],
            "financial_held_preserved": [r["financial_held"] for r in drain],
            "limitations": "no durable transaction/CAS/signature/real receipts or resource operations"}


if __name__ == "__main__":
    print(json.dumps(walkthrough(), indent=2))
