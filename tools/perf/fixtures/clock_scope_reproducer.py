"""Offline regression probe; uses only the delivered synthetic fixture."""
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()  # repository root containing tools/perf
sys.path.insert(0, str(root / "tools/perf"))
import analyze
data = analyze.load_json(root / "tools/perf/fixtures/synthetic.json")
rid = data["requests"][0]["request_id"]
data["requests"][0]["clock_scope"] = "other-client-monotonic"
for observation in data["observations"]:
    if observation["request_id"] == rid and observation["producer"] == "client":
        observation["clock_scope"] = "other-client-monotonic"
try:
    analyze.analyze(data)
except analyze.InputError:
    print("PASS: rejected mixed unnormalized client clocks")
else:
    raise SystemExit("FAIL: mixed unnormalized client clocks accepted for a common throughput window")
