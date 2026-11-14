"""Read-only GPU/dependency probe; no model download or global mutation."""
import importlib.metadata as md
import json
import pathlib
import platform
import subprocess

out = {"python": platform.python_version(), "platform": platform.platform()}
out["packages"] = {}
for name in ("torch", "triton", "cupy-cuda12x", "numpy", "vllm", "sglang", "sgl-kernel"):
    try:
        out["packages"][name] = md.version(name)
    except md.PackageNotFoundError:
        out["packages"][name] = None
try:
    import torch
    out["torch"] = {"version": torch.__version__, "cuda": torch.version.cuda,
                    "available": torch.cuda.is_available()}
    if torch.cuda.is_available():
        x = torch.arange(32, device="cuda", dtype=torch.float32)
        out["torch"].update(name=torch.cuda.get_device_name(),
                            capability=torch.cuda.get_device_capability(),
                            memory_free_total=torch.cuda.mem_get_info(),
                            smoke_sum=x.sum().item())
    import cupy as cp
    from cupy.cuda import nvrtc
    out["cupy"] = {"version": cp.__version__, "nvrtc": nvrtc.getVersion()}
except Exception as e:
    out["gpu_error"] = str(e)
cache = pathlib.Path.home() / ".cache/huggingface/hub"
out["default_hf_cache_models"] = sorted(p.name for p in cache.glob("models--*"))
out["nvidia_smi"] = subprocess.check_output([
    "nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.free,pstate,power.limit",
    "--format=csv,noheader"], text=True).strip()
print(json.dumps(out, indent=2))
