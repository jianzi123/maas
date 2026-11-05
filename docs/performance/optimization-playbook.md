# 实验执行规程：把目标卡变成证据

先完成[入门](onboarding.md)或[进阶](advanced.md)，选择[八张目标卡](optimization-goals.md)之一。本页只负责“怎样执行并交付”，概念、推导和目标不再重复堆在命令清单中。

## 1. 实验前冻结

1. 用[目标卡模板](templates/optimization-goal.md)登记主指标、层级、成熟baseline、进入证据、单因素和淘汰条件。
2. 固定版本/shape/dtype/layout、模型/权重/tokenizer/template、GPU/拓扑、频率/功耗、请求序列/顺序、预热/采样。
3. 固定业务Key/预算/slot/rate、publication/route/price和质量门槛。源文件/计划hash写入manifest。
4. SLO、质量容忍、最小收益、资源/最大退化等未批准值保持null。已有5次/+10%/95%区间规则是建议，不是全层通用的批准政策。
5. 采样权限、工具和资源必须明确。课程/文档修订不打开execution_enabled。

## 2. 当前可以做的准备与练习

| 项 | 入口 | 可得到的结论 |
|---|---|---|
| CPU正确性 | operators/bench.py | 指定float64参考行为，不含GPU性能 |
| finite门禁 | operators/check_gemm_host.py | 同一host gate的21场景控制流，不含CUDA编译 |
| 源码审计 | runtime/source_audit.py | 指定SHA原文/AST定位一致，不含热点 |
| Profiler dry-run | operators/profile_operator.py | argv/门槛准备，不含实际trace |
| loopback练习 | controlled_transport.py | 本地传输/采样/清理，不含MaaS/引擎基线 |

命令详见[入门](onboarding.md)、[工作台](operator-lab.md)。已知本机GPU不等于获准GPU实验；Torch CPU构建/OpenMP冲突、Triton/Nsight Systems等历史核查结果和未验项以工作台记录为准，不能当永久环境保证。

## 3. 真实实验入口

| 实验 | 对应目标 | 设计与必要证据 |
|---|---|---|
| E1：真实平台＋受控上游 | E01，与后端/网关协作 | 实际Go→Higress路径；冷/热连接、flush、Go/Redis/MySQL/网关测点，真实预算/终态/取消证据 |
| E2：prefill切块/调度 | R01 | M/C4/U及固定J02；baseline与1024/2048/4096候选逐项比较，实际版本支持先核对 |
| E3：prefix/KV | R02 | 同H开/关缓存并补U负对照，预热相同；不能只拿U/H工作量差当收益 |
| 单算子实验 | K01–K03 | 成熟native/backend对照、数值先行、冷/稳态分离、资源/布局实录 |
| Graph/通信 | R03/R04 | 先有launch/命中或暴露通信证据；同总资源，契约扩展先ADR |

[首批计划](../../tools/perf/experiments/first-batch-v0.4.json)及[算子计划](../../tools/perf/operators/plan.json)均保持关闭。[J02方法](runtime-experiments-v0.5.md)固定200条120/60/20顺序和hash，实际token数待tokenizer/template冻结。超过批准slot的C4/C8跳过，不放宽规则。

MAAS-3已有4f3eb93耐久内核代码与局部受控验证；不能再概括为核心不存在。E1仍需实际API链路/Higress装配与授权输入，本轮文档没有重跑其验证。

## 4. 运行与停止

先正确性，再编译/初始化/预热，最后独立正常计时；Profiler另开run并标开销。保留同一窗口的全部sent及失败/拒绝/取消/pending，按shape/冷热/模式分层。

一例越权、重复attempt、绑定/价格错配、超预算、重复结算或错误退款即否决；一次OOM/Xid/OOMKill停当前格且不升级负载。触达请求/Token/金额/GPU/墙钟上限或下一请求最坏预留不足即停发。其他阈值在批准计划里有值，null不是无限。

停发按原deadline/取消语义drain，保留未恢复数量、观察截止与隔离/held。不得为收尾删finalizer或用TTL退款。配置回退走受控发布修订/新publication与epoch，不旁路CR。

## 5. 实验后交付

用[实验记录](templates/experiment-record.md)交：manifest/版本/样本hash、逐请求数据、分格A/B与失败/缺失、正常计时和profile、数值/质量、账本/取消/清理、区间方法、代价、回退和未执行项。用[周总结](templates/weekly-summary.md)分开事实/决定/建议/未验项。

同一层先判断是否满足预登记目标；只验证到K层就不出E层收益。没有稳定净收益、质量/正确性失败或成本超限，保留负结果并停止/放弃。GPU/目标集群/供应商/付费操作沿既有具体授权，不由本规程自动批准。
