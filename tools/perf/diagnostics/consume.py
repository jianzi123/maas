"""Consume an authenticated, hash-pinned existing QA archive into a partial D1 report."""

import argparse, json, sys, zipfile
from pathlib import Path
from time import perf_counter_ns

if __package__:
    from .source_import import build_report
    from .validation import DiagnosticError, InputError
    from .run import publish
else:
    from source_import import build_report
    from validation import DiagnosticError, InputError
    from run import publish


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--expected-archive-sha256", required=True)
    p.add_argument("--expected-source-commit", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    try:
        if a.output_dir.exists():
            raise FileExistsError()
        start = perf_counter_ns()
        report = build_report(
            a.archive, a.expected_archive_sha256, a.expected_source_commit
        )
        elapsed = perf_counter_ns() - start
        overhead = {
            "consumer_parse_validate_compose_ns": elapsed,
            "scope": "this Python process monotonic; excludes rendering/publication; NOT source sampling hot path",
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
        InputError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        zipfile.BadZipFile,
        UnicodeError,
    ):
        print(
            "D1 import rejected source integrity, shape, identity or unavailable output",
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "imported_records": report["source_counts"][
                    "observed_terminal_records"
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
