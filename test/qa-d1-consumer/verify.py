"""Independent QA for pinned D1 consumers. Offline; never execute source collection.

Run with --consumer <fresh df8d40e archive> --repo <source Git repo>
--inputs <authenticated d1-input> --output <fresh evidence directory>.
Only this test directory belongs to QA; product/performance code stays unchanged.
"""
import argparse
import copy
import hashlib
import io
import json
import platform
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

SOURCE = "c7e863b11fb34ee2828c947393444e1e5a9baf08"
CONSUMER = "df8d40efa08fcbb72e4a29a922d15ef22a849ec4"
BASE = "8420aaf956b7d44d52c2bbe52c9d20d15fcdb781"
RAW_HASH = "a2589061b5c39fb259397e6bdf6129cbdb16bce8579318438fe760642fb51458"
MANIFEST_HASH = "9cf52e7a5b3338a6f115d087a621fb3f0a932bccdc07bff7ca592ad97378eb9c"
OLD = "d2d7869fe16b8968d6ca5b00a63560c322b84dc1"
OLD_HASH = "ca6c85428ab91a675fdea163bf3a541812dff4cfc5e751e11c871c7b70d49e8c"
SENTINEL = "QA_SYNTHETIC_PRIVATE_SENTINEL_634829"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def packed(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=True) + "\n").encode()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("consumer", "repo", "inputs", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--resume", action="store_true", help="rerun failed checks and new checks; retain the first oracle separately")
    a = p.parse_args()
    for name in ("consumer", "repo", "inputs", "output"):
        setattr(a, name, getattr(a, name).resolve())
    a.output.mkdir(parents=True, exist_ok=a.resume)
    source = a.inputs / "evidence/original-source"
    raw = source / "go-relay-d1.json"
    mf = source / "go-relay-d1-manifest.json"
    export, manifest = json.loads(raw.read_bytes()), json.loads(mf.read_bytes())
    previous = json.loads((a.output / "results.json").read_bytes())["checks"] if a.resume else []
    prior = {c["id"]: c for c in previous}
    checks = []
    commands = json.loads((a.output / "commands.json").read_bytes()) if a.resume else []

    def check(name, fn):
        if a.resume and prior.get(name, {}).get("passed"):
            checks.append(prior[name])
            return
        try:
            fn()
            checks.append(dict(id=name, passed=True))
        except Exception as exc:
            checks.append(dict(id=name, passed=False, error=type(exc).__name__, detail=str(exc)))

    def require(value, message="independent oracle mismatch"):
        if not value:
            raise AssertionError(message)

    def run(args):
        cp = subprocess.run([str(v) for v in args], cwd=a.consumer, capture_output=True, timeout=30)
        text = (cp.stdout + cp.stderr).decode("utf-8", errors="replace")
        require(SENTINEL not in text, "private sentinel echoed")
        commands.append(dict(argv=[str(v).replace(str(a.output.parent), "<workspace>") for v in args],
                             exit_code=cp.returncode, stdout=cp.stdout.decode("utf-8", errors="replace"),
                             stderr=cp.stderr.decode("utf-8", errors="replace")))
        return cp

    def git_blob(commit, path):
        cp = subprocess.run(["git", "-C", str(a.repo), "show", commit + ":" + path], capture_output=True, timeout=20)
        require(cp.returncode == 0, "fixed Git object unavailable: " + path)
        return cp.stdout

    def integrity():
        require(digest(raw.read_bytes()) == RAW_HASH)
        require(digest(mf.read_bytes()) == MANIFEST_HASH)
        hashes = json.loads((a.inputs / "review/manifest-sha256.json").read_bytes())
        require(len(hashes) == 17)
        for path, h in hashes.items():
            require(digest(git_blob(CONSUMER, path)) == h, path)
            require(digest((a.inputs / "review/increment" / path).read_bytes()) == h, path)
            require(digest((a.consumer / path).read_bytes()) == h, path)
        for path, h in manifest["source_sha256"].items():
            require(digest(git_blob(SOURCE, path)) == h, path)
        require(len(manifest["source_sha256"]) == 6)
        schema = "tools/perf/diagnostics/source-contracts/diagnostic-0.1-draft.1.schema.json"
        require((a.consumer / schema).read_bytes() == git_blob(CONSUMER, schema))
    check("I01-fixed-originals-17-files-six-sources-schema", integrity)

    cli = a.consumer / "tools/perf/diagnostics/consume_relay.py"
    def relay_args(r, m, h, out, commit=SOURCE):
        return [sys.executable, cli, "--raw", r, "--manifest", m,
                "--expected-manifest-sha256", h, "--expected-source-commit", commit,
                "--source-repo", a.repo, "--output-dir", out]

    original = a.output / "relay"
    def positive():
        require(run(relay_args(raw, mf, MANIFEST_HASH, original)).returncode == 0)
        require((original / "report.json").read_bytes() == (a.inputs / "evidence/d1-import-report.json").read_bytes(), "JSON differs from delivered report")
        require((original / "report.html").read_bytes() == (a.inputs / "MAAS-10-d1-import-report-v0.13.html").read_bytes(), "HTML differs from delivered report")
    check("P01-byte-exact-json-html-reproduction", positive)
    report = json.loads((original / "report.json").read_bytes())
    rows = {r["source_case"]: r for r in report["source_rows"]}

    def population():
        counts = report["source_counts"]
        require(counts["observed_source_results"] == dict(succeeded=3, failed=2, interrupted=1, cancelled=2, timed_out=1))
        require(counts["source_declared_summary_coverage"]["known"] == 9)
        require(counts["source_declared_summary_coverage"]["denominator"] == 10)
        require(counts["source_declared_summary_coverage"]["ratio"] == .9)
        for field in ("complete_client_sent", "rejected_not_exported", "pending_not_exported", "global_sampler_dropped_counter", "drop_rate"):
            require(counts[field] is None, field)
        require({r["request_id"] for r in rows.values()} == set(manifest["case_to_request"].values()))
        require(len(report["recovery_missing_request_ids"]) == 6)
    check("P02-nine-requests-ten-local-scenarios-no-global-denominator", population)

    def milestones():
        require(rows["write_failure"]["first_content_write_ok_ms"] is None)
        require(rows["write_failure"]["first_content_flush_attempt_ms"] is not None)
        require(rows["write_failure"]["observed_result"] != "succeeded")
        for case in ("empty", "usage_only"):
            require(rows[case]["first_protocol_ms"] is not None)
            require(all(rows[case][f] is None for f in ("first_content_received_ms", "first_content_write_ok_ms", "first_content_flush_attempt_ms")))
        for r in rows.values():
            require(r["go_legacy_first_chunk_ms"] is None and r["client_visible_ttft_ms"] is None)
            require(r["actual_usage"] is None and r["terminal_result"] is None)
        require(all(d["go_server_first_chunk_ms"] is None for d in report["request_diagnostics"]))
    check("P03-four-milestones-and-two-origins", milestones)

    def limits():
        for field in ("rates", "goodput", "observation_window", "registry", "metric_report"):
            require(report[field] is None, field)
        require(all(not report[k] for k in ("d1_overall_complete", "e1_executed", "real_execution_enabled", "benchmark_comparable")))
        require(report["source_import"]["sampled_source_revisions"] == ["working-tree-d1"])
        require(report["source_import"]["capture_commit_attested"] is False)
        require(report["source_import"]["source_files_verified_against_delivery_commit"] is True)
        require(report["timeline"]["end_to_end_critical_path_ms"] is None)
        require(all(r["invocation_binding"] is None and r["trace_id"] is None for r in rows.values()))
        html = (original / "report.html").read_text(encoding="utf-8")
        for text in ("Go Forward content receive ms", "flush attempt ms", "Received", "working-tree-d1", "9/10"):
            require(text in html, "HTML disclosure missing: " + text)
    check("P04-downgrade-and-html-disclosures", limits)

    snapshot = {f.name: f.read_bytes() for f in original.iterdir()}
    mutations = a.output / "mutations"
    mutations.mkdir(exist_ok=a.resume)
    cases = []
    def sample(field, value):
        return lambda e, m: e["samples"][0].__setitem__(field, value)
    cases.extend([
        ("raw-hash", lambda e, m: None, "raw"),
        ("manifest-hash", lambda e, m: None, "manifest"),
        ("expected-commit", lambda e, m: None, "commit"),
        ("source-digest", lambda e, m: m["source_sha256"].__setitem__(next(iter(m["source_sha256"])), "0"*64), None),
        ("sample-run", sample("run_id", "wrong-run"), None),
        ("request", sample("request_id", "00000000-0000-4000-8000-000000000099"), None),
        ("boot", sample("boot_id", "00000000-0000-4000-8000-000000000099"), None),
        ("clock", sample("clock_scope", "shared-clock"), None),
        ("duplicate", lambda e, m: e["samples"].__setitem__(1, copy.deepcopy(e["samples"][0])), None),
        ("unmapped", lambda e, m: m["case_to_request"].__setitem__("content", "00000000-0000-4000-8000-000000000099"), None),
        ("private-sample", sample("body", SENTINEL), None),
        ("private-export", lambda e, m: e.__setitem__("prompt", SENTINEL), None),
        ("private-manifest", lambda e, m: m.__setitem__("secret", SENTINEL), None),
        ("negative-time", sample("first_content_received_ms", -1), None),
        ("boolean-time", sample("first_content_received_ms", True), None),
        ("nan-time", sample("first_content_received_ms", float("nan")), None),
        ("infinite-time", sample("first_content_received_ms", float("inf")), None),
        ("time-after-end", sample("first_content_received_ms", 1e12), None),
        ("missing-parent", sample("first_content_received_ms", None), None),
        ("reversed-time", sample("first_content_write_ok_ms", 0), None),
        ("version", sample("schema_version", "future-2"), None),
        ("fake-complete-sidecar", lambda e, m: m.__setitem__("direct_diagnostic_sidecar_import_ready", True), None),
        ("hide-missing-clock", lambda e, m: e["missing_components"].remove("cross_clock_calibration"), None),
        ("hide-missing-trace", lambda e, m: e["missing_identity"].remove("trace_id"), None),
        ("source-path-traversal", lambda e, m: m["source_sha256"].__setitem__("../../private", "a"*64), None),
        ("manifest-command", lambda e, m: m.__setitem__("collection_command", "echo " + SENTINEL), None),
    ])
    for name, mutate, pin in cases:
        def negative(name=name, mutate=mutate, pin=pin):
            e, m = copy.deepcopy(export), copy.deepcopy(manifest)
            mutate(e, m)
            folder = mutations / name
            folder.mkdir()
            r, f = folder / "raw.json", folder / "manifest.json"
            r.write_bytes(packed(e))
            m["raw_sha256"] = digest(r.read_bytes()) if pin != "raw" else "0"*64
            f.write_bytes(packed(m))
            h = digest(f.read_bytes()) if pin != "manifest" else "0"*64
            args = relay_args(r, f, h, folder / "new-report", "0"*40 if pin == "commit" else SOURCE)
            require(run(args).returncode == 2, "invalid input accepted")
            require(not (folder / "new-report").exists(), "published invalid report")
            args[-1] = original
            require(run(args).returncode == 2)
            require(snapshot == {f.name: f.read_bytes() for f in original.iterdir()}, "old report changed")
            require(not list(a.output.rglob("*.pending-*")), "staging output leaked")
        check("N-" + name, negative)

    for name, mode in (("zero", "zero"), ("all-null", "null")):
        def synthetic(name=name, mode=mode):
            e, m = copy.deepcopy(export), copy.deepcopy(manifest)
            times = ("first_protocol_ms", "first_content_received_ms", "first_content_write_ok_ms", "first_content_flush_attempt_ms")
            for t in times:
                e["samples"][0][t] = 0 if mode == "zero" else None
            folder = mutations / name
            folder.mkdir()
            r, f = folder / "raw.json", folder / "manifest.json"
            r.write_bytes(packed(e))
            m["raw_sha256"] = digest(r.read_bytes())
            f.write_bytes(packed(m))
            out = folder / "report"
            require(run(relay_args(r, f, digest(f.read_bytes()), out)).returncode == 0)
            row = json.loads((out / "report.json").read_bytes())["source_rows"][0]
            require(all(row[t] == (0 if mode == "zero" else None) for t in times))
            require(row["go_legacy_first_chunk_ms"] is None)
        check("S-" + name + "-synthetic-mutation", synthetic)

    def full_sidecar():
        out = a.output / "invalid-full-sidecar"
        args = [sys.executable, a.consumer / "tools/perf/diagnostics/run.py", "--metrics-input", a.consumer / "tools/perf/fixtures/synthetic.json", "--timeline-input", raw, "--output-dir", out]
        require(run(args).returncode == 2)
        require(not out.exists())
    check("N-raw-export-cannot-become-full-sidecar", full_sidecar)

    old_archive = a.inputs / "MAAS-7-usage-reader-independent-evidence.zip"
    old_cli = a.consumer / "tools/perf/diagnostics/consume.py"
    def old_args(archive, h, out):
        return [sys.executable, old_cli, "--archive", archive, "--expected-archive-sha256", h, "--expected-source-commit", OLD, "--output-dir", out]
    historical = a.output / "historical"
    def historical_positive():
        require(digest(old_archive.read_bytes()) == OLD_HASH)
        if not historical.exists():
            require(run(old_args(old_archive, OLD_HASH, historical)).returncode == 0)
        data = json.loads((historical / "report.json").read_bytes())
        require(data["source_counts"]["observed_terminal_records"] == 20)
        require(data["source_counts"]["source_test_oracle_failed"] == 1)
        require(data["source_counts"]["source_test_oracle_passed"] == 19)
        require({r["request_id"] for r in data["source_rows"]}.isdisjoint({r["request_id"] for r in rows.values()}))
        require((historical / "report.json").read_bytes() == (a.inputs / "evidence/historical-QA-normalized-report.json").read_bytes())
        unknown = [r for r in data["source_rows"] if r["token_actual"] is None]
        zeros = [r for r in data["source_rows"] if r["token_actual"] == "0"]
        # The authenticated 20-record archive has no real-zero sample. Do not invent one.
        require(len(unknown) == 16 and not zeros)
        require(any(int(r["current_token_ledger"]["Held"]) > 0 for r in unknown))
        require(any(r["terminal_original_token_reserved"] != r["current_token_ledger"]["Reserved"] for r in data["source_rows"]))
    check("H01-twenty-historical-requests-oracle-null-zero-held-no-join", historical_positive)

    with zipfile.ZipFile(old_archive) as z:
        members = {n: z.read(n) for n in z.namelist()}
    primary = "artifacts/qa-usage-evidence.json"
    for mode in ("archive-hash", "member-hash", "required-path", "duplicate-member", "unused-private-member"):
        def archive_case(mode=mode):
            items = dict(members)
            if mode == "member-hash":
                items[primary] += b" "
            if mode == "required-path":
                items["../" + primary] = items.pop(primary)
            if mode == "unused-private-member":
                items["../" + SENTINEL + ".txt"] = SENTINEL.encode()
            outzip = mutations / (mode + ".zip")
            with zipfile.ZipFile(outzip, "w", zipfile.ZIP_DEFLATED) as z:
                for n, data in items.items():
                    z.writestr(n, data)
                if mode == "duplicate-member":
                    z.writestr(primary, members[primary])
            h = "0"*64 if mode == "archive-hash" else digest(outzip.read_bytes())
            target = mutations / (mode + "-out")
            cp = run(old_args(outzip, h, target))
            if mode == "unused-private-member":
                require(cp.returncode == 0, "unread non-allowlisted archive member affects import")
                require(SENTINEL.encode() not in (target / "report.json").read_bytes())
                require(SENTINEL.encode() not in (target / "report.html").read_bytes())
                require({f.name for f in target.iterdir()} == {"report.json", "report.html", "consumer-import-overhead.json"})
            else:
                require(cp.returncode == 2 and not target.exists())
        check("H-" + mode, archive_case)

    def historical_synthetic_zero():
        # Derived input only; this is explicitly not an original Go execution.
        original_rows = json.loads(members[primary])
        zero = copy.deepcopy(original_rows[0])
        zero["case"] = "qa_synthetic_zero"
        t = zero["terminal"]
        for field in ("input_tokens", "output_tokens", "total_tokens", "input_cached_tokens", "reasoning_tokens"):
            t["usage"][field] = 0
        budget = t["budget_accounting"]
        budget["token_actual"] = budget["cost_actual_atomic"] = "0"
        for field, ledger in (("token", "tokens"), ("money", "money")):
            budget[field]["known_used"] = "0"
            budget[field]["released"] = budget[field]["reserved"]
            zero[ledger]["Known"] = "0"
        for d in zero["diagnostics"]:
            if d["usage"] is not None:
                d["usage"] = {k: 0 for k in d["usage"]}
        unknown = next(r for r in original_rows if r["terminal"]["budget_accounting"]["token_actual"] is None)
        blobs = {n: members[n] for n in (primary, "artifacts/qa-usage-partial-retest.json", "artifacts/qa-results.json", "test/qa-usage/kernel_test.go.in")}
        blobs[primary] = packed([zero, unknown])
        blobs["artifacts/qa-usage-partial-retest.json"] = packed([])
        blobs["manifest-sha256.json"] = packed({n: digest(b) for n, b in blobs.items()})
        path = mutations / "SYNTHETIC-zero-and-null.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in blobs.items():
                z.writestr(n, b)
        target = mutations / "SYNTHETIC-zero-and-null-out"
        require(run(old_args(path, digest(path.read_bytes()), target)).returncode == 0)
        data = json.loads((target / "report.json").read_bytes())["source_rows"]
        require(data[0]["token_actual"] == "0" and data[0]["actual_usage"]["total_tokens"] == 0)
        require(data[1]["token_actual"] is None and data[1]["actual_usage"]["total_tokens"] is None)
        require(data[1]["current_token_ledger"]["Held"] == "140")
    check("S-historical-real-zero-value-vs-null-SYNTHETIC-only", historical_synthetic_zero)

    for mode in ("no-calibration", "untrusted-zero-error-calibration", "missing-trace", "missing-binding", "missing-experiment"):
        def sidecar_case(mode=mode):
            data = json.loads((a.consumer / "tools/perf/fixtures/synthetic.json").read_bytes())
            side = json.loads((a.consumer / "tools/perf/diagnostics/fixtures/timeline.synthetic.json").read_bytes())
            if mode == "no-calibration":
                side["mappings"] = []
            elif mode == "untrusted-zero-error-calibration":
                # Flags deliberately exercise unverified declarations using synthetic data.
                data["synthetic"] = side["synthetic"] = False
                side["evidence_kind"] = "controlled_export_unverified"
            elif mode == "missing-trace":
                del side["intervals"][0]["trace_id"]
            elif mode == "missing-binding":
                del side["intervals"][0]["binding_sha256"]
            else:
                del side["registry"]["experiment_ref"]
            folder = mutations / ("SYNTHETIC-sidecar-" + mode)
            folder.mkdir()
            d, s = folder / "metrics.json", folder / "sidecar.json"
            d.write_bytes(packed(data))
            side["dataset_sha256"] = digest(d.read_bytes())
            s.write_bytes(packed(side))
            out = folder / "out"
            args = [sys.executable, a.consumer / "tools/perf/diagnostics/run.py", "--metrics-input", d, "--timeline-input", s, "--output-dir", out]
            cp = run(args)
            if mode.startswith("missing-"):
                require(cp.returncode == 2 and not out.exists())
            else:
                require(cp.returncode == 0)
                r = json.loads((out / "report.json").read_bytes())
                require(r["timeline"]["blocked_edges"])
                require(r["benchmark_comparable"] is False)
                kernel = next(i for i in r["timeline"]["intervals"] if i["id"] == "kernel")
                require(kernel["analysis_domain"] == "synthetic-device-clock")
                require(all(c["observed_active_dependency_chain_ms"] < 165 for c in r["timeline"]["observed_dependency_chains"]))
        check("S-sidecar-" + mode, sidecar_case)

    result = dict(source_commit=SOURCE, consumer_commit=CONSUMER, delta_base=BASE,
                  python=sys.version, platform=platform.platform(),
                  unique_checks=len(checks), passed=sum(c["passed"] for c in checks),
                  failed=sum(not c["passed"] for c in checks), cli_invocations=len(commands),
                  source_go_rerun=False, real_execution_enabled=False, checks=checks)
    (a.output / "results.json").write_bytes(packed(result))
    (a.output / "commands.json").write_bytes(packed(commands))
    print(json.dumps({k: v for k, v in result.items() if k != "checks"}, indent=2))
    for c in checks:
        if not c["passed"]:
            print(json.dumps(c))
    return int(result["failed"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
