# GEMM 分块实现与成熟基线

GEMM常写成C=A[M,K]B[K,N]。优化必须同时决定输出如何分给线程、输入如何复用、尾部如何处理，以及接口要求的布局和精度。先实现一个确切的版本，再比较不同分工。

## CPU 分块版本实际做了什么

[tiled_gemm](../../../tools/perf/engineering/layout_lab.py)已实现三层tile循环。输出按tm×tn分块，K每次tk；最后的部分tile由真实slice长度处理。输入可以是不连续view，测试使用A[37,58][:,::2]与B[58,53][::2,:]，最终问题为37×29乘29×53。

~~~python
for i in range(0, M, tm):
    for j in range(0, N, tn):
        acc = zeros(min(tm,M-i), min(tn,N-j))
        for start in range(0, K, tk):
            acc += A[i:i+tm,start:start+tk] @ B[start:start+tk,j:j+tn]
        C[i:i+tm,j:j+tn] = acc
~~~

这是可运行的CPU算法，不把NumPy局部matmul时间解释为GPU tile性能。它用于验证分块、尾部和stride语义；成熟完整matmul作为独立数学对照。K=0按本CPU接口返回全0，GPU接口支持哪些空shape需要另外规定。

## 将输出分工扩展到 CUDA

已有[CUDA骨架](../../../tools/perf/operators/gemm.cu)每block处理16×16输出。37/53/29时grid为3×4，K循环2次，末行/列/K有效长度为5/5/13。有效FLOP=113738；补齐形状的运算不能作为额外有效工作。

要提高复用，可让每线程计算多个输出，例如block输出64×64而线程仍256，每线程持有若干accumulator。好处是一次载入可服务更多乘加，代价是寄存器、指令和尾部浪费。warp tile与每线程tile必须一起推导覆盖，确保每个C元素恰有一个写者。

若block tile为BM×BN，K分块为BK，单缓冲shared字节近似(BM*BK+BK*BN)*element_bytes；双缓冲再乘2。accumulator寄存器至少随每线程输出元素数增长，编译器实际分配还包含地址、循环和临时值。不要仅按shared容量选择tile。

## Triton 中的指针与 program 不是同一个抽象

Triton的一个program处理一个输出tile，指针矩阵由行列offset和stride广播生成。mask要分别覆盖M、N、K；不能只在最终store遮罩，却让K尾部load越界。调度program顺序可能改善L2复用，但效果取决于shape和cache状态。

自动调参也要有边界：固定候选tile/warps/stages、预热与编译范围，记录选中的配置及适用shape。不能把候选的最佳单次与baseline正常分布比较，也不能把首次JIT排除后隐藏其实际服务成本。概念参考[官方matmul教程](https://triton-lang.org/main/getting-started/tutorials/03-matrix-multiplication.html)；本仓库现有Triton实现是[RMSNorm](../../../tools/perf/operators/triton_rmsnorm.py)，没有声称本CPU分块已经编译成Triton GEMM。

## 行列主序与 leading dimension 的具体检查

连续行主序C=A×B可转成列主序视图Cᵀ=BᵀAᵀ。给经典cuBLAS接口时，相应输出形状是N×M，两个连续视图的leading dimension为N和K，输出为N。若A来自每隔一列的view，不能沿用连续stride；应先记录真实stride、进行等价打包或使用确切支持该布局的接口。

打包/转置的成本应按实际使用方式计算。每请求重新打包权重与加载时一次打包不是同一问题；权重预打包还增加副本和发布工件。benchmark范围要说明权重是否已驻留、是否已转置、workspace是否复用。

## 精度路径和公平对照

输入dtype、乘法路径、累加dtype与输出dtype分别固定。FP32输入可能走允许TF32的成熟库路径；若候选用更低精度却把差异隐去，比较不公平。量化权重还要比较scale、反量化、融合输出和模型质量。

CPU float64回归使用约1e-12级误差检查分块数学；它不提供FP16/BF16/TF32的模型容忍阈值。candidate、成熟baseline、reference都先finite，再按预登记atol/rtol检查。共用[finite门禁](../../../tools/perf/operators/gemm_validation.h)失败时不进入预热/计时。

## 从 small M 到 Grouped GEMM 的决策

小M时，权重复用少、launch和准备可能显著；M较大时，计算与复用方式改变。取K=N=4096、float32的理想读写代理，M=1约0.50 FLOP/byte，M=128约60.24。实际DRAM流量需硬件测量，不由公式代替。

MoE的Grouped GEMM需要记录每组M/N/K与空组比例。把多个小组打成一个调度，可能节约launch，但重排、metadata、负载偏斜、逆排列与通信也要计入。第8章给出了可运行的dispatch/combine参考。

作业：为三种实际shape分布写tile与准备范围，说明哪项证据会使你放弃自研kernel。只能战胜naive实现时应保留该结果，下一步仍以成熟库为对照。

接口依据：[cuBLAS](https://docs.nvidia.com/cuda/cublas/index.html)。本节分工、资源与算术强度推导是教学模型，现阶段未编译运行新增GPU kernel。
