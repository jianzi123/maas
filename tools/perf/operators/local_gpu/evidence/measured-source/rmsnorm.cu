#include <cuda_fp16.h>
// Teaching baseline: one thread per row, FP32 accumulation, no fast-math.
extern "C" __global__ void rms_serial(const float* x, const float* weight,
                                      float* out, int rows, int width, float eps) {
    int row = blockIdx.x * blockDim.x + threadIdx.x;
    if (row >= rows) return;
    float sum = 0.0f;
    for (int j = 0; j < width; ++j) {
        float v = x[row * width + j];
        sum += v * v;
    }
    float scale = rsqrtf(sum / width + eps);
    for (int j = 0; j < width; ++j)
        out[row * width + j] = x[row * width + j] * scale * weight[j];
}

extern "C" __global__ void rms_serial_half(const __half* x, const __half* weight,
                                           __half* out, int rows, int width, float eps) {
    int row = blockIdx.x * blockDim.x + threadIdx.x;
    if (row >= rows) return;
    float sum = 0.0f;
    for (int j = 0; j < width; ++j) {
        float v = __half2float(x[row * width + j]);
        sum += v * v;
    }
    float scale = rsqrtf(sum / width + eps);
    for (int j = 0; j < width; ++j)
        out[row * width + j] = __float2half_rn(__half2float(x[row * width + j]) * scale * __half2float(weight[j]));
}

extern "C" __global__ void rms_block_half(const __half* x, const __half* weight,
                                          __half* out, int rows, int width, float eps) {
    int row = blockIdx.x, tid = threadIdx.x, lane = tid & 31, warp = tid >> 5;
    if (row >= rows) return;
    __shared__ float partial[8];
    __shared__ float scale;
    float sum = 0.0f;
    for (int j = tid; j < width; j += 256) {
        float v = __half2float(x[row * width + j]);
        sum += v * v;
    }
    for (int offset = 16; offset; offset >>= 1)
        sum += __shfl_down_sync(0xffffffff, sum, offset);
    if (lane == 0) partial[warp] = sum;
    __syncthreads();
    if (warp == 0) {
        sum = lane < 8 ? partial[lane] : 0.0f;
        for (int offset = 16; offset; offset >>= 1)
            sum += __shfl_down_sync(0xffffffff, sum, offset);
        if (lane == 0) scale = rsqrtf(sum / width + eps);
    }
    __syncthreads();
    for (int j = tid; j < width; j += 256)
        out[row * width + j] = __float2half_rn(__half2float(x[row * width + j]) * scale * __half2float(weight[j]));
}

// Profile-guided change: consecutive lanes read consecutive columns; reduce
// within warps, then combine the eight warp partials. One block owns one row.
extern "C" __global__ void rms_block(const float* x, const float* weight,
                                     float* out, int rows, int width, float eps) {
    int row = blockIdx.x, tid = threadIdx.x, lane = tid & 31, warp = tid >> 5;
    if (row >= rows) return;
    __shared__ float partial[8];
    __shared__ float scale;
    float sum = 0.0f;
    for (int j = tid; j < width; j += 256) {
        float v = x[row * width + j];
        sum += v * v;
    }
    for (int offset = 16; offset; offset >>= 1)
        sum += __shfl_down_sync(0xffffffff, sum, offset);
    if (lane == 0) partial[warp] = sum;
    __syncthreads();
    if (warp == 0) {
        sum = lane < 8 ? partial[lane] : 0.0f;
        for (int offset = 16; offset; offset >>= 1)
            sum += __shfl_down_sync(0xffffffff, sum, offset);
        if (lane == 0) scale = rsqrtf(sum / width + eps);
    }
    __syncthreads();
    for (int j = tid; j < width; j += 256)
        out[row * width + j] = x[row * width + j] * scale * weight[j];
}
