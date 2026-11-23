# B06｜Accelerating PyTorch with CUDA Graphs

作者：Vinh Nguyen, Michael Carilli, Sukru Burc Eryilmaz, Vartika Singh, Michelle Lin, Natalia Gimelshein, Alban Desmaison, Edward Yang。初发：2021-10-26（日精度）；版本：PyTorch1.10-era article; API checked against2.8 docs。访问：2026-11-14 America/Tijuana（UTC见结构化索引）。

阅读深度：关键章节精读，范围为CUDA Graphs；API overview / example；partial capture；NCCL boundary only。未宣称完整论文复现或本项目稳定收益。

## 捕获内容和Python对象不是一回事

文章解释捕获后沿固定地址重放，输入需更新到长生命周期buffer。[原文](https://pytorch.org/blog/accelerating-pytorch-with-cuda-graphs/)属Torch1.10时期；本次另读[2.8 CUDA Graphs约束/内存管理](https://docs.pytorch.org/docs/2.8/notes/cuda.html#cuda-graphs)，按当前版本核对。

捕获某函数一次以后，再把Python方法换成新实现，并不会自动改写旧图。我们已有late负控：eager走新store，旧图仍index双写，完整输出却仍相同。所以“库op计数有”和“结果一致”都不是图中已命中的充分证据。

## 源码与地址生命周期

S01 capture_one_batch_size在525行捕获真实model.forward；S02 replay_prepare在711行更新图输入/attention元数据，S03 replay在801行调用已捕获图。S04 backend init_cuda_graph_state在369行分配自己的图索引和scratch；完整hash和end_line见[source-map.json](../source-map.json)。

窗口B给第二变体独立backend、图输入和pool。若只切graph对象却让replay_prepare更新另一套metadata地址，旧图可能读陈旧buffer。输出也可能是图buffer别名：后一次重放前应在检查范围内clone，不把clone/毒化/CPU快照放入干净成本。

2.8文档还说明重放可能重排独立流上的操作，只需尊重依赖DAG。因此本地看到“双stream/单stream”是观测，不应把某个stream编号或数量当跨版本唯一正确性门禁。验证producer→write→read依赖、实际写槽和生命周期。

## pool复用不是免费交换条件

2.8文档给共享pool的保守安全条件是按捕获顺序重放且不并发。不能在改变变体次序后任意手工共享private pool。现有SGLang原生捕获策略与已验范围保持；新增对照采用独立pool，不由通用文档推断任意原生pool布局都错。

图主要减少提交开销，不保证每个GPU工作负载变快。[窗口B](../../engineering/20-window-b-cost-drift.md)的bare_graph只是绕过准备的诊断范围，真实动态请求仍需要replay_prepare。本文不提供当前Ada的稳定性能分母。

实验接点为[E-LIT-01](../experiment-cards.md#e-lit-01)和[E-LIT-03](../experiment-cards.md#e-lit-03)。捕获前安装或显式重捕获后，先看correlation连到的真实核，随后核动态输入/alias/slot，再讨论成本。

自测：两个Python对象不同能证明scratch不共享吗？不能，要检查实际地址与生命周期。输出逐位相同能证明新核已进入图吗？late负控已否定。
