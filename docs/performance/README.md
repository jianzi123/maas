# MaaS 性能与框架工程手册

本手册为推理运行时、推理部署框架和性能工作提供统一入口。按“理解机制 → 做对应练习 → 定义课题 → 接入项目 → 留下验证与总结”的顺序使用。教材、练习和工作资料各维护一份，章节与具体命令通过索引连接。

高级主线新增[推理框架工程实现卷](engineering/README.md)：十四章推导和源码阅读，含原八类算法实验、真实进程恢复与新增异步CPU闭环。建议读完基础第1–3章后，按方向进入实现卷；每章都有代码和反例，不另建平行的概念清单。

当前实现进展：[异步运行时闭环](engineering/13-runtime-loop.md)连接调度、KV页池和Worker，提供七个固定场景与真实CPU线程验证。

本恢复批次新增[页预算调度与负结果](engineering/14-page-budget-scheduling.md)：复用MAAS-13源码输入，执行固定J02对照，保留失败/未恢复样本，定位first_chunk_ms无内容事件采样。

## 端到端诊断入口

当前体系工作从[诊断交付与缺口盘点](diagnostics.md)进入，使用[tools/perf/diagnostics](../../tools/perf/diagnostics/README.md)把原指标、受控sidecar、区间/显式依赖、恢复与证据索引连成JSON/HTML报告。真实测量不足时只报缺口，不命名模型瓶颈。后续单因素实验与输入门槛在同一交付页，教材作为实现/排障参考。

## 先按工作选择路线

| 你现在要做什么 | 阅读与操作顺序 | 交付 |
|---|---|---|
| 新成员入门 | 主教材第1–3章 → 标准库教学模型 → 对应B/A练习 | shape/指标/显存手算、确定轨迹与结论边界 |
| 开发推理运行时 | 第1/2/3/5章 → 第6章R0–R3 → K/R目标卡 | Scheduler/KV/Worker接口、异步所有权、正确性与框架负载 |
| 开发推理部署框架 | 第1/4/5章 → 第6章D0–D3 → 项目接点 | 发布状态机、耐久意图、真实证据、排空和UID清理 |
| 承担性能实验 | 目标卡 → 成熟baseline与源码/采样 → 执行规程 | 同条件A/B、负结果、质量/业务约束和原始证据 |
| 做团队整合与评审 | 整合地图 → 现有代码/分支 → 阶段完成条件 | 单一真源、职责边界、接线缺口和合入/验证顺序 |

## 固定使用这五个入口

1. [六章工程教材](foundations/README.md)：请求与张量、调度/KV、算子/剖析、发布协调、高级接口、分阶段实现。
2. [逐章练习索引](exercises/README.md)：对应B01–B06、A01–A04、教学脚本和十四道工程题；资源条件与预期结果集中说明。
3. [教材与研发整合地图](integration-map.md)：资料如何归并、两条框架主线如何汇合、真实代码/19项观测接点及分支顺序。
4. [八张优化课题卡](optimization-goals.md)＋[实验执行规程](optimization-playbook.md)：定义问题、冻结条件、停止/淘汰与证据判断。
5. [当前进度与归档](progress-and-summary.md)＋[修订记录](learning-change-log.md)：当前事实置顶，历史结果按原基线保留。

基础练习和进阶页分别是[B组详解](onboarding.md)、[A组详解与核验](advanced.md)。第一次学习按主教材章节走，需要命令或检查项时从索引跳转；团队评审先看整合地图。

## 工具与参考按需要查

| 资料 | 用途 |
|---|---|
| [链路、术语和指标](architecture-and-metrics.md) | 测量点、时钟、账本与身份边界 |
| [算子工作台](operator-lab.md) | CPU参考、宿主门禁、GPU骨架和Profiler命令 |
| [固定SHA源码分析](sglang-source-analysis-v0.5.md) | 从真实路径提出候选；样本v0.5.6不作为当前部署推荐 |
| [J02及运行时实验](runtime-experiments-v0.5.md) | 混合负载、合理baseline、未恢复样本和热路径开销 |
| [GEMM有限值修复](gemm-finite-fix-v0.5.1.md) | NaN反例与计时前门禁 |
| [离线分析器](../../tools/perf/README.md) | 现有受限导入格式、报告和固定合成夹具 |
| [19项观测映射](../../tools/perf/docs/observability-handoff-v0.2.csv) | request/trace、活动修订、分层耗时与安全边界 |
| [C01–C08验收契约](../../tools/perf/docs/acceptance-v0.3.md) | 完整证据条件与尚未通过的真实验收 |
| [目标卡](templates/optimization-goal.md)／[实验记录](templates/experiment-record.md)／[周总结](templates/weekly-summary.md) | 固定记录问题、事实、决定和限制 |

## 使用边界与当前基线

教学脚本用Python标准库；完整CPU练习与宿主C++按[资源表](exercises/README.md)准备。synthetic/teaching、controlled_local_http、controlled_platform、real_model各自标识，成果只报告实际验证到的层级。

性能工具沿用5020d5c，教材版起点为b67a805。本轮整合只改docs/performance的组织与导航。最新项目代码按整合地图中的固定提交核对，已有耐久内核/历史Reader与受控验证不再表述为不存在。

票据v3、终态3.0、ObservationEnvelope1.0保持原样。Go/MySQL为唯一业务准入与耐久结算真源，Higress实际选路；未知用量、slot、停止与财务held分开处理。真实导出适配和H1–H4装配列为明确接线工作。

机器可读[目标登记表](optimization-goals.json)与真实实验计划均保持execution_enabled=false。模型/权重/GPU、目标环境、SLO、调用额度与预算按具体任务的授权推进。课程和静态合并预演不自动启动框架实现、模型实验或部署。
