# MaaS 团队入门与性能工作台

这里是新成员进入项目、复现实验和回顾阶段结果的统一入口。当前项目采用Vue/TypeScript、Go、Higress、MySQL/Redis，以及Kubernetes/Helm；私有推理候选为LWS+SGLang。团队实现与运行证据不是同一回事，先看证据级别再解读数字。

| 阅读顺序 | 文档 | 阅读后能做什么 |
|---|---|---|
| 1 | [入门与本地练习](onboarding.md) | 在15–30分钟内跑离线分析和小规模本地fixture |
| 2 | [链路、术语与指标](architecture-and-metrics.md) | 解释Go/Higress/账本分工、TTFT/TPOT/有效吞吐、时钟与未知用量 |
| 3 | [优化实验手册](optimization-playbook.md) | 按瓶颈证据选择单因素实验，知道何时不能给收益结论 |
| 4 | [阶段总结与证据索引](progress-and-summary.md) | 看已完成项、真实验证边界和下一步依赖 |
| 5 | [实验记录模板](templates/experiment-record.md) | 为每个run记录可复核条件、原始证据、结果和回退 |
| 6 | [团队周总结模板](templates/weekly-summary.md) | 用事实/决定/建议/未验项写短总结，不把计划写成结果 |

工作相关入口：
- [离线分析器与C01规则](../../tools/perf/README.md)。
- [既有方法](../../tools/perf/docs/method-v0.2.md)和[C01–C08验收契约](../../tools/perf/docs/acceptance-v0.3.md)。
- [首批实验计划](../../tools/perf/experiments/first-batch-v0.4.json)：真实链路/模型实验保持execution_enabled=false。
- [控制器集成与原始历史](../integration.md)。
- [发布存储实现](../mysql-release.md)与[后端已报告的MySQL验证边界](../mysql-verification.md)。
- [v0.4共享架构](../contracts/MAAS-2-architecture-v0.4.md)及[v0.3预算正文](../contracts/MAAS-2-architecture-v0.3.md)。

证据标签统一使用：
- synthetic_fixture：人工时间戳/事件，只验证计算行为。
- controlled_local_http：本机临时HTTP/SSE夹具的实测，只验证传输与采样机制。
- controlled_platform：完整Go→Higress链路+受控上游；必须有真实准入/结算证据。
- real_model：获准真实模型/GPU或供应商端点；仍要固定资源、版本、预算及质量门槛。

现在可以运行前两类。后两类仍需唯一调用内核、网关适配和相应环境/额度输入。周总结是人工文档模板，本次没有创建自动任务或长期服务。
