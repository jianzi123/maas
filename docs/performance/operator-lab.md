# 算子正确性、微基准与Profiler工作台

本任务主线是GPU算子和真实推理运行时。工具在[operators目录](../../tools/perf/operators)，计划默认execution_enabled=false；CPU公式只做独立数值oracle，不计为GPU/模型性能交付。

## 当前首项：Decode Attention与KV读取

研究入口复用SGLang固定v0.5.6 / 7ae368e的flashinfer_backend.forward_decode路径（详见[固定源码分析](sglang-source-analysis-v0.5.md)），将KV索引/写入/布局准备、paged wrapper执行与实际GPU kernel分开。该版本只是可复核源码样本；目标引擎版本、模型及backend未确认，不认定它是已上线环境。

现有decode-llm用B=4、Hq=16、Hkv=4、Sq=1、Sk=2048、D=128、FP16，是代表性合成shape，不冒充从目标模型采集的分布。连续K+V载荷约16MiB，只是张量容量，不是实际DRAM流量或整卡显存上限。先复用它验证设备计时、后缀causal/GQA数值及实际选中backend；torch模式candidate=baseline是计时control，不能报告优化收益。

GPU条件满足后分两步：先给出该dense control的原始CUDA Events、独立采样trace、误差和显存；再按实际SGLang profile的shape/page/layout与原生paged backend作同条件对照。dense SDPA不代替paged KV或完整引擎。没有原生paged采样时登记缺口，不继续写CPU分页模拟器作为替代。

只有timeline/计数器支持时才选一项等价改动：例如确实暴露的Q contiguous拷贝、KV布局准备或backend参数。若没有该开销，淘汰该假设。后续GEMM、CUDA Graph、TP/EP通信同样先确认热点；不通过去掉collective、改变精度或降低输出语义制造收益。

K1不以Go/Higress接通为前置；R层需要获准模型、真实引擎/权重/质量约束；E层另验证受保护平台。产出按设备时延/实际计数器→引擎TTFT/TPOT/有效吞吐→客户端收益分层，不再用CPU测试数作为主进度。

下面三条只生成已有GPU采样命令，不执行GPU：

~~~text
python tools/perf/operators/profile_operator.py --tool torch --case decode-llm --output-dir tools/perf/reports/decode-profile-torch
python tools/perf/operators/profile_operator.py --tool nsys --case decode-llm --output-dir tools/perf/reports/decode-profile-nsys
python tools/perf/operators/profile_operator.py --tool ncu --case decode-llm --output-dir tools/perf/reports/decode-profile-ncu
~~~

真正执行仍需批准计划、干净兼容的CUDA运行库与资源上限；设备计时与profiler采样分开。源码分析与命令准备不等于已完成GPU实验。

## 本机只读核查与具体缺口

- nvidia-smi报告RTX4070 Laptop、8188MiB、驱动581.29；nvcc报告CUDA13.0.88。
- 2026-11-13只读复核：PATH有Nsight Compute2025.3.1的bat入口，实际exe位于其target/windows-desktop-win7-x64/ncu.exe；执行器要求真实exe位于获准进程PATH，不修改全局环境。Nsight Systems在当前PATH未发现；Triton安装状态沿历史记录，本轮未重查。
- 安装元数据为PyTorch2.9.1，version.py明确2.9.1+cpu、cuda=None；导入时实际遇到重复libiomp5md OpenMP错误。没有设置KMP_DUPLICATE_LIB_OK绕过。
- NumPy2.3.5、Python3.13.9 CPU参考可运行。没有分配GPU张量、编译/执行CUDA或Triton，CUDA host编译器与实际Profiler计数权限也未验证。

“有显卡”不等于本次GPU实验授权或完整工具链。后续需兼容CUDA PyTorch、干净运行库、可选Triton、明确approval_ref/target_environment、数据内存估算/预热/样本上限、设备频率功耗策略。真实框架实验还需模型/权重/profile和批准SLO/业务限制。

## 数值oracle（支持工作，不是性能基线）

    python tools/perf/operators/bench.py --output tools/perf/reports/operator-cpu.json
    python -m unittest discover -s tools/perf -p "test_operator_runtime.py" -v

8个小shape：尾部与strided GEMM；MHA/GQA、decode/prefill、cross、strided Attention；尾部与strided RMSNorm。CPU执行一律float64，比较独立公式/online-softmax与向量化参考，报告只含数值误差，不报GPU或CPU性能。

Grouped GEMM有CPU列表参考；CUDA starter仅普通FP32 GEMM；Triton starter仅连续CUDA RMSNorm。GPU低精度、分页KV、MLA、分布式通信、模型质量均未验证。

## 数值与布局约定

Attention为B,H,S,D；支持Hq是Hkv整数倍的GQA，V维度目前等于K维度。causal query位于KV序列尾部：q位置=Sk−Sq+index；Sq=1的decode可见所有既有KV。全遮罩行定义为零，不能让NaN通过。实际引擎特殊mask/滑窗/MLA需另建参考。

plan.json中的dtype误差阈值是待评审算子检查起点，不是模型质量容忍；当前CPU只验证float64参考。GPU starter只接受contiguous，strided已在CPU oracle覆盖；不会暗中复制后宣称测了原layout。GPU结果要保存实际stride、dtype、库版本、误差与不支持项。

## 获准后才运行GPU

复制计划后由授权流程填写approval_ref、target_environment与gpu_limits并显式启用。max_estimated_data_bytes仅估算输入/参考数据，不包含CUDA context、library workspace等，不能当设备显存强隔离；真实资源监控另行设置。

    python tools/perf/operators/bench.py --plan <approved-plan.json> --mode gpu --case prefill-gqa --backend torch --output <run>/operator.json
    python tools/perf/operators/bench.py --plan <approved-plan.json> --mode gpu --case norm-tail --backend triton --output <run>/operator.json

torch后端默认是同后端control：torch.mm、SDPA auto或原生rms_norm。它用于验证计时与参考，不能称新优化。Triton RMSNorm才与成熟原生baseline比较；CUDA文件用cuBLAS pedantic FP32作baseline并核对CPU double参考。dtype/shape/layout相同，TF32关闭；SDPA实际选中的backend仍须由trace确认。

每次GPU执行先正确性，失败不产生性能结论；记录首次调用host时间、预热、交错的baseline/candidate设备事件时长和host wall+sync。CUDA Events在同一stream记录，end同步后读值。分配、CPU高精度参考和编译/预热不混入稳态；allocator peak不是整卡显存。GPU算子时长不是客户端TTFT/TPOT。

CUDA starter的执行命令（仅获准后）：

    nvcc -O3 -arch=sm_89 tools/perf/operators/gemm.cu -lcublas -o <run>/gemm
    <run>/gemm --approved-gpu-run 37 53 29

sm_89只对应当前已查到设备的候选编译目标，不作为其他GPU默认值；host编译器/CUDA/cuBLAS版本仍须核验。本程序限M/N/K≤256，作为正确性/采样起点，不覆盖完整LLM尺寸。

## Profiler采样

默认只输出argv，不启动Profiler或GPU：

    python tools/perf/operators/profile_operator.py --tool torch --output-dir tools/perf/reports/proposed-profile
    python tools/perf/operators/profile_operator.py --tool nsys --output-dir tools/perf/reports/proposed-profile
    python tools/perf/operators/profile_operator.py --tool ncu --output-dir tools/perf/reports/proposed-profile

真正采样需指定已获准计划并加--execute，samples至少为4以容纳固定采样窗口；更小的样本上限会在导入框架前拒绝。ncu使用NVTX maas_candidate范围、basic集合、最多5个kernel launch；nsys记录CUDA/NVTX/OS runtime；torch profiler固定wait/warmup/active窗口并输出Chrome trace。外部Profiler走instrumented模式，内部Profiler走profile-dir模式，二者均抑制基准timings，不能拿重放/采样时间算收益。

本机ncu是bat入口，执行器会拒绝shell wrapper；获准环境需将实际ncu.exe放入PATH，不拼接cmd脚本。没有任意外部目标程序或模型端点启动参数。

先用Nsight Systems看CPU launch/同步/通信空洞，再用Nsight Compute定位kernel的SM/DRAM、寄存器、shared memory、occupancy；roofline须配实际字节/FLOP及目标GPU可用指标，不能仅凭低occupancy判瓶颈。采样开销与正式基准独立，所有rank/profile修订可追踪。

官方依据：[PyTorch2.9 SDPA](https://docs.pytorch.org/docs/2.9/generated/torch.nn.functional.scaled_dot_product_attention.html)、[Profiler](https://docs.pytorch.org/docs/2.9/profiler.html)、[Triton教程](https://triton-lang.org/main/getting-started/tutorials/01-vector-add.html)、[Nsight Compute](https://docs.nvidia.com/nsight-compute/NsightComputeCli/index.html)、[Nsight Systems](https://docs.nvidia.com/nsight-systems/UserGuide/index.html)。本轮只执行了CPU/离线检查与dry-run，未验证GPU API实际可用性。

源码字节和定位可复验（仅解析，不导入上游）：

    python tools/perf/runtime/source_audit.py --source-root <downloaded-fixed-sha-root> --output <run>/source-audit.json

GPU结果同时给logical_dense_flops_estimate和logical_io_bytes_estimate，GEMM约2MNK、dense Attention约4B×Hq×Sq×Sk×D，尚不包含softmax/分页/通信。用估算工作量除设备事件时长只能得逻辑TFLOP/s或IO GB/s，不能冒充实际DRAM带宽或完整roofline。真正缓存命中、DRAM字节和指令需由对应GPU的计数器采集。

## CUDA GEMM finite 门禁（本轮修复）

旧NaN误放行已改为CUDA/宿主共用gemm_validation.h与validate_then_execute：candidate、cuBLAS、reference必须全部finite，数值失败在任何预热/计时/成功报告前退出1。独立宿主回归无需CUDA：

    python tools/perf/operators/check_gemm_host.py --output tools/perf/reports/gemm-host.json

21个运行场景（17拒绝、4正常）及fast-math拒绝编译由[有限值修复记录](gemm-finite-fix-v0.5.1.md)说明。需要现有GCC/Clang兼容C++编译器；完整Python回归将包含这一宿主组，缺编译器明确skip，不得算成宿主验证通过。本轮只编译宿主header/driver，仍未编译CUDA translation unit或执行GPU算子。
