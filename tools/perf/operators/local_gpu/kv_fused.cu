// Inference research kernel: exact bitwise copy, no precision conversion.
// One launch writes K and V. Input locations are unique and prevalidated by
// the bounded harness. A bad raw-op location traps before any out-of-bounds access.
extern "C" __global__ void kv_fused_u16(
    unsigned short* k_cache, unsigned short* v_cache,
    const long long* locations, const unsigned short* k,
    const unsigned short* v, long long count, long long width, long long rows) {
  long long i = (long long)blockIdx.x * blockDim.x + threadIdx.x;
  if (i < count) {
    long long row = locations[i / width];
    if (row < 0 || row >= rows) { asm("trap;"); return; }
    long long offset = row * width + i % width;
    k_cache[offset] = k[i];
    v_cache[offset] = v[i];
  }
}
