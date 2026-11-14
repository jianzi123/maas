// ATen dispatcher -> CUDA driver launch. Python binding supplies PyTorch's
// CURRENT stream on every call; never cache the stream at bind/capture time.
// Device code is NVRTC, not nvcc. No pybind entry point; torch build ABI pinned.
#include <ATen/ATen.h>
#include <ATen/MemoryOverlap.h>
#include <torch/library.h>
#include <cuda.h>
#include <cstdint>

void write_kv(at::Tensor kc, at::Tensor vc, const at::Tensor& loc,
              const at::Tensor& k, const at::Tensor& v, int64_t handle, int64_t stream_handle) {
  TORCH_CHECK(kc.is_cuda() && vc.is_cuda() && loc.is_cuda() &&
              k.is_cuda() && v.is_cuda(), "CUDA tensors required");
  for (const auto& t : {vc, loc, k, v}) {
    TORCH_CHECK(t.device() == kc.device(), "same CUDA device required");
  }
  TORCH_CHECK(kc.dim()==3 && vc.sizes()==kc.sizes() && k.dim()==3 &&
              v.sizes()==k.sizes() && k.size(1)==kc.size(1) &&
              k.size(2)==kc.size(2) && loc.dim()==1 && loc.numel()==k.size(0),
              "incompatible KV shapes");
  TORCH_CHECK(loc.scalar_type()==at::kLong, "int64 locations required");
  TORCH_CHECK((kc.scalar_type()==at::kHalf || kc.scalar_type()==at::kBFloat16) &&
              vc.scalar_type()==kc.scalar_type() && k.scalar_type()==kc.scalar_type() &&
              v.scalar_type()==kc.scalar_type(), "matching FP16/BF16 required");
  for (const auto& t : {kc,vc,loc,k,v}) {
    TORCH_CHECK(t.is_contiguous(), "contiguous tensors required");
    TORCH_CHECK(!t.requires_grad(), "inference-only");
  }
  TORCH_CHECK(k.numel()<=65536 && kc.numel()<=20000LL*4*128 &&
              kc.size(0)>0 && handle>0, "bounded research operator");
  at::assert_no_overlap(kc,vc);
  at::assert_no_overlap(kc,k); at::assert_no_overlap(kc,v);
  at::assert_no_overlap(vc,k); at::assert_no_overlap(vc,v);
  TORCH_CHECK(kc.get_device()==0 && stream_handle>=0, "local device0 research binding");
  long long count=k.numel(), width=k.size(1)*k.size(2), rows=kc.size(0);
  if (!count) return;
  auto kp=kc.data_ptr(); auto vp=vc.data_ptr();
  auto lp=loc.data_ptr(); auto src_k=k.data_ptr(); auto src_v=v.data_ptr();
  void* args[]={&kp,&vp,&lp,&src_k,&src_v,&count,&width,&rows};
  CUresult result=cuLaunchKernel(reinterpret_cast<CUfunction>(handle),
      (count+255)/256,1,1,256,1,1,0,reinterpret_cast<CUstream>(stream_handle),args,nullptr);
  if (result!=CUDA_SUCCESS) {
    const char* message=nullptr; cuGetErrorString(result,&message);
    TORCH_CHECK(false,"CUDA driver launch failed: ",message?message:"unknown");
  }
  // Execution errors are asynchronous; the harness synchronizes/checks output.
}
TORCH_LIBRARY(maas_decode_kv,m) {
  m.def("write(Tensor(a!) kc, Tensor(b!) vc, Tensor locations, Tensor k, Tensor v, int kernel_handle, int stream_handle) -> ()");
}
TORCH_LIBRARY_IMPL(maas_decode_kv,CUDA,m) {
  m.impl("write",&write_kv);
}
