"""One bounded actual-backend smoke check, prior to performance work."""

import json, torch
from decode_path import DecodePath

if __name__ == "__main__":
    torch.set_grad_enabled(False)
    torch.cuda.set_device(0)
    torch.cuda.set_per_process_memory_fraction(0.2)
    p = DecodePath([17, 33], hq=9, hkv=3, cap=8)
    print(json.dumps({"check": p.check(), "metadata": p.metadata()}), flush=True)
