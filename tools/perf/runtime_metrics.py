"""Pure diagnostic arithmetic; never a slot release or budget correction authority."""
from analyze import distribution


def recovery_summary(records, cutoff_ms):
    if type(cutoff_ms) is not int or cutoff_ms < 0:
        raise ValueError("invalid observation cutoff")
    scopes = {r["observer_scope"] for r in records}
    if len(scopes) > 1 or any(not isinstance(s, str) or not s for s in scopes):
        raise ValueError("independent observer coordinates must match")
    samples, censored = [], []
    for row in records:
        if row.get("independent_observer") is not True:
            raise ValueError("candidate self-observation is not independent evidence")
        cancel = row["cancel_ms"]
        if type(cancel) is not int or not 0 <= cancel <= cutoff_ms:
            raise ValueError("invalid cancellation time")
        for key in ("stop_ms", "safe_ms", "evidence_ms", "release_ms", "successor_ms"):
            value = row[key]
            if value is not None and (type(value) is not int or not cancel <= value <= cutoff_ms):
                raise ValueError("event outside observation interval")
        release, safe, evidence = row["release_ms"], row["safe_ms"], row["evidence_ms"]
        if release is not None and (safe is None or evidence is None or release < max(safe, evidence)):
            raise ValueError("release lacks preceding safe/evidence observations")
        successor = row["successor_ms"]
        if successor is not None and (release is None or successor < release):
            raise ValueError("successor precedes release")
        samples.append(release - cancel if release is not None else None)
        censored.append(cutoff_ms - cancel if release is None else None)
    return {"count": len(records), "recovered": sum(v is not None for v in samples),
            "unrecovered": sum(v is None for v in samples), "cutoff_ms": cutoff_ms,
            "cancel_to_release_observed_ms": distribution(samples, len(records)),
            "right_censor_durations_ms": censored,
            "actual_stop_unknown": sum(r["stop_ms"] is None for r in records),
            "authority": "independent experimental observations only; not production release proof"}


def held_area(points, start_ms, cutoff_ms, unit):
    if type(start_ms) is not int or type(cutoff_ms) is not int or not 0 <= start_ms < cutoff_ms:
        raise ValueError("invalid held observation window")
    if unit != "token" and not (isinstance(unit, str) and unit.startswith("money:") and
                                len(unit) == 9 and unit[6:].isascii() and unit[6:].isalpha() and unit[6:].isupper()):
        raise ValueError("money requires a single explicit currency")
    previous, area, covered = None, 0, 0
    for index, point in enumerate(points):
        at, value = point["at_ms"], point["held"]
        if type(at) is not int or not start_ms <= at <= cutoff_ms or (previous is not None and at <= previous):
            raise ValueError("held points must be strictly ordered in the fixed window")
        if value is not None and (not isinstance(value, str) or not value.isascii() or
                                  not value.isdigit() or (len(value)>1 and value[0]=="0")):
            raise ValueError("held must be a canonical nonnegative integer string or null")
        end = points[index+1]["at_ms"] if index+1 < len(points) else cutoff_ms
        if type(end) is not int or end < at or end > cutoff_ms:
            raise ValueError("invalid held segment")
        if value is not None:
            area += int(value) * (end-at)
            covered += end-at
        previous = at
    whole, fraction = divmod(area, 1000)
    seconds = str(whole) + (("." + str(fraction).zfill(3).rstrip("0")) if fraction else "")
    return {"unit": unit + "*ms", "known_integral": str(area),
            "known_integral_in_seconds": seconds,
            "known_duration_ms": covered, "missing_duration_ms": cutoff_ms-start_ms-covered,
            "actual_usage": None, "note": "stepwise observed occupancy; never a refund calculation"}
