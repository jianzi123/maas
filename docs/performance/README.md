# MaaS 性能与框架工程手册

当前GPU接续：[cap6固定切片验证](engineering/17-cap6-empty-cta.md)已完成。B8/L1024保持相同分段，grid由192减为144 CTA，三进程局部改善；512保留退化，未改Engine默认。

最新补测：追加sgl-kernel0.3.9.post2的成熟store_kv_cache直接调用基线，主shape无fallback实际通过；D80/480字节行明确unsupported。原型未建立稳定跨shape优势，最终优先复用成熟库，不采用教学原型替换。三项研究各三个GPU进程，初期六进程结果保留。

当前实作：[SGLang Decode/KV GPU批次](engineering/16-sglang-decode-kv.md)已跑通原始Triton后端、真实KV池/索引与两阶段核，完成split负结果、KV融合局部对照、ATen/NVRTC注册和图/异步错误验证。完整Engine/模型生成/serving尚未执行，长序列退化保留，不把局部收益写成引擎收益。

当前研发主线是 **SGLang真实推理执行路径与GPU性能**：先做Decode Attention/KV的设备基线和实际backend采样，再依据profile选择GEMM/融合、Graph或通信改动，最后验证引擎TTFT/TPOT/有效吞吐。工作入口是[GPU算子与采样](operator-lab.md)、[历史v0.5.6源码研究](sglang-source-analysis-v0.5.md)（当前GPU实测固定0.5.2，见第16章）及[K/R优化目标](optimization-goals.md)。

已有CPU公式、模拟调度器和教材用于正确性参考、故障反例与入门；测试数量不代表推理优化成果，不再扩展为本任务主线。CPU launch/调度只有在真实引擎时间线证明它让GPU等待时才成为性能课题。

K1算子实验可在GPU资源和运行库条件满足后独立推进，不等待Go/Higress平台E1。真实引擎R层另需目标模型/权重/框架版本；平台E层再验证业务链路，三层证据分别交付。GPU尚未执行时记录具体缺口，不用CPU模拟结果替代。

## 已有学习资料

本手册也为后续推理运行时、推理部署框架开发提供资料：[工程实现卷](engineering/README.md)、[异步运行时教学闭环](engineering/13-runtime-loop.md)、[页预算调度与负结果](engineering/14-page-budget-scheduling.md)。保留既有结果，不重做已交教材或CPU调度对照。

## 端到端诊断入口

当前体系工作从[诊断交付与缺口盘点](diagnostics.md)进入，使用[tools/perf/diagnostics](../../tools/perf/diagnostics/README.md)把原指标、受控sidecar、区间/显式依赖、恢复与证据索引连成JSON/HTML报告。真实测量不足时只报缺口，不命名模型瓶颈。后续单因素实验与输入门槛在同一交付页，教材作为实现/排障参考。

当前[D1消费接线](d1-wiring.md)已接入c7e863b实际Go/临时MySQL/受控HTTP导出：9条摘要及1个额外满队列场景，首协议/内容/Write/flush分列；完整client分母与平台路径仍缺，D1整体/E1未完成。

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
