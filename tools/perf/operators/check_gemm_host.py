#!/usr/bin/env python3
"""Compile/run the shared GEMM numerical gate on the HOST only, without CUDA."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLAGS = ["-std=c++11", "-O2", "-fno-fast-math", "-Wall", "-Wextra", "-Werror", "-pedantic"]
PASS_CASES = ("normal_exact", "normal_tolerance", "normal_signed_zero", "tolerance_boundary")
REJECT_CASES = (
    "candidate_nan", "candidate_pos_inf", "candidate_neg_inf",
    "baseline_nan", "baseline_pos_inf", "baseline_neg_inf",
    "reference_nan", "reference_pos_inf", "reference_neg_inf",
    "late_candidate_nan", "candidate_wrong", "baseline_wrong",
    "atol_nan", "rtol_inf", "negative_tolerance", "tolerance_overflow", "original_nan_fixture")


def compiler_path():
    for name in ("g++", "clang++", "c++"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("GCC/Clang-compatible host C++ compiler required")


def compile_fixture(directory, compiler=None, fast_math=False):
    compiler = compiler or compiler_path()
    output = Path(directory) / ("fast-math" if fast_math else "gemm-host")
    if os.name == "nt":
        output = output.with_suffix(".exe")
    command = [compiler] + FLAGS
    if fast_math:
        command.append("-ffast-math")
    command += [str(HERE / "gemm_validation_host.cpp"), "-o", str(output)]
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    return output, result


def run_scenario(binary, scenario):
    result = subprocess.run([str(binary), scenario], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=10)
    should_pass = scenario in PASS_CASES
    counters = "warmup=1 timing=1 reporting=1" if should_pass else "warmup=0 timing=0 reporting=0"
    passed = result.returncode == (0 if should_pass else 1) and counters in result.stderr
    if should_pass:
        try:
            report = json.loads(result.stdout)
            passed = passed and report["validation"] == "passed" and report["host_gate_only"] is True
        except (ValueError, KeyError):
            passed = False
    else:
        passed = passed and result.stdout == ""
    return {"scenario": scenario, "expected_exit": 0 if should_pass else 1,
            "exit_code": result.returncode, "stdout": result.stdout,
            "stderr": result.stderr, "passed": passed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    compiler = compiler_path()
    with tempfile.TemporaryDirectory(prefix="gemm-host-", dir=HERE) as directory:
        binary, build = compile_fixture(directory, compiler)
        if build.returncode:
            raise RuntimeError("host fixture compilation failed")
        cases = [run_scenario(binary, name) for name in PASS_CASES + REJECT_CASES]
        _, unsafe = compile_fixture(directory, compiler, fast_math=True)
        fast_math_rejected = unsafe.returncode != 0 and "requires IEEE finite checks" in unsafe.stderr
    version = subprocess.run([compiler, "--version"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=10)
    report = {"kind": "shared_gemm_validation_host_regression",
              "compiler": version.stdout.splitlines()[0], "flags": FLAGS,
              "host_only": True, "cuda_translation_unit_compiled": False,
              "gpu_executed": False, "scenario_count": len(cases), "scenarios": cases,
              "fast_math_build_rejected": fast_math_rejected,
              "passed": all(row["passed"] for row in cases) and fast_math_rejected}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"scenarios": len(cases), "passed": report["passed"],
                      "fast_math_build_rejected": fast_math_rejected, "gpu_executed": False}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
