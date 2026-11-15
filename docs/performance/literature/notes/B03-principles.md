# B03｜Making Deep Learning Go Brrrr From First Principles

作者：Horace He。初发：2022（年精度）；版本：author page snapshot; exact day unknown。访问：2026-11-14 America/Tijuana（UTC见结构化索引）。

阅读深度：关键章节精读，范围为Compute；Bandwidth / Reasoning about Memory-Bandwidth Costs；Overhead；footnote3 / BibTeX。未宣称完整论文复现或本项目稳定收益。

## 从文章到我们自己的归因问题

作者把计算、搬运、其他开销分开讨论，并用算术强度解释干预方向。这是分类工具，不是GPU利用率阈值分类器。[原文](https://horace.io/brrr_intro.html)与其脚注3都要求关注工作量变化；文章中的A100峰值不能替换本机Ada数据。

我们对当前工作负载使用下界推理：若一次实际工作包含F次目标精度运算、至少D字节目标层级搬运，理想设备时间不小于max(F/P,D/BW)。P必须按实际指令/精度选，D的逻辑下界不等于实测DRAM字节。缓存、占用、串行依赖、提交等待等可能让实测远离下界。不要把host与device的重叠阶段无条件相加。

同样是增大batch，线性层可能复用同一W而提高算术强度；没有共享前缀的独立attention请求则会增加各自KV读量。因而“batch翻倍而时长不翻倍”不能单独证明只受Python开销限制。这是结合文章脚注与我们GQA/ModelRunner工作负载的分析，不是新增实测。

## 对照已有证据

[窗口B](../../engineering/20-window-b-cost-drift.md)有240交错块、54独立控制块，裸图仍有长event/wait而host提交短，33/120对M更慢。这削弱了“十几毫秒全是Python准备”的简单解释，但不能区分设备执行、driver/WSL、其他活动。频率快照不能排除状态漂移。

读源码从[S03重放](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/model_executor/cuda_graph_runner.py#L801)到[S06 decode](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/triton_backend.py#L771)，确认当前不是线上Scheduler采样。当前没有测到可用于宣告带宽/算力瓶颈的硬件计数。

## 给高级工程师的检查顺序

先写明计时范围和分母，再找关键路径上的等待；用同一输入的最小干预去否定假设。对“加一个融合核”同时问：省了哪次真实读写、哪次API提交？引入多少寄存器、scratch或同步？不能从少30个kernel得出固定比例的收益。

下一步为[E-LIT-01](../experiment-cards.md#e-lit-01)：只改变查询/空闲策略，保持图与输入。若效应不随策略重复，保留未知并转向最小图/GEMM控制；不追着快样本改参数。

自测：低GPU-Util能证明带宽不足吗？不能，它没有提供忙时DRAM吞吐。batch扩张为何可能改变模型层与attention层不同的瓶颈？权重与每请求KV的复用方式不同。
