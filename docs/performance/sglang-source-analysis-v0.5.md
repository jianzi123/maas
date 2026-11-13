# SGLang 固定版本源码与候选路径

源码样本：官方tag v0.5.6，git解析的不可变提交7ae368efde14f0b2abe769a5fbb99b8154b2a9b7。选择它是为了固定可复核样本，不是部署推荐，也不代表当前最新版本或目标模型/GPU已兼容。没有安装或执行SGLang；没有下载模型权重。8份原文只存任务输入目录，仓库仅保存[URL/SHA256/符号行号索引](../../tools/perf/runtime/sglang-source-map-v0.5.json)，没有复制上游整段实现。

## 从请求调度到GPU候选

| 固定文件与入口 | 源码能确认的机制 | 应采什么，如何证伪瓶颈假设 |
|---|---|---|
| [scheduler.py L967/L992](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/managers/scheduler.py#L967) | normal循环接收/处理请求、选batch、run_batch、处理结果；overlap循环用结果队列重叠CPU处理与GPU计算，并有特定同步分支 | 看recv/选batch/结果处理的CPU时间与GPU空洞。若GPU持续繁忙且CPU很小，不能宣称调度是主瓶颈。 |
| [scheduler.py L1633/L1952](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/managers/scheduler.py#L1633)与[schedule_batch.py](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/managers/schedule_batch.py) | batch选择与执行分开，forward模式和在途状态影响路径 | 在固定J02序列下采queue、batch token分布、prefill/decode切换和未完成样本；同一工作负载比较单因素参数，不能只测齐长请求。 |
| [model_runner.py L2633](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/model_executor/model_runner.py#L2633) | forward进入_raw后先判断graph可运行性，否则按decode/split-prefill/extend/idle分派；还有MLP/attention同步准备 | 记录真实can_run_graph命中、fallback及各模式占比；graph存在不等于命中。没有launch gap时不先扩大capture集合。 |
| [cuda_graph_runner.py L449/L532/L737/L808](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/model_executor/cuda_graph_runner.py#L449) | capture、指定batch捕获、replay准备与replay分别实现 | 编译/图捕获冷成本和稳态分开；采额外显存、batch padding及replay准备CPU开销，不只采GPU图执行。 |
| [flashinfer_backend.py L698/L805](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/layers/attention/flashinfer_backend.py#L698) | extend有paged/ragged与prefix合并分支；decode调用paged KV wrapper。Q可能做contiguous，KV写入/读取与attention调用相邻；部分标量使用float避免D2H破坏capture | 区分KV写/索引/布局转换、attention kernel与merge。用真实shape/dtype/layout确认copy或带宽贡献；本轮dense/GQA微基准不覆盖分页/MLA全部成本。 |
| [radix_cache.py L340/L544](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/mem_cache/radix_cache.py#L340) | prefix匹配和逐出分开；逐出遍历可逐出叶节点并释放allocator位置，锁引用影响protected/evictable集合 | 同H负载缓存开/关，并补U负对照；采匹配CPU、命中长度、逐出/重算与KV压力。命中高不等于有效吞吐高。 |
| [memory_pool.py L106/L264](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/mem_cache/memory_pool.py#L106) | 请求/KV相关allocator有不同alloc/free接口和池实现 | 采分配失败、余量、索引搬运、碎片/回收行为；普通GQA字节公式不能直接替代MLA或每rank实际分配。 |
| [linear.py RowParallelLinear.forward L1365](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/layers/linear.py#L1365) | local linear调用quant_method.apply；满足reduce_results、TP>1且未skip时再做TP all-reduce；输入切分可伴随contiguous | 分别采GEMM、布局处理、collective和同步。单卡GEMM微基准不包含多卡通信；去掉all-reduce不是等价优化。 |

这些是已读代码的机制与待验证假设，没有时间线或热点占比，因此不宣布“某kernel已成为瓶颈”，也不写预期加速百分比。未修改上游框架或项目共享契约。

## 有依据的第一批算子实验

1. GEMM：FP32/FP16/BF16，M小的decode与M较大的prefill分别建表；先与torch.mm/cuBLAS成熟实现对照。CUDA16×16共享内存tile只是边界正确性起点，不是推荐替代cuBLAS。
2. Attention：MHA/GQA、prefill/decode，固定显式suffix causal mask；检查非方阵mask、全遮罩、KV长度尾部和布局。先以高精度参考核对PyTorch SDPA，再研究实际paged KV/backend，不把dense结果冒充FlashInfer或SGLang收益。
3. RMSNorm：作为融合/带宽型候选，Triton starter用FP32归约和masked lane，与PyTorch原生rms_norm对照；先检查寄存器/occupancy/带宽，再调整block，不宣称减少launch必然加速。
4. Grouped GEMM/MoE：本轮仅有多shape CPU正确性参考和源码路径清单；目标MoE及通信布局未确认，不提供虚构GPU测量。

正式GPU实验还需批准设备/资源/版本/采样上限及兼容CUDA PyTorch。本轮只有CPU数学参考、源码定位和禁用命令。后续版本变更必须重新解析SHA、核对文件/参数/函数，不能把latest参数直接套在v0.5.6。
