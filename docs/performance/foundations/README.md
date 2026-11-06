# 推理运行时与部署框架工程基础

这条主线面向准备参与推理框架、推理部署框架开发的成员。有 Python 基础即可开始；读到后半部分，需要理解状态机、并发与数据库事务。目标是能解释一条请求为什么慢、KV 页为什么不能提前复用、一个模型为什么还不能对外接流量，并把这些判断写进代码接口与回归用例。

先读一个算例，再看运行轨迹，最后处理真实工程中的并发和故障。教材中的小模型刻意简化，教学脚本只使用 Python 标准库，不连接平台、模型或集群。带 teaching_only 的输出是逻辑演示，不能计算真实性能。

按章节做作业见[统一练习索引](../exercises/README.md)；与既有代码、角色及分支接线见[整合地图](../integration-map.md)。

## 阅读顺序与实际产出

| 章节 | 你将弄清楚什么 | 读完应交出什么 |
|---|---|---|
| [一条请求怎样变成张量计算](01-request-to-tensors.md) | tokenizer、prefill、decode、测量点与三类控制权 | 张量 shape 表、请求时间线和指标手算 |
| [调度与 KV 页如何一起工作](02-scheduler-and-kv.md) | 连续批处理、分页、共享、取消与异步回收 | 六步调度轨迹、KV 预算表和资源所有权图 |
| [从数学算子走到 GPU 实现](03-kernels-and-profiling.md) | GEMM tile、Attention mask、融合、计时与剖析 | 正确性样本、边界索引推导与热点证据计划 |
| [模型发布为什么需要协调器](04-deployment-controller.md) | CR、修订、发布屏障、ACK 未知、排空与清理 | 发布状态机、故障轨迹和对象归属表 |
| [高级工程师怎样设计框架接口](05-framework-design.md) | 组件边界、并发、背压、图与并行通信、恢复 | 接口草图、线程/进程归属、容量模型和 ADR |
| [分阶段实现与评审练习](06-build-and-review.md) | 从教学模型走到受控实现，再走到真实验收 | R0–R3/D0–D3 交付计划及 14 道工程题 |

“入门”要能算对、跑通、解释每一个状态变化；“进阶”要能说明失败时由谁恢复、如何证明资源可以复用、如何否证优化假设。无需先背完术语。第一次阅读沿正文和命令走；第二次带着第六章的评审问题回看。

## 三个教学模型与核验入口

从仓库根目录执行，Python 3.10+ 即可：

~~~text
python docs/performance/foundations/labs/worked_numbers.py
python docs/performance/foundations/labs/runtime_walkthrough.py
python docs/performance/foundations/labs/release_walkthrough.py
python docs/performance/foundations/labs/check_examples.py
~~~

最后一条命令核对正文中的固定预期和反例。第一个重算显存、tile 与蓝绿部署资源；第二个输出调度和异步页回收轨迹；第三个输出发布重试、证据不足与排空轨迹。预期值和简化条件分别写在第二、三、四章。它们没有实现 GPU Worker、Kubernetes Operator 或耐久业务账本；后续实现必须补齐第五章的接口和故障条件。

## 与项目工作的关系

MaaS 当前技术边界是 Vue/TypeScript、Go、Higress、Kubernetes/Helm，私有推理优先研究 SGLang/LWS。本教材不改变选型或共享协议。运行时研究负责调度、内存和 GPU 执行；部署研究负责把指定修订安全地变成可服务实例；Go/MySQL 继续掌握业务准入与唯一结算。

源码阅读沿用 [SGLang v0.5.6 固定 SHA 分析](../sglang-source-analysis-v0.5.md)，不代表推荐部署该旧版本。共享语义按架构师最新记录及 [MAAS-3 的 2319eb6 内核提交](https://github.com/jianzi123/maas/commit/2319eb62d84f278d1dd6d444ce52e532e202766e)理解：票据 v3、终态 3.0、ObservationEnvelope 1.0；本轮未重新执行其验证。已有耐久内核与受控验证不能概括为不存在，实际 Higress 装配和真实平台/模型实验仍须另行验收。

下一步用 [八张优化目标卡](../optimization-goals.md)选择有证据的课题，用[实验记录模板](../templates/experiment-record.md)留下可复核结果。GPU、模型、权重、目标部署和付费调用遵循具体授权；所有现有真实实验计划保持禁用。
