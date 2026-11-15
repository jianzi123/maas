# P02｜FlashInfer: Efficient and Customizable Attention Engine for LLM Inference Serving

作者：Zihao Ye, Lequn Chen, Ruihang Lai, Wuwei Lin, Yineng Zhang, Stephanie Wang, Tianqi Chen, Baris Kasikci, Vinod Grover, Arvind Krishnamurthy, Luis Ceze。初发：2025-01-02（日精度）；版本：arXiv2501.01005v2 / 2025-04-21; paper runtime FlashInferv0.2。访问：2026-11-14 America/Tijuana（UTC见结构化索引）。

阅读深度：关键章节精读，范围为§2.2 attention composition；§3.1 KV formats；§3.2 tile/JIT；§3.3 scheduling / Algorithm1；§3.4 plan/run；§4.1–4.2 setup；Appendix D.1–D.3。未宣称完整论文复现或本项目稳定收益。

## 本次读到哪，哪些版本没有混用

精读范围为[arXiv v2](https://arxiv.org/html/2501.01005v2)的§2.2、§3.1–3.4、§4.1–4.2实验设置和D.1–D.3，不标全文/复现。初发2025-01-02、v2为2025-04-21。论文评估FlashInferv0.2、SGLang0.3.4、CUDA12.4/PyTorch2.4/FP16，A10040GB SXM与H10080GB SXM；我们固定SGLang0.5.2/Triton3.4/Ada8.9，不是同一基线。

论文将KV组织、可定制算子和动态计划分层。plan把长度映射成任务/归并索引，run消费计划；图兼容workspace要求地址和各段偏移稳定。这个设计不能简化成“动态长度要求每步重新捕获图”。

## 如何和真实代码对照

本机[S13 init_cuda_graph_state](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/flashinfer_backend.py#L278)、[S14 replay metadata](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/flashinfer_backend.py#L417)存在，但本轮只读源码，没有执行FlashInfer。也未发现flashinfer-python/flashinfer分发元数据；这不是用库文件名证明backend已运行。

实际路径是S04/S05/S06的Triton backend。文献机制只用于提出对照问题，不冒称论文scheduler已经在这条路径中。论文硬件/shape/软件表与本地矩阵分别保存。

## workspace上界怎样读成工程约束

论文D.3给局部输出元素上界2·N_CTA·Tq·Hqo·(D+1)。这是partial-output部分，不是全部workspace。我们取一个纯手算例：N_CTA=36、Tq=1、Hqo=9、D=64、FP32，得到42120个元素/168480字节。这里36 CTA是示例，未证明本机最佳occupancy；还没算scheduler arrays、对齐及其他临时内存。

当前Triton ModelRunner例的scratch公式则为B·Hq·cap·(D+1)·4。B8/Hq9/cap8/D64得到149760字节。它和论文的分配算法不同，不能将两数相减宣告内存优化，也不能把论文上界直接当当前后端分配尺寸。

保持固定buffer后，可更新其内容表达动态长度；必须证明元数据容量、任务覆盖、真实/空段以及归并目标都合法。GQA的head比9/3=3能改变复用，但不共享KV的请求batch不自动提高同一attention tile的算术强度。

## 什么尚不能从论文推出

§4.1按P99TTFT约束调请求率，组件§4.2另用B16的constant/uniform/Zipf长度；不能和我们的静态ForwardBatch事件时间合表算收益。v2该段有遗留指代句，与v1的TRTLLM段落不一致；本卡只采用明确列出的Triton/FlashInfer设置，不复述不清楚的闭源表述。

论文的query/key变换融合不等于本机sgl-kernel的RoPE+cache写API，更不等于Llama caller命中。后者已在[第20章](../../engineering/20-window-b-cost-drift.md)完成库级语义，caller路径仍需[E-LIT-03](../experiment-cards.md#e-lit-03)。论文/博客收益不是本项目收益。

自测：固定workspace能否允许数据依赖计划？可以更新合法范围内的数据，但图指针/布局须稳定。计算局部输出上界后能否忽略metadata？不能，计划本身也占容量，越界应失败关闭。
