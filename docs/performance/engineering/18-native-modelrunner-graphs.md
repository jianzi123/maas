# 18｜人工权重下的原生ModelRunner与图重放

本批固定SGLang0.5.2/b0d25e7、torch2.8+cu128，使用已有SmolLM配置/tokenizer和原生DummyModelLoader初始化人工随机权重，实际构造134515008参数的LlamaForCausalLM与ModelRunner。原生CudaGraphRunner完成1/2/4/8捕获，随后走原生Req、ScheduleBatch、ForwardBatch、prefill和decode。

**证据层级已到实际ModelRunner/原生图的结构执行。** 没有构造Engine facade、运行在线scheduler/serving或加载预训练权重；没有模型语义质量、预训练模型性能或加速结论。额外eager参考、毒化、同步和hook使本批所有时间都不适合作性能基线。

[原始报告](../../../tools/perf/operators/local_gpu/evidence/framework-v0.18/native-framework.json)与[摘要](../../../tools/perf/operators/local_gpu/evidence/framework-v0.18/summary.json)逐项区分实际执行、人工探针和未执行层级。上一批cap6已由QA553980d在受控后端张量范围独立通过，本批不重复它的计时矩阵，默认cap8保持。

## 1. 入口真正执行了什么

[run_framework_dummy.py](../../../tools/perf/operators/local_gpu/run_framework_dummy.py)调用原生sglang.bench_one_batch.load_model，而非__new__构造metadata。固定版DummyModelLoader.download_model为no-op，load_model实际创建模型、初始化随机权重并eval；它不需要模型文件。

~~~mermaid
flowchart LR
  A[本地config/tokenizer] --> B[原生DummyModelLoader]
  B --> C[真实ModelRunner / LlamaForCausalLM]
  C --> D[原生CudaGraphRunner捕获1/2/4/8]
  E[原生Req / ScheduleBatch] --> F[原生ForwardBatch]
  F --> G[ModelRunner.forward]
  G --> H[原生graph_runner.replay]
  G --> I[原生eager参考]
  H --> J[logits切片/别名/有限值检查]
  I --> J
~~~

9份相关安装源码与官方固定commit逐字节一致，见[framework-source-lock](../../../tools/perf/operators/local_gpu/evidence/framework-v0.18/framework-source-lock.json)：原生bench、dummy loader、weight utils、ModelRunner、CudaGraphRunner、ForwardBatch、ScheduleBatch、Llama与RoPE。upstream磁盘文件没有修改。

为观察路径，只在捕获完成后给runner.forward、实际KV写方法与RoPE模块添加观察/参考hook；观测器调用原方法并保留结果。graph捕获仍来自原模型。Python hook仅观察eager caller，不能将它的计数当作重放时又执行了Python。

## 2. 资源上限实际满足

| 项 | 实际 |
|---|---|
| GPU | RTX4070 Laptop / 单GPU0 |
| allocator fraction | 0.20 |
| SGLang静态内存规划fraction | 0.20 |
| max_running_requests | 8 |
| context_length / max_total_tokens | 128 / 512 |
| 捕获尺寸 | 1、2、4、8 |
| Torch allocator峰值 | 323878912 bytes，308.875MiB |

fraction不是整卡/context强隔离。本批开始至少1GiB空闲、同research锁、每进程外层600s；未提高原资源上限、修改驱动或终止其他GPU进程。原生进程组在finally销毁，自有进程退出。

人工权重的整个模型架构被执行，但不能称为“SmolLM预训练性能”。token步使用固定合成输入与强制变化的token，用于检查结构；无语义输出评测。

## 3. 动态batch、padding与真实图输出

12次decode检查覆盖独立B1/B3/B2/B5/B8各两步，以及原生filter_batch的8→3→1缩减。B2场景在非默认stream运行。

| 实际batch | 捕获batch | padding |
|---|---|---|
| 1 | 1 | 0 |
| 2 | 2 | 0 |
| 3 | 4 | 1 |
| 5 | 8 | 3 |
| 8 | 8 | 0 |

每次原生ModelRunner.forward确实返回used_graph=True，随后用相同ForwardBatch临时禁用graph_runner，再调用原生eager路径作为参考。先克隆graph logits，防止后续调用复用缓冲使比较失去意义。12次实际最大绝对差均0；本例logits量级约1e-6，预设rtol0.02/atol5e-7只是人工权重的局部数值门禁，不是模型质量政策。

捕获输出和固定attention scratch在重放前毒化为NaN，真实结果须重新写成有限值；变化token产生不同logits hash。padding位置seq_lens=1、cache location=0，返回logits只含真实batch行。graph输入buffer指针在batch变化中稳定，返回logits实际别名于原图输出buffer；要长期保存必须clone。

池回收使用原ReqToTokenPool/token allocator接口，以实际请求映射/seq_lens释放；释放集合必须唯一且不含dummy slot0。五个场景结束均回到req_free8、kv_free512。8→3→1还调用原生ScheduleBatch.filter_batch，未用手工metadata代替。这里是同步受控生命周期，不证明生产取消/ACK未知的资源安全。

## 4. 图重放的metadata不是你眼前那个对象

首轮观测器错误读取forward_metadata.num_kv_splits，得到None并退出。原因是：

1. prefill/eager会替换forward_metadata对象；
2. 原生图捕获已经持有固定cuda_graph_* buffer参数；
3. replay_prepare更新固定buffer，重放不会重新运行Python forward_metadata引用逻辑。

正确记录来自cuda_graph_num_kv_splits及graph_runner的真实bs/raw_bs。只查看forward_metadata可能把prefill对象误认成图当前输入。

实际B3、序列13时，图padding到4，split向量为[7,7,7,1]；eager真实B3为[4,4,4]。两边输出仍一致，因为短KV的32对齐使有效工作分片相同。B5→8也出现图[7,7,7,7,7,1,1,1]与eager[3,3,3,3,3]差异。

这说明上一批B8/L1024的cap6切片条件不是在线batch保证。padding改变参与全批min/max的序列分布；必须在真实捕获与动态batch下评估，不从手工metadata实验直接改默认值。

## 5. 成熟RoPE/KV：caller存在、实际命中、人工探针要分清

### 默认实际模型路径

选定B3场景的独立trace包含prefill及两个graph/eager参考对：

- CPU op统计观察到sgl_kernel::apply_rope_pos_ids_cos_sin_cache 90次、fused_add_rmsnorm180次、rmsnorm3次、silu_and_mul90次；这些是profile中eager/prefill的实际dispatcher调用，graph重放由GPU kernel交叉核对。
- 默认模型路径没有sgl_kernel::store_kv_cache调用。实际原生KV池仍分别写K和V。
- RoPE实际Q为[12,576]、K为[12,192]，stride均[960,1]，输出与输入别名；KV写入K为[12,3,64]、stride[960,64,1]，是QKV拆分产生的非连续视图。

不能把之前连续张量微基准的契约不经核对搬到真实caller。

### 原生图的多stream语义

本次两个同步graph区域各378个kernel，eager参考各399个；这些是结构计数，不是速度收益。raw CUPTI中graph有两个stream：主stream348核，其中30个KV索引写；另一stream30核，均为KV索引写。eager参考单stream、60个KV索引写。

这与原始model_capture_mode下KV池对K/V复制的跨stream安排对应。stream ID是单次运行标识，复验不应强求本次7/144。只替换一段双写为单核，会改变真实图的DAG/同步语义，需要原生框架验证。

### 在真实视图上的成熟直接op探针

额外人工探针只在B1 prefill层0执行：用独立目标cache，直接将实际K/V非连续视图传给store_kv_cache，不改变默认模型写入。结果逐位一致、无fallback，专门trace只有store_kv_cache_128x2一个核，没有隐式连续化拷贝；CPU侧只观察到view元数据操作。

它说明当前实际视图兼容已安装成熟op，不说明默认模型已经命中或替换后一定更快。人工探针在默认路径profile之外单独记录，绝不把这一调用混为默认命中。

下一批可优先在原生框架中验证成熟KV接线或既有RoPE+KV融合，保留动态locations/stream/输出别名约束；无需用教学内核替代成熟实现。

## 6. 失败记录与复现

第一探针在原生捕获完成后，将属性误写为cuda_graph_runner；固定版是graph_runner。下一观测器又误读prefill metadata。两次都保留failed报告和当时源码；没有当作图/框架成功报告。修正的是研究观测代码，没有修改SGLang实现。

同持久WSL环境、现有本地config/tokenizer、离线标志HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE/HF_DATASETS_OFFLINE开启，trust_remote_code=False。只用原生dummy loader，不下载权重；旧run_sglang.py的真实权重门禁未放开。

~~~bash
GPU_PY=/var/tmp/maas-10-gpu-01a1a5ba/bin/python
timeout --kill-after=10s 600s "$GPU_PY" tools/perf/operators/local_gpu/run_framework_dummy.py \
  --source-lock tools/perf/operators/local_gpu/evidence/framework-v0.18/framework-source-lock.json \
  --output tools/perf/reports/native-dummy-structure --profile
~~~

输出目录必须全新。framework.json包含真实类/参数、12步数值、padding/split、buffer别名、pool对账、实际成熟caller与人工探针；timeline.json是B3结构profile，manual-mature-view.json单独记录人工API探针。源码/数值/回收失败保留failed状态，不发布passed结论。

## 7. 本批后的验证顺序

1. 在这套原生ModelRunner和实际非连续视图上，验证成熟KV或RoPE+KV接线、原生graph与多stream等价性；先正确性，再决定是否值得测成本。
2. 研究动态batch/padding下的条件化cap，保留cap8默认与上一批L512退化，不在热路径添主机同步。
3. 完整获准预训练权重/依赖到位后，分别建立真实ModelRunner、Engine、serving与质量基线。dummy结构结果不代替它们；nvcc/Sanitizer缺口仍保留。

自测：为什么forward_metadata可能None？它可能仍是prefill对象，图参数在固定buffer；为什么先clone输出？返回值实际复用图buffer；为什么native graph有两条stream？实际KV复制被捕获成跨stream依赖；人工store探针为何不叫默认命中？默认caller未替换，trace单独标注；为什么没宣称模型加速？本批人工权重且加入额外参考/同步，既非语义质量也非干净性能基线。
