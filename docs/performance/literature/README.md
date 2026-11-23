# 原文、论文与可否证实验

这里沿用Mika首批B01–B08/P01–P08编号，保留16项原始来源，另列[Torch2.8官方约束](https://docs.pytorch.org/docs/2.8/notes/cuda.html#cuda-graphs)作为辅助核查。筛选依据是可追溯原始贡献、方法/代码与本任务关联，不制造专家排名或资历。本文献线服务既有GPU研究，不替换运行环境。

本批四项达到“关键章节精读”，其余仅摘要/引言/元数据；没有一项标完整全文或实际复现。网页整页下载只用于私有访问快照，不代表整页已读。Horace的作者BibTeX只能确认2022年，具体月日未知；Colfax页尾补核2024-06-24，个人署名仍未确认，不以评论者代替作者。

## 路线：每一步要留下什么

1. 先读B03和B06，写清计时范围、哪些等待尚未解释；拿[窗口B](../engineering/20-window-b-cost-drift.md)的负结果反驳过强的归因。
2. 读B05/P02相关节，手算状态归并、空段和workspace；对应[source-map.json](source-map.json)实际函数，而不是凭同名术语推定实现一致。
3. 执行前先把假设落成[三张实验卡](experiment-cards.md)。本轮设计状态execution_enabled=false，明确需要实现的开关/caller，未伪造新GPU命令。
4. 后续再按需精读P01/P03/P04的系统取舍，B01/B02补CUDA工程，B04/P07/P08走目标硬件进阶线。源码与原始数据比宣传倍数优先。

## 首批原文索引

| ID / 优先级 | 原文 | 作者/初发 | 本轮深度 | 入口 |
|---|---|---|---|---|
| B01 / P1 | [How to Optimize a CUDA Matmul Kernel for cuBLAS-like Performance: a Worklog](https://siboehm.com/articles/22/CUDA-MMM) | Simon Boehm；2022-12 | 摘要/引言与元数据 | 待精读 |
| B02 / P1 | [CUDA Matrix Multiplication Optimization](https://leimao.github.io/article/CUDA-Matrix-Multiplication-Optimization/) | Lei Mao；2024-01-20 | 摘要/引言与元数据 | 待精读 |
| B03 / P0 | [Making Deep Learning Go Brrrr From First Principles](https://horace.io/brrr_intro.html) | Horace He；2022 | 关键章节 | [笔记](notes/B03-principles.md) |
| B04 / P2 | [CUTLASS Tutorial: Mastering the NVIDIA Tensor Memory Accelerator (TMA)](https://research.colfax-intl.com/tutorial-hopper-tma/) | Colfax Research；2024-06-24 | 摘要/引言与元数据 | 待精读 |
| B05 / P0 | [Flash-Decoding for long-context inference](https://pytorch.org/blog/flash-decoding/) | Tri Dao等；2023-10-13 | 关键章节 | [笔记](notes/B05-flash-decoding.md) |
| B06 / P0 | [Accelerating PyTorch with CUDA Graphs](https://pytorch.org/blog/accelerating-pytorch-with-cuda-graphs/) | Vinh Nguyen等；2021-10-26 | 关键章节 | [笔记](notes/B06-cuda-graphs.md) |
| B07 / P1 | [SGLang v0.4: Zero-Overhead Batch Scheduler, Cache-Aware Load Balancer, Faster...](https://www.lmsys.org/blog/2024-12-04-sglang-v0-4/) | The SGLang Team；2024-12-04 | 摘要/引言与元数据 | 待精读 |
| B08 / P1 | [Mini-SGLang: Efficient Inference Engine in a Nutshell](https://www.lmsys.org/blog/2025-12-17-minisgl/) | Ziyi Xu；2025-12-17 | 摘要/引言与元数据 | 待精读 |
| P01 / P1 | [SGLang: Efficient Execution of Structured Language Model Programs](https://arxiv.org/abs/2312.07104v2) | Lianmin Zheng等；2023-12-12 | 摘要/引言与元数据 | 待精读 |
| P02 / P0 | [FlashInfer: Efficient and Customizable Attention Engine for LLM Inference Ser...](https://arxiv.org/html/2501.01005v2) | Zihao Ye等；2025-01-02 | 关键章节 | [笔记](notes/P02-flashinfer.md) |
| P03 / P1 | [Efficient Memory Management for Large Language Model Serving with PagedAttent...](https://arxiv.org/abs/2309.06180v1) | Woosuk Kwon等；2023-09-12 | 摘要/引言与元数据 | 待精读 |
| P04 / P1 | [Taming Throughput-Latency Tradeoff in LLM Inference with Sarathi-Serve](https://arxiv.org/abs/2403.02310v3) | Amey Agrawal等；2024-03-04 | 摘要/引言与元数据 | 待精读 |
| P05 / P1 | [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135v2) | Tri Dao等；2022-05-27 | 摘要/引言与元数据 | 待精读 |
| P06 / P1 | [FlashAttention-2: Faster Attention with Better Parallelism and Work Partition...](https://arxiv.org/abs/2307.08691v1) | Tri Dao；2023-07-17 | 摘要/引言与元数据 | 待精读 |
| P07 / P2 | [FlashAttention-3: Fast and Accurate Attention with Asynchrony and Low-precision](https://arxiv.org/abs/2407.08608v2) | Jay Shah等；2024-07-11 | 摘要/引言与元数据 | 待精读 |
| P08 / P2 | [FlashAttention-4: Algorithm and Kernel Pipelining Co-Design for Asymmetric Ha...](https://arxiv.org/abs/2603.05451v1) | Ted Zadouri等；2026-03-05 | 摘要/引言与元数据 | 待精读 |

完整作者、修订日期、硬件/shape/dtype、对照分母、数值约束与局限在[sources.json](sources.json)。[访问manifest](source-access.json)记录17个页面的独立HTTP200/hash；不分发整篇第三方文章。[源码地图](source-map.json)有15处实际符号，14处SGLang符号涉及7文件与官方b0d25e7逐字节一致，另1处sgl-kernel轮子源独立计版本。

## 阅读状态不是性能状态

“摘要/元数据”不能写成已理解全部消融；“关键章节”不能写成复现论文；“已有本地机制证据”不能写成同条件复现作者系统。当前本机有真实GPU、SGLang原生ModelRunner和库级语义证据，但没有预训练模型质量或Engine/serving收益。本轮不新增GPU运行、不下载权重、不改MAAS-15。

## 评审人可直接核对

- [四篇笔记](notes/B03-principles.md)分别记录机制和我们自己的源码/证据推理；从具体链接继续读B06/B05/P02。
- [三张实验卡JSON](experiment-cards.json)的假设、单因素、固定项、矩阵、门禁、否定/停止条件和实现缺口是可检查的；没有尚不存在的CLI flags。
- [手算记录](math-check.json)复用已有FP64数学参考，只核一条归并示例，不是新的性能实验。
- 既有原始成本、旧cap6负结果和QA关闭范围保持原SHA。下一优先级是查询/空闲节奏的可重复干预，随后才是候选caller的语义/图命中与成本。
