# 21｜把原文读成源码问题与可否证实验

本章接续[第20章窗口B](20-window-b-cost-drift.md)。窗口B已在7315b32/bf319d6交付294个干净成本块，漂移unknown、稳定收益未成立；本轮不再跑GPU成本实验。这里新增的是原文索引、四张关键章节笔记、实际代码导航及三张设计卡，服务后续推理框架与部署框架建设。

[总入口](../literature/README.md)保留Mika的B01–B08/P01–P08编号，共16项原始来源，另有Torch2.8官方语义辅助源。筛选看可追溯贡献/方法/代码，不做“谁排名第一”的编造。四项为关键章节精读，其余只是摘要/引言/元数据，没有完整论文复现。

## 1. 一次阅读如何变成可审结论

~~~mermaid
flowchart LR
  A[原文中的条件与机制] --> B[固定版本实际源码]
  B --> C[已有raw证据/反例]
  C --> D[单因素假设]
  D --> E[数值/身份/容量门禁]
  E --> F[受控实验及否定条件]
  F --> G[适用/不适用/未知]
~~~

每张资料卡都登记作者、日期精度、访问时间、阅读范围、版本/硬件/shape、基线分母、数值约束及局限。原文告诉我们某种方法可能为什么有效；实际源码告诉我们当前路径是否相同；原始证据决定本项目能下什么结论。这三层不应互相替代。

本轮访问manifest有17个独立HTTP200/hash，7份固定SGLang源码与官方b0d25e7逐字节核对。完整第三方文章只作私有阅读快照，不随成果整篇分发。Horace作者BibTeX确认年份2022，月日仍未知；Colfax补核页尾日期2024-06-24，但不把评论中的名字冒充个人署名。

## 2. 四项优先阅读的实际问题

| 笔记 | 读后的工程产物 | 不能推出的结论 |
|---|---|---|
| [B03 第一性原理](../literature/notes/B03-principles.md) | 分开计算/搬运/提交；为窗口B写反证 | 看到低利用率或小batch就确认某种瓶颈 |
| [B06 CUDA Graphs](../literature/notes/B06-cuda-graphs.md) | 固定地址、图buffer/alias/pool与DAG生命周期 | 换Python方法自动更新旧图，或图一定消除全部等待 |
| [B05 Flash-Decoding](../literature/notes/B05-flash-decoding.md) | 推导局部状态归并，区分cap/S/chunk/grid | 更多split必然更快；局部输出可以等权平均 |
| [P02 FlashInfer](../literature/notes/P02-flashinfer.md) | 对照plan/run、workspace上界及当前backend | 库文件存在就说明实际命中；论文系统倍率适用于本机 |

软max归并手算使用现有FP64参考：分数[0,ln2,ln6]、向量[[1,0],[0,1],[1,1]]，正确[7/9,8/9]，两块输出等权平均却是[2/3,5/6]。本轮只核这条公式，误差1.11e-16；不是新的CPU性能实验，也不是复现作者GPU。空段/全mask语义须按目标路径明确处理，不能靠-inf相减得到碰巧可用的NaN。

高级工程师还应核单位：FlashInfer局部输出上界按“元素数”给出，转bytes要按状态dtype；metadata、对齐与其他临时内存另算。Triton的B×H×cap布局与论文动态workspace不同，不能把两个上界相减当实际节省。

## 3. 固定SGLang0.5.2的代码地图

下表的S01–S14均为b0d25e72c401f37b55d689ddbf05b8c583afe854的实际安装源码，AST位置与7份官方原文hash一致。S15为另一个分发包sgl-kernel0.3.9.post2，不能自动归到同一SGLang commit。

| ID | 实际符号 | 原始源码 |
|---|---|---|
| S01 | CudaGraphRunner.capture_one_batch_size | [srt/model_executor/cuda_graph_runner.py:525](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/model_executor/cuda_graph_runner.py#L525) |
| S02 | CudaGraphRunner.replay_prepare | [srt/model_executor/cuda_graph_runner.py:711](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/model_executor/cuda_graph_runner.py#L711) |
| S03 | CudaGraphRunner.replay | [srt/model_executor/cuda_graph_runner.py:801](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/model_executor/cuda_graph_runner.py#L801) |
| S04 | TritonAttnBackend.init_cuda_graph_state | [srt/layers/attention/triton_backend.py:369](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/triton_backend.py#L369) |
| S05 | TritonAttnBackend.init_forward_metadata_replay_cuda_graph | [srt/layers/attention/triton_backend.py:583](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/triton_backend.py#L583) |
| S06 | TritonAttnBackend.forward_decode | [srt/layers/attention/triton_backend.py:771](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/triton_backend.py#L771) |
| S07 | get_num_kv_splits_triton | [srt/layers/attention/triton_backend.py:965](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/triton_backend.py#L965) |
| S08 | _decode_grouped_att_m_fwd | [srt/layers/attention/triton_ops/decode_attention.py:426](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/triton_ops/decode_attention.py#L426) |
| S09 | _decode_softmax_reducev_fwd | [srt/layers/attention/triton_ops/decode_attention.py:585](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/triton_ops/decode_attention.py#L585) |
| S10 | MHATokenToKVPool.set_kv_buffer | [srt/mem_cache/memory_pool.py:594](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/mem_cache/memory_pool.py#L594) |
| S11 | RotaryEmbedding.forward_cuda | [srt/layers/rotary_embedding.py:219](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/rotary_embedding.py#L219) |
| S12 | LlamaAttention.forward | [srt/models/llama.py:188](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/models/llama.py#L188) |
| S13 | FlashInferAttnBackend.init_cuda_graph_state | [srt/layers/attention/flashinfer_backend.py:278](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/flashinfer_backend.py#L278) |
| S14 | FlashInferAttnBackend.init_forward_metadata_replay_cuda_graph | [srt/layers/attention/flashinfer_backend.py:417](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/flashinfer_backend.py#L417) |
| S15 | apply_rope_with_cos_sin_cache_inplace | sgl_kernel/elementwise.py:266（轮子源码hash单列） |

代码存在和执行命中分开：本机窗口B指定Triton；未发现flashinfer-python/flashinfer分发元数据，本轮没有导入运行其backend。S13/S14用于源码对照，不列为已执行功能。实际精度/图捕获范围沿旧QA与GPU产物，不因新增映射扩大。

## 4. 版本和硬件分栏

| 材料 | 原条件 | 本地迁移判断 |
|---|---|---|
| 本机已交实验 | RTX4070 Laptop / CC8.9 / 36SM；Torch2.8+cu128、Triton3.4、SGLang0.5.2、sgl-kernel0.3.9.post2 | 人工权重ModelRunner/库级；没有预训练质量或Engine/serving验收 |
| [PyTorch博客](https://pytorch.org/blog/accelerating-pytorch-with-cuda-graphs/) | 2021、Torch1.10时期，训练/NCCL实例 | API约束另对[Torch2.8](https://docs.pytorch.org/docs/2.8/notes/cuda.html#cuda-graphs)；不复制训练指标 |
| [Flash-Decoding](https://pytorch.org/blog/flash-decoding/) | A100、FP16、Hq16/Hkv2/D128；表格改变B和L | 先转成当前shape与split假设；不照搬组件/模型倍率 |
| [FlashInfer v2论文](https://arxiv.org/html/2501.01005v2) | FlashInferv0.2、SGLang0.3.4、Torch2.4、CUDA12.4、A100/H100 | 目前只是阅读对照；不是当前Triton实际路径 |
| [Colfax TMA](https://research.colfax-intl.com/tutorial-hopper-tma/) / [FA3](https://arxiv.org/abs/2407.08608v2) | Hopper/SM90、异步TMA/warp specialization | Ada8.9不具同一SM90路径；需要目标硬件才能验证该实现 |
| [FA4](https://arxiv.org/abs/2603.05451v1) | Blackwell/B200、BF16与新流水 | 本轮只核摘要；不在Ada上声称复现或因此升级环境 |
| [Mini-SGLang](https://www.lmsys.org/blog/2025-12-17-minisgl/) | 独立教学框架；Hopper核、H200样本 | 可学习结构，但不是当前0.5.2配置/参数文档 |

多卡TP/EP/PD/MoE与部署框架的资源/拓扑/故障语义另列后续阅读，不以单卡算子结果外推。Go/MySQL唯一准入结算及平台链路的已有边界保持；本批不改变共享契约。

## 5. 三张可否证卡，执行前缺什么

[完整卡与JSON](../literature/experiment-cards.md)均为design_only、execution_enabled=false。本地GPU授权继续有效；此字段仅说明本轮文献交付尚未实现/执行这些新干预，不是重新等待原GPU许可。

- E-LIT-01先对查询/空闲节奏做预置轮转：块前查询、cluster前查询、按预先记录查询时长匹配空闲。先证明状态能否随干预重复，不给某个驱动机理盖章。现脚本没有cadence开关，future_GPU_invocation=null。
- E-LIT-02固定物理cap8 scratch、stride、实际S/chunk和stage2，只对满足条件的cell缩stage1 grid。旧run_split_cap6含L512–2049并重建metadata，不能直接拿来用。新矩阵最长128、总KV不超过512，S>6的cell明确不适用。
- E-LIT-03将成熟RoPE+cache写在真实caller捕获前接入，证明写到同一层/槽后才save=False。六格库级通过不覆盖caller、动态padding dummy0或图中命中；真实非目标槽哨兵、V视图、alias及写前拒绝都需独立门禁。

候选发生数值/身份/映射错误即否决，不进入性能成功结论；超资源/锁忙/600s即停止。所有失败、未恢复与不适用cell保留。若DAG、分段或工作量改变，就不能继续叫同一单因素对照。

## 6. 阅读后的工程作业与检查点

入门作业：复述“一个正确输出为何不能证明图已融合”，并用已有late负控说明。进阶作业：写出state merge包含尺度的原因、空段中性状态与浮点限制，再指出当前backend的两个阶段和scratch来源。

高级作业：审查新caller的所有写缓存路径。prefill/eager/decode何时save？绑定前后何时capture？B5→pad8的dummy slot0是否被误当真实非目标槽？loc数据值校验会不会偷偷引入热路径.item同步？缺乏可信元数据证明时应故障关闭，而不是在计时中加同步掩盖问题。

验收以可解释的来源/代码/门禁/负结果为准，不以链接数量或复制宣传倍数为准。四笔记有明确关键章节范围；没有写“全文已读”“论文已复现”或新的模型瓶颈/收益。后续一轮实质证据到来再更新阅读深度，不开无限抓取或礼貌互唤醒。
