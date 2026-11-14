# Failure excerpts
Excerpts from actual tool returns, not complete stdout/stderr.
- Empty graph: The CUDA Graph is empty. This usually means that the graph was attempted to be captured on wrong device or stream.
  serial/report.json graph timing is INVALID, including its passed label.
- venv: ensurepip is not available.
- Truncated official wheel: expected SHA256 83aae146f3913ed0802bb1ea356facff47efe0e7d18041a3f143de9ef6e44b2c, got 65e384ea2ac1b87bd0934468adf42913ba12e15c178258d0da4ea021868f5c58. Progress stopped at 1.3/2.2MB. No hash bypass.
- Mature FP32: failed to dispatch data type Float; no timing report.
- FlashInfer 0.3.1 sdist: metadata project name unknown; resolver discarded it.
- pip22: sglang 0.5.2 does not provide the extra runtime_common; use runtime-common.
- Final Engine import passed; blocked_missing_model_weights; generation false.
- Isolated shadow installs conflict with inherited vLLM xgrammar/outlines pins; global distributions were not uninstalled.

Valid final reports: fp32-final/report.json and fp16-final/report.json.
serial-fixed/optimized are exploratory results under earlier source hashes.
No generated-model or platform performance result exists.
