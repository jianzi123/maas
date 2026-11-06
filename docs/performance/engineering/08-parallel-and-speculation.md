# TP MoE PD 与投机解码的等价性

分布式优化应先写出每个rank持有什么、消息传什么、结果如何合并。可运行的[distributed_lab](../../../tools/perf/engineering/distributed_lab.py)在CPU上验证TP和MoE数学，并核对一次投机采样的概率质量；没有启动NCCL、网络或多卡。

## 列并行和行并行的完整结果

X[M,K]W[K,N]按W输出列分成P份，rank r得到Y_r=XW_r，shape为[M,N/P]。若后续按对应头继续计算，可以保持分片；需要完整Y的消费者则要相应gather。

行并行把X沿K分成X_r，W沿输入行分成W_r。各rank算Z_r=X_rW_r，完整输出Z=ΣZ_r。没有这个归约，得到的只是局部贡献。实验对P=1/2/4/8与完整matmul比较，覆盖两种分法。

真实接口要固定每个collective的组、序号、count、dtype和buffer依赖。不同rank以不同次序或形状进入，可能挂起或产生错误。root是rank标识，也不能与物理GPU编号混用。基础语义见[NCCL官方collective说明](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/usage/collectives.html)。

## Ring 的字节模型与暴露时间

理想ring all-reduce包含reduce-scatter和all-gather，P个rank、每rank完整逻辑payload S时，每rank发送代理量约2(P−1)S/P。P=4、S=8MiB，结果为12MiB；P=1为0。

该模型没有协议、拓扑、分片粒度、链路争用、latency和实际算法选择。不能将S/总wall time称物理带宽，也不能把NCCL总duration当关键路径。若20ms通信有15ms被计算覆盖，最多约5ms暴露；还要看依赖和下一阶段等待。

每rank内存分别核算，KV并不必然除以TP。GQA的KV头可能复制，通信buffer与workspace也可能使最紧rank更早OOM。一个rank失败时必须按通信组与状态语义处理，不能只重启Pod就续旧请求。

## MoE 的 dispatch 与 inverse routing

输入T条token，每条top-k个专家及gate。实验先生成(expert_id,token_id,slot)记录，按专家稳定排序；各组对X[token_ids]做专家matmul，最后按原token和slot加权累加。

7条token、top2产生14个assignment。输出与逐token逐专家的独立循环比较；逆排列丢失时，shape可能仍然正确但内容错位。空专家也要保留计数，不伪造一次有工作。

实验要求非负gate每行和为1、专家范围正确、同token不重复路由；容量不足在执行前报错，不静默丢assignment。真实模型的gate归一化/容量/溢出策略必须冻结。Grouped GEMM收益还要减去排序、dispatch/combine、额外buffer和跨rankall-to-all成本。

## 投机采样为什么需要 residual 分布

一次草稿token从q抽样，以min(1,p(x)/q(x))接受，接受概率质量为min(p,q)。拒绝质量R=1−Σmin(p,q)，从正差residual=max(p−q,0)/Σmax(p−q,0)补偿。

教学例p=[0.1,0.7,0.2]，q=[0.4,0.4,0.2]。接受质量[0.1,0.4,0.2]，总接受率0.7；residual=[0,1,0]，拒绝的0.3补到第二项，最后恰为p。

[speculative_mass](../../../tools/perf/engineering/distributed_lab.py)核对这个概率恒等式，包含q=0和p=q边界。实际多token算法需要在同一目标条件分布上验证，拒绝后丢弃相应草稿后缀并正确回退KV。温度、截断或greedy策略改变时须重新定义规则。概率恒等式不证明当前模型有加速，草稿成本、接受率与验证batch都可能抵消收益。方法参考[原论文v2](https://arxiv.org/abs/2211.17192v2)。

## PD 分离的传输与所有权

按本教材普通KV假设，每token24KiB，输入1024对应24MiB。若虚构可用链路为12GiB/s，单次理想传输下界约1.953ms，未计排队、序列化、同步与多rank。只有prefill/decode分离带来的净收益足够覆盖这些代价，才值得采用。

必须固定KV格式、位置、dtype、权重/引擎/配置、目标rank和原请求绑定。发送端完成copy不必然等于接收端可消费；接收确认也不允许旧执行器继续写同一逻辑状态。取消发生在交接前/中/后各需停止和回收策略。

PD、TP/EP布局或执行框架替换属于架构选择，走ADR和具体授权。本章不改项目固定来源、attempt、预算或发布协议，也不以跨引擎回退替代错误恢复。
