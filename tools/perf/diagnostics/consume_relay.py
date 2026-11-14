"""Consume pinned Go relay D1 export and manifest; source collection is never executed."""

import argparse, json, subprocess, sys
from pathlib import Path
from time import perf_counter_ns

if __package__:
    from .relay_import import build_report
    from .validation import DiagnosticError
    from .run import publish
else:
    from relay_import import build_report
    from validation import DiagnosticError
    from run import publish


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--expected-manifest-sha256", required=True)
    p.add_argument("--expected-source-commit", required=True)
    p.add_argument("--source-repo", type=Path)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    try:
        if a.output_dir.exists():
            raise FileExistsError()
        start = perf_counter_ns()
        report = build_report(
            a.raw,
            a.manifest,
            a.expected_manifest_sha256,
            a.expected_source_commit,
            a.source_repo,
        )
        overhead = {
            "consumer_parse_validate_compose_ns": perf_counter_ns() - start,
            "scope": "consumer process monotonic; includes optional git reads, excludes render/publication; NOT source hot path",
            "source_sampling_overhead_ns": None,
            "source_sampled_vs_unsampled_pair": None,
        }
        publish(
            a.output_dir,
            report,
            {"consumer-import-overhead.json": json.dumps(overhead, indent=2) + "\n"},
        )
    except (
        DiagnosticError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        UnicodeError,
        subprocess.SubprocessError,
    ):
        print(
            "D1 relay import rejected integrity, shape, clock, identity or unavailable output",
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "exported_summary_records": report["source_counts"][
                    "exported_summary_records"
                ],
                "d1_overall_complete": False,
                "e1_executed": False,
                "go_executed_this_import": False,
                "model_bottleneck": None,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
