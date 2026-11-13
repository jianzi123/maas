# GPU 执行与访存的可计算模型

一次 kernel 优化应落到线程做了什么、哪些地址被访问、哪些资源限制并发。先把地址和工作量写出来，再用 profiler 检查硬件是否按假设执行。本章使用显式假设的教学模型，数值不作为某张 GPU 的硬件规格或性能结果。

## 一个 warp 的连续加载为什么是四个 sector

设 32 个 lane 各读一个4字节数，lane i 的地址为 base+4i，sector=32字节。base=0时访问字节0到127，覆盖sector0到3，共4个；base=4时访问4到131，跨到sector4，共5个。有效数据同为128字节，模型内请求的sector字节从128增到160，利用率从100%降到80%。

[layout_lab.sectors](../../../tools/perf/engineering/layout_lab.py)逐字节枚举覆盖集合，处理元素跨sector的情况。它不是运行GPU counter；真实请求合并、缓存命中与重复访问会影响DRAM流量。连续索引也不保证每条指令连续：若线程按列读取行主序矩阵，地址步长可能是整行。

给定矩阵X[M,N]与stride，先写 byte_address=base+(row*stride_row+col*stride_col)*element_bytes。对同一条指令列出32个lane地址，检查对齐、有效mask和访问跨度。向量化需要同时满足地址、stride、长度和类型约束；对齐不满足时强行reinterpret_cast可能破坏正确性。

## 共享内存的 bank 与广播要分开

教学假设为32个bank、4字节word，bank(word_address)=word_address mod 32。

- 读同一列且行stride=32word：lane i读word32i，均落bank0，但地址不同，模型冲突度为32。
- 行stride改为33：bank(33i)=i mod32，模型冲突度为1。
- 32个lane读同一个word0：按同址广播处理，冲突度为1，而不是32。

[bank_conflict_degree](../../../tools/perf/engineering/layout_lab.py)用每个bank的不同word集合计算这个模型，专门保留同址广播例外。它只描述32位读取假设；64/128位向量、多次实际事务、写入和不同架构必须重新分析。padding节约冲突，却增加共享内存占用，可能减少驻留block。

## Occupancy 的上界怎样算

以虚构SM参数演算：65536个32位寄存器，2048线程上限，每block256线程，每线程64寄存器，最多32block。忽略分配粒度时：

~~~text
寄存器允许block数 = floor(65536 / (256*64)) = 4
线程允许block数   = floor(2048 / 256) = 8
上界block数       = min(4,8,32) = 4
线程occupancy上界 = 4*256/2048 = 50%
~~~

[register_bound](../../../tools/perf/engineering/layout_lab.py)返回这些值，并显式标记尚未包含共享内存、warp/block限制和寄存器分配粒度。如果再假设共享内存64KiB、每block32KiB，最多驻留2block，线程上界降至25%。实际设备参数要查目标架构；不能把本例2048线程套到本机型号。

高occupancy可提供更多可切换工作，但寄存器复用、指令级并行和访存效率也影响结果。减少寄存器导致spill到local memory，可能比原来更慢；增加block size也可能降低总驻留量。评审要同时看register数、spill、shared、活跃warp、stall与实际时间。

## 指令、流水线和同步的边界

一个block内的共享tile至少经历“加载完成→共同读取→所有读者完成→复用缓冲”。越界线程可以加载0，但不能在其他线程需要它参加barrier时提前返回。warp内部数据交换与block barrier也不是同一个范围。

双缓冲把下一tile的加载与当前tile计算交叠，必须对每个buffer维护阶段：可写、生产中、可读、消费中、可复用。异步copy已发出不等于数据可读；消费结束也不等于全block已不再引用。错误的stage轮转可能只在多轮K、尾部或压力下出现。

cp.async、Tensor Core、TMA、WGMMA等指令有架构、dtype、布局和同步条件。它们是进一步优化的候选机制，不能给现有教学kernel加一个新指令名就宣称兼容。先确定目标compute capability、编译器和真实生成代码，再决定是否采用。

## 用三个相互独立的量解释性能

有效工作量来自数学问题；逻辑IO来自算法；真实硬件流量和时间来自测量。GEMM的2MNK、上述sector模型和Nsight的DRAM字节可以并列，但不能互相冒充。

例如，一个kernel用时减少却DRAM字节不变，可能改善了launch、指令或延迟隐藏；DRAM字节减少但时间不变，可能关键路径在计算/同步。需要提出能被推翻的解释，而不是仅用利用率截图命名瓶颈。

作业：把同一行主序矩阵的行读、列读、错位向量读列出地址；推导sector与bank集合；再说明你会用哪段timeline和哪个硬件证据验证。CPU实验只核对地址推导。

参考依据：[CUDA 13.0.1 Best Practices](https://docs.nvidia.com/cuda/archive/13.0.1/cuda-c-best-practices-guide/index.html)。本章的地址枚举、虚构SM与资源上界为本教材独立算例。
