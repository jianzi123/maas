// Standalone FP32 row-major starter. Untuned; NOT GPU-validated in this delivery.
// Build only after approval: nvcc -O3 -arch=sm_89 gemm.cu -lcublas -o gemm
// Run only after approval: ./gemm --approved-gpu-run 37 53 29
#include <cuda_runtime.h>
#include <cublas_v2.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <vector>
#define CU(x) do { if ((x)!=cudaSuccess) { std::fprintf(stderr,"CUDA failure\n"); std::exit(2); } } while(0)
#define BL(x) do { if ((x)!=CUBLAS_STATUS_SUCCESS) { std::fprintf(stderr,"cuBLAS failure\n"); std::exit(2); } } while(0)
__global__ void tiled_gemm(const float* a,const float* b,float* c,int m,int n,int k) {
  __shared__ float as[16][16],bs[16][16];
  int r=blockIdx.y*16+threadIdx.y,col=blockIdx.x*16+threadIdx.x;
  float sum=0;
  for(int t=0;t<(k+15)/16;t++) {
    int ak=t*16+threadIdx.x,bk=t*16+threadIdx.y;
    as[threadIdx.y][threadIdx.x]=(r<m&&ak<k)?a[r*k+ak]:0;
    bs[threadIdx.y][threadIdx.x]=(bk<k&&col<n)?b[bk*n+col]:0;
    __syncthreads();
    for(int j=0;j<16;j++) sum+=as[threadIdx.y][j]*bs[j][threadIdx.x];
    __syncthreads();
  }
  if(r<m&&col<n)c[r*n+col]=sum;
}
int main(int argc,char** argv) {
  if(argc!=5||std::string(argv[1])!="--approved-gpu-run") {
    std::fprintf(stderr,"GPU run requires explicit prior approval; expected flag and M N K\n");return 2;
  }
  int m,n,k;
  try {m=std::stoi(argv[2]);n=std::stoi(argv[3]);k=std::stoi(argv[4]);}
  catch(...) {return 2;}
  if(m<1||n<1||k<1||m>256||n>256||k>256)return 2; // bounded correctness starter
  std::vector<float>a(m*k),b(k*n),out(m*n),base(m*n);
  std::mt19937 rng(20261105);std::uniform_real_distribution<float>d(-.25f,.25f);
  for(auto&v:a)v=d(rng);for(auto&v:b)v=d(rng);
  float *ga,*gb,*gc,*gd;
  CU(cudaMalloc(&ga,a.size()*sizeof(float)));CU(cudaMalloc(&gb,b.size()*sizeof(float)));
  CU(cudaMalloc(&gc,out.size()*sizeof(float)));CU(cudaMalloc(&gd,base.size()*sizeof(float)));
  CU(cudaMemcpy(ga,a.data(),a.size()*sizeof(float),cudaMemcpyHostToDevice));
  CU(cudaMemcpy(gb,b.data(),b.size()*sizeof(float),cudaMemcpyHostToDevice));
  cublasHandle_t handle;BL(cublasCreate(&handle));BL(cublasSetMathMode(handle,CUBLAS_PEDANTIC_MATH));
  float alpha=1,beta=0;dim3 block(16,16),grid((n+15)/16,(m+15)/16);
  auto candidate=[&]{tiled_gemm<<<grid,block>>>(ga,gb,gc,m,n,k);CU(cudaGetLastError());};
  // Row-major C=A*B interpreted as column-major C^T=B^T*A^T.
  auto baseline=[&]{BL(cublasSgemm(handle,CUBLAS_OP_N,CUBLAS_OP_N,n,m,k,&alpha,gb,n,ga,k,&beta,gd,n));};
  candidate();baseline();CU(cudaDeviceSynchronize());
  CU(cudaMemcpy(out.data(),gc,out.size()*sizeof(float),cudaMemcpyDeviceToHost));
  CU(cudaMemcpy(base.data(),gd,base.size()*sizeof(float),cudaMemcpyDeviceToHost));
  double maxerr=0;
  for(int r=0;r<m;r++)for(int c=0;c<n;c++){
    double expected=0;for(int j=0;j<k;j++)expected+=double(a[r*k+j])*double(b[j*n+c]);
    maxerr=std::max(maxerr,std::abs(double(out[r*n+c])-expected));
    double tol=1e-4+2e-4*std::abs(expected);
    if(std::abs(out[r*n+c]-expected)>tol||std::abs(base[r*n+c]-expected)>tol)return 1;
  }
  for(int i=0;i<10;i++){baseline();candidate();}CU(cudaDeviceSynchronize());
  cudaEvent_t start,end;CU(cudaEventCreate(&start));CU(cudaEventCreate(&end));
  auto measure=[&](auto fn){CU(cudaEventRecord(start));for(int i=0;i<50;i++)fn();
    CU(cudaEventRecord(end));CU(cudaEventSynchronize(end));float ms;CU(cudaEventElapsedTime(&ms,start,end));return ms/50;};
  float baseline_ms=measure(baseline),candidate_ms=measure(candidate);
  std::printf("{\"evidence\":\"approved_synthetic_cuda_operator\",\"max_abs\":%.9g,\"cublas_ms\":%.9g,\"tile_ms\":%.9g,\"end_to_end_claim\":false}\n",maxerr,baseline_ms,candidate_ms);
  CU(cudaEventDestroy(start));CU(cudaEventDestroy(end));BL(cublasDestroy(handle));
  CU(cudaFree(ga));CU(cudaFree(gb));CU(cudaFree(gc));CU(cudaFree(gd));
  return 0;
}
