"""Interval arithmetic and explicit causal chains; inclusive spans are never summed."""

from collections import defaultdict
import heapq

if __package__:
    from .validation import need
else:
    from validation import need


def union(intervals):
    merged = []
    for start, end in sorted(intervals):
        need(start <= end, "interval order")
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def topological(events, parents=False):
    indegree = {key: 0 for key in events}
    children = defaultdict(list)
    for key, e in events.items():
        refs = (
            ([e["parent_id"]] if e["parent_id"] is not None else [])
            if parents
            else e["predecessors"]
        )
        for ref in refs:
            need(ref in events, "graph reference")
            indegree[key] += 1
            children[ref].append(key)
    ready = [key for key, n in indegree.items() if n == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        key = heapq.heappop(ready)
        order.append(key)
        for child in children[key]:
            indegree[child] -= 1
            if not indegree[child]:
                heapq.heappush(ready, child)
    need(len(order) == len(events), "cycle")
    return order


def summarize(events):
    topological(events, parents=True)
    order = topological(events)
    children = defaultdict(list)
    for e in events.values():
        if e["parent_id"] is not None:
            children[e["parent_id"]].append(e)
    intervals = []
    for e in events.values():
        total = e["local_duration_ms"]
        exclusive = None
        reason = None
        eligible = e["end_ms"] is not None and e["attribution"] == "request"
        if not eligible:
            reason = "missing_end" if e["end_ms"] is None else "shared_batch"
        elif e["segment_kind"] == "activity":
            need(not children[e["id"]], "exclusive task cannot contain child")
            exclusive = e["normalized_end_ms"] - e["normalized_start_ms"]
        else:
            complete = []
            for child in children[e["id"]]:
                if child["domain"] != e["domain"] or child["normalized_end_ms"] is None:
                    reason = "child_clock_or_end_unknown"
                    break
                need(
                    e["normalized_start_ms"]
                    <= child["normalized_start_ms"]
                    <= child["normalized_end_ms"]
                    <= e["normalized_end_ms"],
                    "parent containment",
                )
                complete.append(
                    (child["normalized_start_ms"], child["normalized_end_ms"])
                )
            if reason is None:
                exclusive = (
                    e["normalized_end_ms"] - e["normalized_start_ms"] - union(complete)
                )
        intervals.append(
            {
                "id": e["id"],
                "stage": e["stage"],
                "request_id": e["request_id"],
                "clock_scope": e["clock_scope"],
                "trace_id": e["trace_id"],
                "binding_sha256": e["binding_sha256"],
                "runtime_metadata_ref": e["runtime_metadata_ref"],
                "instance_id": e["instance_id"],
                "boot_id": e["boot_id"],
                "rank": e["rank"],
                "batch_id": e["batch_id"],
                "start_ms": e["start_ms"],
                "end_ms": e["end_ms"],
                "normalized_start_ms": e["normalized_start_ms"],
                "normalized_end_ms": e["normalized_end_ms"],
                "parent_id": e["parent_id"],
                "predecessors": e["predecessors"],
                "analysis_domain": e["domain"],
                "local_duration_ms": total,
                "exclusive_self_ms": exclusive,
                "exclusive_missing_reason": reason,
                "exclusive_scope": "parent minus union(exported comparable direct children); undeclared work may remain",
                "activity_exclusivity": "exporter-declared, unverified",
                "segment_kind": e["segment_kind"],
                "attribution": e["attribution"],
                "evidence_ref": e["evidence_ref"],
                "calibration": e["calibration"],
            }
        )
    groups = defaultdict(list)
    for e in events.values():
        if e["normalized_end_ms"] is not None:
            groups[(e["request_id"], e["domain"])].append(
                (e["normalized_start_ms"], e["normalized_end_ms"])
            )
    unions = [
        {
            "request_id": rid,
            "analysis_domain": domain,
            "covered_interval_union_ms": union(values),
            "note": "covered wall-time union, not CPU/GPU busy or bottleneck time",
        }
        for (rid, domain), values in sorted(groups.items())
    ]
    score = {}
    path = {}
    blocked = []
    valid_edges = []
    for key in order:
        e = events[key]
        if (
            e["segment_kind"] != "activity"
            or e["attribution"] != "request"
            or e["normalized_end_ms"] is None
        ):
            continue
        weight = e["normalized_end_ms"] - e["normalized_start_ms"]
        score[key] = weight
        path[key] = (key,)
        for ref in e["predecessors"]:
            p = events[ref]
            need(
                p["segment_kind"] == "activity" and p["attribution"] == "request",
                "exclusive request dependency endpoints required",
            )
            if ref not in score or p["normalized_end_ms"] is None:
                blocked.append({"from": ref, "to": key, "reason": "missing_end"})
                continue
            if p["domain"] != e["domain"]:
                blocked.append(
                    {
                        "from": ref,
                        "to": key,
                        "reason": "uncalibrated_or_uncertain_clock",
                    }
                )
                continue
            need(
                p["normalized_end_ms"] <= e["normalized_start_ms"],
                "dependency overlaps execution",
            )
            valid_edges.append([ref, key])
            candidate = score[ref] + weight
            if (
                candidate > score[key]
                or candidate == score[key]
                and path[ref] + (key,) < path[key]
            ):
                score[key] = candidate
                path[key] = path[ref] + (key,)
    by_request = defaultdict(list)
    for key in score:
        if len(path[key]) >= 2:
            by_request[events[key]["request_id"]].append(key)
    chains = []
    for rid, ends in sorted(by_request.items()):
        endpoint = min(ends, key=lambda key: (-score[key], path[key]))
        ids = path[endpoint]
        first, last = events[ids[0]], events[ids[-1]]
        elapsed = last["normalized_end_ms"] - first["normalized_start_ms"]
        chains.append(
            {
                "request_id": rid,
                "interval_ids": list(ids),
                "analysis_domain": first["domain"],
                "observed_active_dependency_chain_ms": score[endpoint],
                "observed_chain_elapsed_ms": elapsed,
                "known_dependency_gaps_ms": elapsed - score[endpoint],
                "scope": "longest weighted path among explicitly exported exclusive tasks; NOT full end-to-end critical path",
                "calibration_authority": "input declaration only, unverified",
            }
        )
    return {
        "intervals": intervals,
        "interval_unions": unions,
        "observed_dependency_chains": chains,
        "verified_temporal_edges": valid_edges,
        "blocked_edges": blocked,
        "end_to_end_critical_path_ms": None,
        "unattributed_ms": None,
        "model_bottleneck": None,
        "note": "Never infer causal edges from timestamps or assign unexplained residual to GPU/network.",
    }
