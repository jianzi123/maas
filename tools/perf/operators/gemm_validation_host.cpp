// CPU-only process fixture. Uses the EXACT gate included by gemm.cu.
#include "gemm_validation.h"
#include <array>
#include <cstdio>
#include <limits>
#include <string>

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  const std::string scenario(argv[1]);
  std::array<float, 3> candidate = {{1, 2, 3}}, baseline = {{1, 2, 3}};
  std::array<double, 3> reference = {{1, 2, 3}};
  double atol = 1e-4, rtol = 2e-4;
  std::size_t count = candidate.size();
  const float nan = std::numeric_limits<float>::quiet_NaN();
  const float inf = std::numeric_limits<float>::infinity();
  if (scenario == "normal_exact") {}
  else if (scenario == "normal_tolerance") candidate[1] += 1e-5f;
  else if (scenario == "normal_signed_zero") candidate[0] = -0.0f, baseline[0] = 0, reference[0] = 0;
  else if (scenario == "tolerance_boundary") candidate[1] = 3, atol = 1, rtol = 0;
  else if (scenario == "original_nan_fixture") candidate[0] = nan, count = 1;
  else if (scenario == "candidate_nan") candidate[1] = nan;
  else if (scenario == "candidate_pos_inf") candidate[1] = inf;
  else if (scenario == "candidate_neg_inf") candidate[1] = -inf;
  else if (scenario == "baseline_nan") baseline[1] = nan;
  else if (scenario == "baseline_pos_inf") baseline[1] = inf;
  else if (scenario == "baseline_neg_inf") baseline[1] = -inf;
  else if (scenario == "reference_nan") reference[1] = std::numeric_limits<double>::quiet_NaN();
  else if (scenario == "reference_pos_inf") reference[1] = std::numeric_limits<double>::infinity();
  else if (scenario == "reference_neg_inf") reference[1] = -std::numeric_limits<double>::infinity();
  else if (scenario == "late_candidate_nan") candidate[2] = nan;
  else if (scenario == "candidate_wrong") candidate[1] = 1234;
  else if (scenario == "baseline_wrong") baseline[1] = -1234;
  else if (scenario == "atol_nan") atol = std::numeric_limits<double>::quiet_NaN();
  else if (scenario == "rtol_inf") rtol = std::numeric_limits<double>::infinity();
  else if (scenario == "negative_tolerance") atol = -1;
  else if (scenario == "tolerance_overflow") rtol = std::numeric_limits<double>::max();
  else return 2;

  int warmup = 0, timing = 0, reporting = 0;
  const int status = maas_perf::validate_then_execute(
      candidate.data(), baseline.data(), reference.data(), count,
      [&](const maas_perf::GemmValidation& validation) {
        ++warmup; ++timing; ++reporting;
        std::printf("{\"validation\":\"passed\",\"host_gate_only\":true,"
                    "\"candidate_max_abs\":%.9g,\"baseline_max_abs\":%.9g}\n",
                    validation.candidate_max_abs, validation.baseline_max_abs);
        return 0;
      }, atol, rtol);
  std::fprintf(stderr, "host_gate status=%d warmup=%d timing=%d reporting=%d\n",
               status, warmup, timing, reporting);
  return status;
}
