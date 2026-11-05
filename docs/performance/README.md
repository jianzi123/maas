# MaaS 性能学习与工作手册

这份手册分两条路线：入门路线训练“把结果算对、把边界说清”，进阶路线训练“从证据找到值得优化的算子/运行时路径”。两条路线最后汇入可评审的优化目标卡。

本次文档以代码基线5020d5c为依据。算子、运行时是性能角色主线；Go/Higress/存储用于解释端到端影响，由相应负责人协作。源码样本v0.5.6不是部署推荐，当前手册不宣称已有GPU/模型收益。

## 按你的任务选择路线

| 读者/任务 | 起点 | 完成标志 |
|---|---|---|
| 有Python基础，尚不熟LLM/CUDA的新成员 | [入门教程](onboarding.md) | 完成B01–B06，能解释正确结果与不能得出的结论 |
| 能运行脚本，希望承担性能实验 | [进阶教程](advanced.md) | 完成A01–A04，能写出合理基线、采样方式和否证条件 |
| 负责选题/评审/协作 | [优化目标与八张目标卡](optimization-goals.md) | 每张目标卡有测量点、约束、证据、门槛状态和停止/淘汰条件 |
| 需要做一次具体实验 | [执行手册](optimization-playbook.md)＋[目标卡模板](templates/optimization-goal.md) | 实验前冻结条件，实验后按证据判断 |
| 要核对练习 | [自测答案](exercises/answer-key.md) | 用推导说明原因，不只抄输出 |
| 要了解当前进度 | [阶段总结](progress-and-summary.md) | 区分作者结果、独立复核、未执行和依赖 |

## 从学习进入工作

入门：请求和token → prefill/decode → 指标与时钟 → 数值门禁 → 证据分级。

进阶：目标拆解 → timeline与roofline → Attention/GEMM/KV/Graph/通信 → 同条件A/B → 正确性/质量/业务约束 → 复核。

入门无需GPU、模型或平台Key。GPU阶段另需具体批准和兼容环境；不要为完成课程打开任何execution_enabled。

## 参考资料分层

| 资料 | 用途 |
|---|---|
| [链路、术语和指标](architecture-and-metrics.md) | 查测量点、账本及身份边界 |
| [算子工作台](operator-lab.md) | 查CPU参考、宿主校验、GPU骨架与采样命令 |
| [固定SHA源码分析](sglang-source-analysis-v0.5.md) | 沿调用路径定位候选，不把代码存在当热点 |
| [运行时实验与J02](runtime-experiments-v0.5.md) | 查混合负载、合理基线、未恢复样本和热路径成本 |
| [GEMM有限值修复](gemm-finite-fix-v0.5.1.md) | 学习NaN比较为何会误放行，以及共用门禁如何验证 |
| [现有验收契约](../../tools/perf/docs/acceptance-v0.3.md) | 查C01–C08及未批准收益建议 |
| [实验记录](templates/experiment-record.md)／[周总结](templates/weekly-summary.md) | 保存事实、决定、建议、未验项 |

## 先判断证据能支持什么

synthetic_fixture：人工记录，可验证计算；controlled_local_http：临时回环传输，可验证客户端机制；controlled_platform：真实受保护平台链路＋受控上游；real_model：获准模型/引擎环境。宿主C++校验只证明同一host gate的行为，不证明CUDA translation unit编译、GPU数值或模型质量。

工具现有输入为票据v3元数据、终态3.0、ObservationEnvelope1.0。项目协议升级以架构师确认的共享契约为准；课程不修改协议或业务政策。机器可读的[目标登记表](optimization-goals.json)是文档建议，所有执行和业务SLO门槛保持待批准。

本次任务附件还提供单页HTML阅读版，主教材/目标/答案可离线阅读；代码及工具/契约参考可在源码阅读包或项目仓库查看。
