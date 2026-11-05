# 进阶教程：从profile到可判定的优化

前置：完成[入门B01–B06](onboarding.md)，能解释shape/dtype/layout、共同时间窗和finite门禁。本章不要求本机已有GPU；先完成源码定位、手算与实验设计，GPU阶段按批准计划执行。

学习产物是一张可评审[目标卡](templates/optimization-goal.md)，不是一组调参命令。对任何候选都要讲清：优化哪段工作、为什么可能影响主指标、用什么成熟baseline、什么证据会否定它。

## 1. 先把目标分成三层

| 层次 | 主问题 | 测量范围 | 不能跨层宣称 |
|---|---|---|---|
| K 算子 | 同shape/精度下，具体运算更快或少搬数据了吗？ | 同stream设备事件、kernel时间、logical work和实际硬件计数 | 单算子2x不等于Worker或客户端2x |
| R 运行时 | 调度/KV/Graph/通信让同一请求集合的有效吞吐改善了吗？ | Worker queue/prefill/decode、batch/缓存/graph、资源与尾延迟 | 增加GPU、缩短输出或改负载不算同条件优化 |
| E 端到端 | 改善是否传到受保护的平台调用和用户体验？ | client共同窗、Go/网关/账本边界及质量/取消/预算 | fixture或Worker均值不能替代客户端SLO内有效吞吐 |

默认主线K→R→E，E1平台归因与后端/网关协作，不重复接管其内核。八张目标卡及当前优先级见[优化目标](optimization-goals.md)。

### A01：先算收益上界，避免优化错地方

在“工作量固定、串行可归因、没有容量/队列变化”的简化模型下，热点占关键路径比例p、局部加速s：

    S_upper = 1 / ((1-p) + p/s)

教学算例，非实测：p=0.10、s=2，整体上界约1.0526；p=0.25、s=2，上界约1.1429。若想整体至少+10%，所需局部加速：

    s_required = p / (1/(1+delta) - (1-p))

分母<=0时仅优化这一段达不到目标。p=0.25、delta=0.10，至少约1.5714x。p必须来自同一可归因关键路径，不能用重叠kernel或nested span总和当比例。

<!-- smoke:A01 -->
~~~python
p, s, delta = 0.25, 2.0, 0.10
upper = 1.0 / (1.0 - p + p / s)
required = p / (1.0 / (1.0 + delta) - (1.0 - p))
print(round(upper, 4), round(required, 4))
~~~

Amdahl筛选思路参考[NVIDIA最佳实践](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html)。上例为自行推导的教学数值，不是实际吞吐预测。KV容量变化、连续批处理和排队会改变工作量/并发关系，应另建实测；Amdahl只用于筛选假设。

## 2. 先读时间线，再读单个kernel计数

阅读顺序：
1. 请求在Worker入队、选batch、prefill/decode、返回各段发生了什么？
2. CPU是否在launch/shape准备/结果处理处让GPU空转？
3. GPU忙时是哪些kernel，通信/同步是否暴露在关键路径？
4. 目标kernel在实际shape分布下占多少；某次trace是否代表总体？
5. 最后再看DRAM、指令、寄存器/shared memory、occupancy和stall。

不要把“低occupancy”直接翻译成“提高block就会更快”。寄存器复用、延迟隐藏、访存带宽、指令依赖和通信都可能限制结果。一个瓶颈假设至少要有两类互相支持的证据，如time share＋实际DRAM计数，或CPU gap＋launch时间线。

固定版本[源码分析](sglang-source-analysis-v0.5.md)提供入口。它只能说明候选路径存在；没有运行trace不能写“已经定位热点”。

## 3. GEMM：shape决定问题，不靠参数名猜

线性层常可写为A[M,K]×W[K,N]。prefill的M通常与新输入token总量有关；decode的M通常较小，取决于活跃请求与执行布局。小M可能受launch/访存/利用率影响，大M也可能受布局、精度或通信限制，不能预先一概而论。

先检查：
- M/N/K与尾部、stride/转置、输入/输出dtype，FP32是否允许TF32；
- baseline是否为当前可用的cuBLAS/torch原生或引擎成熟实现；
- 数据准备/复制、bias/激活/量化是否被某一方偷偷排除；
- TP local GEMM之后是否还有all-reduce；省掉collective不是等价优化。

16×16共享内存CUDA starter是教学/边界起点。若比cuBLAS慢，应保留结果，不能换成更弱baseline来“证明”它快。Grouped GEMM要记录各组shape及分布，不能只报总FLOP。

## 4. Attention/KV：先校验语义，再看带宽

Q[B,Hq,Sq,D]、K/V[B,Hkv,Sk,D]；GQA要求头映射正确。prefill与decode的Sq/Sk不同；suffix causal mask、滑窗、全遮罩及分页索引都是正确性的一部分。

普通MHA/GQA的KV初算：

    bytes_per_token ≈ 2 × layers × Hkv × D × element_bytes

再按所有活跃序列长度累计，并分rank核对实际布局。MLA、KV复制/分片、量化元数据和页表不能直接用该公式代替。每rank还需容纳权重、activation、graph、workspace和碎片。

dense参考能发现mask/GQA等数学错误，但不包含paged KV访问、索引生成、cache逐出、prefix合并或框架调度成本。优化方向可为减少多余contiguous/搬运、改进访问/融合或选择成熟backend；都需trace支持。

### A02：roofline应该用什么字节？

算术强度I=F/B，性能上界近似min(P_compute, Bandwidth×I)。P_compute、带宽必须匹配GPU、dtype/执行模式及测量条件。B若只是(A+B+C)逻辑字节，它给出的“有效GB/s”是代理，不能当实际DRAM流量；cache复用、重复读取、临时张量会改变硬件流量。

术语与计数器分析参考[Nsight Compute roofline指南](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html#roofline-charts)。本工具给logical work estimate，同时注明不是实测DRAM。真正判断算/存储瓶颈需计数器与时间线；profile replay的时间也不能代替正常benchmark。

## 5. RMSNorm/融合：少一次launch不等于有收益

先明确归一化维、epsilon、accumulation dtype、weight以及残差的输入/输出语义。将RMSNorm与residual/量化融合时，需核对所有输出；不能省掉输出或改变数值精度后仍叫同一计算。

成熟原生rms_norm是baseline；Triton starter的masked lane、FP32归约要先过参考。之后才研究行长、block、寄存器、占用和logical IO。小shape[3,7]只适合正确性，不代表LLM实际隐藏维度的性能。

## 6. Graph、批处理和通信要一起看代价

| 候选 | 进入证据 | 关键代价/否证点 |
|---|---|---|
| prefill切块 | J02中长输入造成decode空洞/尾部恶化 | 长prompt TTFT、队列/饥饿、调度开销；只看齐长平均值不够 |
| prefix/KV | 同H负载有可复用prefix或逐出/重算压力 | U负对照、命中匹配CPU、显存、质量/预算；U换H不是优化A/B |
| Graph | launch gap明显，实际batch可捕获 | can_run命中/fallback、padding、额外显存及冷捕获；挤压KV可能抵消收益 |
| TP/MoE | 通信暴露在关键路径或组间负载偏斜 | 总通信时间与暴露通信不同；同总GPU/拓扑对照，EP/PP扩展先审ADR |

本机单张Laptop GPU不能证明多卡/RDMA/DeepEP收益。缓存、Graph和并行布局之间有交互；先筛单因素，再对有证据的交互做小型因子实验，并明确它不再是单因素比较。

## 7. 把计时做对

- 初始化、输入生成/搬运、编译、首次调用、预热、graph capture、稳态分别记录。
- 单stream CUDA Events在正确stream上记录，end完成后读值；异步launch的host时间不是设备执行时间。
- 多stream工作要有明确依赖/完整完成边界，不能只在默认stream计一个不相干事件。
- host wall+sync和device event分列；allocator peak不等于整卡显存。
- Profiler和正式计时分开。本工作台的采样路径抑制benchmark timings，默认dry-run；受批准samples限制。
- 数值门禁要检查candidate、baseline、reference的finite，失败不进预热/计时/成功报告。[NaN修复案例](gemm-finite-fix-v0.5.1.md)展示了这类坑。

事件计时原则参考[NVIDIA GPU timers](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html#using-cuda-gpu-timers)；本地脚本仍须按其实际CUDA/工具版本核对。这里是方法课，不是GPU执行授权。实际命令和环境缺口查[算子工作台](operator-lab.md)，不要为课程修改GPU计划。

## 8. 把实验设计得能够推翻自己

### A03：保留失败和未恢复样本

所有sent都留在分母，按成功/错误/拒绝/取消/pending分层。恢复实验记录独立观察的cancel/stop/safe/evidence/release/successor时刻，以及未恢复数量和观察截止。只对恢复者报p95不能说明整体恢复更快。

缺usage和held不当actual；占用积分按维度/币种与缺观测时段记录。诊断函数不替代生产证明，也不执行退款或slot释放。

### A04：写一张可以评审的目标卡

选择[八张目标卡](optimization-goals.md)中的一张，填写：
1. 产品/运行时主指标以及它和目标kernel的关系；
2. 成熟baseline、固定shape/dtype/layout/版本/资源；
3. 至少两类进入证据；
4. 唯一改动、代价与会否定它的结果；
5. 参考误差/模型质量/业务不变量；
6. 需要批准而仍为null的门槛；
7. 原始数据、复现命令、回退及结论层级。

进阶通过标准：能够说明“什么结果下我会停止/放弃这个方向”，且不依赖弱baseline、删样本或放宽业务规则得到收益。请用[答案/评审要点](exercises/answer-key.md)自查，再进入[执行手册](optimization-playbook.md)。
