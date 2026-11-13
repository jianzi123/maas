"""Produce a fresh local JSON+HTML diagnostic report, no network or model execution."""

import argparse, json, os, sys, uuid
from pathlib import Path

if __package__:
    from .validation import load_json, DiagnosticError, InputError
    from .report import compose
    from .html_report import render
else:
    from validation import load_json, DiagnosticError, InputError
    from report import compose
    from html_report import render


def publish(directory, report, extra_files=None):
    directory = Path(directory)
    # Validate/serialize/render before creating any published output.
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    page = render(report)
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = directory.with_name(directory.name + ".pending-" + uuid.uuid4().hex)
    staging.mkdir()
    try:
        files = {"report.json": encoded, "report.html": page}
        for name, body in (extra_files or {}).items():
            if name in files or name not in ("consumer-import-overhead.json",):
                raise ValueError("extra output name")
            files[name] = body
        for name, body in files.items():
            with (staging / name).open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        # Never replace an existing report directory.
        if directory.exists():
            raise FileExistsError("fresh output directory required")
        os.rename(staging, directory)
    finally:
        if staging.exists():
            for name in ("report.json", "report.html", "consumer-import-overhead.json"):
                (staging / name).unlink(missing_ok=True)
            staging.rmdir()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--metrics-input", type=Path, required=True)
    p.add_argument("--timeline-input", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    try:
        if a.output_dir.exists():
            raise FileExistsError()
        dataset, h = load_json(a.metrics_input)
        sidecar, sidecar_input_sha256 = load_json(a.timeline_input)
        result = compose(dataset, sidecar, h)
        result["sidecar_input_sha256"] = sidecar_input_sha256
        publish(a.output_dir, result)
    except (
        DiagnosticError,
        InputError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RecursionError,
    ):
        # No raw payload, JSON schema values, path, exception or input sentinel in errors.
        print(
            "diagnostic import rejected invalid input or unavailable local output",
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "report": "diagnostic-report-1.0",
                "synthetic": result["synthetic"],
                "model_bottleneck": None,
                "real_execution_enabled": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
