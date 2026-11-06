"""Recompute the textbook's fixed examples. CPU only; no performance claims."""
import math
import sys

sys.dont_write_bytecode = True
from runtime_walkthrough import simulate, page_lifetime
from release_walkthrough import walkthrough, toy_can_switch
from worked_numbers import calculate


def check_examples():
    checks = []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    n = calculate()
    check("KV: 24 KiB per token; 30 MiB per sequence", n["kv_bytes_per_token"] == 24576 and n["sequence_mib"] == 30)
    check("KV: 384 KiB/page, 5461 pages, 80 pages/sequence", (n["page_kib"], n["physical_pages"], n["pages_per_sequence"]) == (384, 5461, 80))
    check("Capacity is a KV-only 68, not approved concurrency", n["kv_only_upper_bound_sequences"] == 68 and n["safe_platform_concurrency"] is None)
    check("Extra graph memory reduces fictional bound to 55", n["kv_only_sequences_after_graph"] == 55)
    check("GEMM: 12 blocks and 2 K tiles", (n["gemm_blocks"], n["gemm_k_tiles"]) == (12, 2))
    check("GEMM: tails 5/5/13, shared 2048 B, useful 113738 FLOP", n["gemm_tail_rows_cols_k"] == [5,5,13] and n["shared_tile_bytes_per_block"] == 2048 and n["gemm_useful_flops"] == 113738)
    check("Blue/green capacity example: 8 to 16 GPUs", n["bluegreen_group_gpu_example"] == {"current": 8, "overlap": 16})
    check("No hardware/model capacity measurement", n["fictional_example"] is True and n["gpu_or_framework_measured"] is False)

    s = simulate()
    trace = s["trace"]
    check("Six deterministic rounds", [r["step"] for r in trace] == [0,1,2,3,4,5])
    check("Mixed prefill/decode order", [r["work"] for r in trace] == [
        ["A:prefill+2"], ["A:prefill+2"], ["A:decode","B:prefill+1"],
        ["A:decode","B:prefill+1"], ["B:decode"], ["B:decode"]])
    check("First output sampled at final prefill: A", [r["state"]["A"]["generated"] for r in trace] == [0,1,2,3,3,3])
    check("First output sampled at final prefill: B", [r["state"]["B"]["generated"] for r in trace] == [0,0,0,1,2,3])
    check("Round-end physical page example", [r["resident_pages"] for r in trace] == [1,2,4,1,2,0])
    check("Generated 2 != consumed decode 1; KV uses 5 positions", trace[2]["state"]["A"]["decoded"] == 1 and trace[2]["state"]["A"]["pages"] == 3)
    check("Logical steps never become throughput", s["teaching_only"] is True and s["real_time_or_token_throughput"] is None)
    p = page_lifetime()
    check("Zero refs with inflight work cannot reuse", p["after_A_detach"]["P5"] == {"refs":0,"inflight":1} and p["free_before_completion"] == [])
    check("Only completed private page reusable; B unaffected", p["free_after_completion"] == ["P5"] and p["B_table"] == ["P2","P7"] and p["after_A_detach"]["P2"]["refs"] == 1)
    check("Simulated completion is not production proof", p["production_completion_proof"] is False)

    d = walkthrough()
    t = {r["event"]:r for r in d["trace"]}
    check("Partial gateway adoption blocks toy switch", t["partial_receipt"]["result"] == "pending")
    check("Committed result survives unknown ACK", t["commit_then_ack_unknown"]["result_in_store"] == "applied" and t["commit_then_ack_unknown"]["client_ack"] == "unknown")
    check("Read/retry original command, single activation", t["read_same_command"]["result"] == t["retry_same_command"]["result"] == "applied" and d["activation_writes"] == 1)
    check("Same command with changed intent conflicts", t["same_id_different_intent"]["result"] == "conflict")
    check("Stale generation and deleted owner rejected", t["stale_evidence"]["toy_switch_allowed"] is False and t["late_owner_after_delete"]["result"] == "closed")
    check("Drain does not refund financial unknown", d["drain_can_cleanup"] == [False,True] and d["financial_held_preserved"] == [140,140])
    check("Toy controller does not assert production callable", d["teaching_only"] is True and d["production_callable"] is False)
    binding={"cr_uid":"example", "generation":7}
    e={"binding":binding.copy(),"workload_ready":True,"accounting_ready":True,
       "validation_done":True,"serving_instances":["gw1","gw2"],"covered_instances":["gw1","gw2"]}
    check("Fixed complete toy evidence permits equality exercise", toy_can_switch(binding,e) is True)
    for field in ("workload_ready","accounting_ready","validation_done"):
        bad=dict(e,**{field:False})
        check("Missing toy prerequisite: "+field, toy_can_switch(binding,bad) is False)
    check("Wrong revision binding blocks", toy_can_switch(binding,dict(e,binding={"cr_uid":"example","generation":8})) is False)
    check("Empty serving set is not adoption evidence", toy_can_switch(binding,dict(e,serving_instances=[],covered_instances=[])) is False)

    # Independent small hand calculations from the prose, not GPU reference validation.
    a=[[1,2,3],[4,5,6]];b=[[1,2,3,4],[5,6,7,8],[9,10,11,12]]
    c=[[sum(row[k]*b[k][j] for k in range(3)) for j in range(4)] for row in a]
    check("Hand GEMM matrix", c == [[38,44,50,56],[83,98,113,128]])
    check("Suffix mask differs from upper-left triangle", [[k <= 5-2+q for k in range(5)] for q in range(2)] == [[True,True,True,True,False],[True]*5])
    weights=[math.exp(0),math.exp(math.log(2))]
    y=[3*weights[0]/sum(weights),3*weights[1]/sum(weights)]
    check("Hand attention weighted sum [1,2]", math.isclose(y[0],1) and math.isclose(y[1],2))
    check("Hand client TTFT and TPOT", (30-0, (90-30)/(4-1)) == (30,20))
    return checks


if __name__ == "__main__":
    checks=check_examples()
    for name in checks:
        print("PASS: "+name)
    print(str(len(checks))+" teaching checks passed; GPU/framework/deployment not measured.")
