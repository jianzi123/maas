# 沿固定 SGLang 源码追踪所有权与执行路径

源码阅读应留下能复查的调用链、状态与问题，不只列函数名。本章沿v0.5.6的固定提交7ae368efde14f0b2abe769a5fbb99b8154b2a9b7；它是源码样本，不作为当前部署推荐。八份原文的SHA256、字节数与AST定位已重新审计，未导入或启动SGLang。

## 调度主循环怎样持有前后两个batch

[Scheduler:967](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/managers/scheduler.py#L967)的normal路径接收请求、选batch、执行并处理结果。阅读时画出请求从队列移入执行集合、结果处理后完成/保留的所有权变化。

同文件992起的overlap路径使用结果队列，并有连续prefill及grammar相关的同步分支。它允许CPU处理与设备工作交叠，因此当前提交对象与待处理结果对象不应被混成同一生命周期。

阅读作业：分别沿“当前无batch但上一轮有结果”“连续prefill”“需要grammar同步”三条分支画时序。找出复制batch描述、结果出队和启动采样的位置，问哪些对象在下一次选批前仍被引用。源码存在overlap不等于目标负载一定受益。

## 选batch与实际forward之间还有边界

[Scheduler:1633](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/managers/scheduler.py#L1633)和1952起分别是选批与运行入口。[ScheduleBatch](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/managers/schedule_batch.py)包含请求、模式及执行metadata。

把“收到请求”“被选中”“提交前向”“结果处理”分成四个观测点，再核对queue时间定义。只在forward外打一个timer会把部分等待漏掉。每一处要记录批量、长度分布和实际模式，避免用平均batch描述完全不同的工作。

## Graph 选择与 fallback

[ModelRunner:2660](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/model_executor/model_runner.py#L2660)先判断模式和graph可运行条件，满足后replay；其他路径根据实际模式进入decode、split prefill、extend或idle等分支。

在此记录命中与fallback，再沿[forward_decode:2546](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/model_executor/model_runner.py#L2546)追backend准备。不要把全模型forward时间等同Attention，线性层、同步和logits也在链路中。

[CudaGraphRunner:808](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/model_executor/cuda_graph_runner.py#L808)包含输入准备、选图、重放与按真实数量裁剪输出。阅读时追捕获buffer的地址和每次更新范围，分析小batch padding及多stream图键对容量的影响。

## 缓存逐出怎样触达物理内存

[RadixCache:340](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/mem_cache/radix_cache.py#L340)是前缀匹配入口；544起的逐出路径从叶节点与策略优先级选择候选，释放对应KV并处理树结构和可继续逐出的父节点。

沿[MemoryPool](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/mem_cache/memory_pool.py)区分不同池与allocator。不能仅看到名为free的方法，就推断它包含全部请求引用、GPU事件和跨进程停止证明。问清上层已经保证了哪些前置条件。

第5章PagePool是独立教学模型，不能声称SGLang使用相同的generation API，也不能以模型不变量替代实际版本的异步生命周期验证。

## 到 Attention 和并行线性层结束一条链

[FlashInferBackend:698](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/layers/attention/flashinfer_backend.py#L698)与805起分别提供extend/decode入口。记录有效长度、布局、metadata准备和选择条件；CPU dense/online参考用来核对数学语义，不是其分页GPU路径的执行证据。

[Linear](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/layers/linear.py)要按类区分列/行并行、量化方法和通信。先画局部输出的消费者，再决定是否必须gather/reduce，避免按文件名推断性能。

## 一份源码阅读产物应包含什么

给每个候选交：固定SHA与原文hash、入口到出口调用链、关键shape/stride/dtype、对象所有者与寿命、分支/回退条件、拟加观测位置、至少一个反例，以及真实profile需要的环境。把“代码机制事实”“热点假设”“实测结论”分栏。

原始映射在[源码manifest](../../../tools/perf/runtime/sglang-source-map-v0.5.json)，审计工具是[source_audit.py](../../../tools/perf/runtime/source_audit.py)。它只验证原文字节和AST锚点，不导入代码、不检测运行兼容或性能。
