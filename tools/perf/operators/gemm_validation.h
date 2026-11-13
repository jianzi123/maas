#ifndef MAAS_PERF_GEMM_VALIDATION_H
#define MAAS_PERF_GEMM_VALIDATION_H

// This is a HOST-only correctness gate shared by CUDA and CPU regressions.
#if defined(__FAST_MATH__) || (defined(__FINITE_MATH_ONLY__) && __FINITE_MATH_ONLY__ != 0)
#error "GEMM validation requires IEEE finite checks; disable fast/finite-math-only"
#endif

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>

namespace maas_perf {
enum class ValidationFailure {
  none, invalid_input, non_finite_candidate, non_finite_baseline,
  non_finite_reference, non_finite_arithmetic, candidate_mismatch, baseline_mismatch
};

struct GemmValidation {
  bool passed;
  double candidate_max_abs;
  double baseline_max_abs;
  std::size_t failure_index;
  ValidationFailure failure;
  GemmValidation(bool ok, double candidate_error, double baseline_error,
                 std::size_t index, ValidationFailure why)
      : passed(ok), candidate_max_abs(candidate_error),
        baseline_max_abs(baseline_error), failure_index(index), failure(why) {}
};

inline GemmValidation validation_failure(ValidationFailure why, std::size_t index) {
  return GemmValidation(false, std::numeric_limits<double>::infinity(),
                        std::numeric_limits<double>::infinity(), index, why);
}

inline GemmValidation validate_gemm_results(
    const float* candidate, const float* baseline, const double* reference,
    std::size_t count, double atol = 1e-4, double rtol = 2e-4) {
  if (!candidate || !baseline || !reference || count == 0 ||
      !std::isfinite(atol) || !std::isfinite(rtol) || atol < 0 || rtol < 0) {
    return validation_failure(ValidationFailure::invalid_input, 0);
  }
  double candidate_max = 0, baseline_max = 0;
  for (std::size_t i = 0; i < count; ++i) {
    const double actual = static_cast<double>(candidate[i]);
    const double native = static_cast<double>(baseline[i]);
    const double expected = reference[i];
    if (!std::isfinite(actual))
      return validation_failure(ValidationFailure::non_finite_candidate, i);
    if (!std::isfinite(native))
      return validation_failure(ValidationFailure::non_finite_baseline, i);
    if (!std::isfinite(expected))
      return validation_failure(ValidationFailure::non_finite_reference, i);
    const double magnitude = std::abs(expected);
    if (magnitude > 0 && rtol > (std::numeric_limits<double>::max() - atol) / magnitude)
      return validation_failure(ValidationFailure::non_finite_arithmetic, i);
    const double tolerance = atol + rtol * magnitude;
    const double candidate_error = std::abs(actual - expected);
    const double baseline_error = std::abs(native - expected);
    if (!std::isfinite(tolerance) || !std::isfinite(candidate_error) ||
        !std::isfinite(baseline_error))
      return validation_failure(ValidationFailure::non_finite_arithmetic, i);
    candidate_max = std::max(candidate_max, candidate_error);
    baseline_max = std::max(baseline_max, baseline_error);
    if (candidate_error > tolerance)
      return validation_failure(ValidationFailure::candidate_mismatch, i);
    if (baseline_error > tolerance)
      return validation_failure(ValidationFailure::baseline_mismatch, i);
  }
  return GemmValidation(true, candidate_max, baseline_max, count, ValidationFailure::none);
}

// Warmup, timing and success-reporting belong INSIDE the validated continuation.
// Return 1 on every numerical rejection, without invoking the continuation.
template <typename Continuation>
int validate_then_execute(const float* candidate, const float* baseline,
                          const double* reference, std::size_t count,
                          Continuation continuation, double atol = 1e-4,
                          double rtol = 2e-4) {
  const GemmValidation result =
      validate_gemm_results(candidate, baseline, reference, count, atol, rtol);
  if (!result.passed) return 1;
  return continuation(result);
}
}  // namespace maas_perf
#endif
