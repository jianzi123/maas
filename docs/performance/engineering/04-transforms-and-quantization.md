# RoPE 归一化 融合与权重量化

这类算子常较小，容易被“少一个launch”吸引。设计应先固定坐标、数值和全部输出，再计算省了哪些传输。可运行实现见[transforms_lab](../../../tools/perf/engineering/transforms_lab.py)。

## RoPE 的旋转与缓存位置

对相邻坐标(x2i,x2i+1)，角度θ=position×base^(−2i/D)：

~~~text
y2i   = x2i*cosθ − x2i+1*sinθ
y2i+1 = x2i*sinθ + x2i+1*cosθ
~~~

旋转矩阵的逆是角度取负，因此R(−p)R(p)x=x；同一位置的q/k旋转保持内积。测试使用非零位置13起，并核验逆变换和内积。若只测试position=0，sin为0，会漏掉符号、配对与位置偏移错误。

实验采用interleaved成对坐标。其他模型可能将前后半维配对、仅旋转部分维度，或采用不同频率缩放。不能把两种布局直接套用。KV里存的是旋转前还是旋转后K也必须明确，避免在decode重放时旋转两遍。

prefix cache的复用键要涵盖位置策略、base/scaling、权重、tokenizer/template及安全域。相同token但不同位置/旋转配置，缓存值可能不同。机制参考[RoFormer](https://arxiv.org/abs/2104.09864v5)，本实验未实现特定模型的长上下文扩展。

## RMSNorm 与残差的两个输出

令r=x+residual，y=r/√(mean(r²)+epsilon)×weight。取x=[2,3]、residual=[1,1]，则r=[3,4]，均方12.5，y约[0.848528,1.131371]。

[rms_residual](../../../tools/perf/engineering/transforms_lab.py)返回r与y。融合后若下游还需要r，就必须保留它；省掉一个必要输出不是等价融合。epsilon要求正且finite，输入/输出都经过finite检查。

若未融合路径先写r到HBM再读取，融合可能减少中间读写；但若r仍要输出，就仍有相应store。量化融合还会产生scale等输出。逻辑IO必须按实际接口计算，不能只数launch。累加dtype、epsilon位置、广播和尾部归约也在正确性范围内。

## 对称分组 W8 的格式必须写全

本实验对W[K,N]沿K按group_size分组，每组每列一个float32 scale：

~~~text
amax[g,n] = max(abs(W[g*G:(g+1)*G,n]))
scale = amax/127；全0组约定scale=1
q = clip(round_to_nearest_even(W/scale), -127,127)
W_hat[k,n] = q[k,n] * scale[k//G,n]
~~~

量化值用int8，但保留范围−127到127，−128视为非法格式。最后不足G的组只处理有效元素。scale落不到可用float32范围时拒绝，避免下溢成0或溢出成Inf。

[quantize_w8/dequantize_w8](../../../tools/perf/engineering/transforms_lab.py)是真实CPU量化与反量化；GEMM仍由反量化后的浮点权重计算，不是GPU INT8 GEMM。它不是GPTQ/AWQ，也没有做校准集优化或模型质量验收。

## 小组不一定省内存

格式字节数=K*N + 4*ceil(K/G)*N。K=8、N=5、G=3时，q占40字节，scale占60，总100；原FP16权重仅80字节。小例反而更大，报告明确保留这一结果。

大K忽略尾部时，相对FP16比例约为1/2+2/G；G=128约0.515625。但这未包含packing、zero point、额外元数据、workspace和运行副本。CPU反量化成float64还会额外分配内存，不能用存储格式节省推断GPU峰值下降。

## 将权重误差传到线性层

令E=W_hat−W，输出误差为XE。对每行i、列j：

~~~text
abs((XE)[i,j]) <= sum_k abs(X[i,k])*abs(E[k,j])
              <= ||X[i,:]||1 * max_k abs(E[k,j])
~~~

实验以实际反量化误差计算上界，包含scale存储舍入，验证候选输出满足三角不等式。这个上界可能很松；多层网络、激活和采样会传播误差，不能替代模型级质量。

高级作业：给定真实shape与接口，分别列未融合、残差融合、反量化融合的输入/输出/临时张量；说明误差预算和成熟baseline。冻结组方向、group size、scale dtype、舍入、饱和及坐标布局后，再提出GPU实现与模型验证计划。
