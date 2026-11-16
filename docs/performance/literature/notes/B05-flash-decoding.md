# B05｜Flash-Decoding for long-context inference

作者：Tri Dao, Daniel Haziza, Francisco Massa, Grigory Sizov。初发：2023-10-13（日精度）；版本：article; benchmark lists FlashAttention2.0.9; implementation package availability separately stated。访问：2026-11-14 America/Tijuana（UTC见结构化索引）。

阅读深度：关键章节精读，范围为Multi-head attention for decoding；A faster attention for decoding；Benchmarks on CodeLlama34B；Component-level micro-benchmarks / Using。未宣称完整论文复现或本项目稳定收益。

## 为什么decode要沿KV维分工

原文面对query很短而KV较长的场景，把KV分块求局部输出/尺度，再归并。[原文机制与基准](https://pytorch.org/blog/flash-decoding/)有清楚的组件/模型范围。其A100组件表为FP16、Hq16/Hkv2/D128，B随L逐行变化；不能把那张表当固定B的长度曲线。

下列是我们自己的数学推导与已有代码接点。令不相交分段s上的分数已包含scale与mask，令：
~~~text
m_s = max_j z_j
l_s = sum_j exp(z_j - m_s)
u_s = sum_j exp(z_j - m_s) v_j

m = max_s m_s
l = sum_s exp(m_s-m) l_s
u = sum_s exp(m_s-m) u_s
o = u/l
~~~
只合并局部归一化输出而不带尺度会错。小例z=[0,ln2,ln6]，v=[[1,0],[0,1],[1,1]]，前两项一块、后一项一块，正确结果[7/9,8/9]；等权平均两块输出为[2/3,5/6]。沿现有FP64参考的单条手算误差为1.11e-16，见[math-check.json](../math-check.json)，不是GPU实验或论文复现。

若用LSE_s=m_s+ln(l_s)，同样可通过对LSE做logsumexp合并局部o_s。空段需要明确中性状态，所有mask为空时避免-inf减-inf；局部参考返回零不代表所有目标框架都有同一策略。浮点归并顺序改变可能有误差，数学结合律不是逐位一致承诺。

## split数不是只有一个含义

[S07](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/triton_backend.py#L965)生成实际split；[S08](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/triton_ops/decode_attention.py#L426)做stage1；[S09](https://github.com/sgl-project/sglang/blob/b0d25e72c401f37b55d689ddbf05b8c583afe854/python/sglang/srt/layers/attention/triton_ops/decode_attention.py#L585)归并。要分开最大cap、实际S_i、对齐chunk长度、非空段、发射grid和physical scratch stride。

现有[cap6资料](../../engineering/17-cap6-empty-cta.md)已经保留L512退化、L1024局部改善、L2048/ragged改变分段。即使S_i和chunk相同，cap变化仍可能改变scratch或stage2条件；不够资格叫“仅去掉空CTA”。

[E-LIT-02](../experiment-cards.md#e-lit-02)因此固定cap8的物理scratch/stage2，只对满足条件的cell改变stage1发射范围。当前旧harness含大长度且会重建metadata，不可原样用于这张卡；新范围还要满足ctx128、总KV512。无收益和不适用cell都保留。

自测：两个分段都算出正确局部softmax，为何直接平均仍错？它们的归一化分母通常不同。为什么删空CTA可能更慢？总成本还含发射/归并/布局/状态，不能只看有效元素数。
