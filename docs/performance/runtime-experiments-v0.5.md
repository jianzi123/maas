# E1–E3、J02与对照证据补充

本页是通用实验方法，不发布内部机会方案、专利草稿或新颖性判断。本轮只交付离线/CPU/源码材料，没有改变项目的发布、预算、未知占用或slot释放政策。

## 工程事实截点

MAAS-3已有4f3eb93耐久准入/结算内核、relay及协议代码，相关验证记录由其负责人交付：不能继续把真实核心表和实现都写成夹具。本轮只读该提交的docs/kernel-verification.md，没有重跑其Go/数据库测试。实际Higress证据生产者/装配、真实模型链路及GPU性能仍未验证；E1必须等实际API链路接通，不用本地fixture替代。

历史b4461d5的12个case/2400 loopback请求是受控传输证据，本轮复用而未重新宣称平台收益。

## J02 固定长短混合

[J02数据](../../tools/perf/runtime/J02-mixed-sequence.json)固定seed20261105，200条按S/M/L=120/60/20洗牌；目标输入/输出cap分别256/128、2048/256、8192/512。planned_offset_ms只是可复算到达计划，不是实测时刻或获准容量。序列hash写入[E1–E3计划](../../tools/perf/experiments/first-batch-v0.4.json)。

A/B逐条复用同一顺序、前缀/样本、并发、GPU/拓扑、权重、精度、版本、业务slot/rate/预算与冻结价表。目标token数必须等实际tokenizer+template解析后冻结，超上下文/正文限制的条目标unsupported，不能自动截短。C1/C4仅是候选，超批准容量则不执行。

E2除M/C4/U外补J02观察长prefill对decode尾部的影响；E3在同一H/J02负载缓存开关，并补U负对照。冷启动/编译/Graph capture/预热另列，不把换负载、换GPU或减少输出当优化。全部真实实验execution_enabled=false。

## 测量点与分母

| 层 | 可比较量 | 禁止替换 |
|---|---|---|
| client | 可见TTFT、E2E、all-sent成功/错误/拒绝/取消/pending与共同时间窗 | Worker均值或Go first_chunk不能当客户端p95 |
| Go/存储/网关 | first_chunk、pool/lock/guard/NOWAIT/commit、实际route、终态/slot状态 | inclusive span不相加；不从两个p95相减归因 |
| Worker/GPU | enqueue/prefill/decode、token时刻、kernel/通信/同步/搬运、KV/graph显存 | SSE chunk不当token，单算子Event时长不当框架/客户端收益 |

采样记录export丢样、trace比例、记录shape/内存的开销；正常基准和Profiler运行分开。GPU microbenchmark只标算子层证据，框架性能仍需真实SGLang固定模型与负载。

## 合理基线、未恢复样本和热路径成本

| 评审要求 | 落地规则 |
|---|---|
| 合理基线 | 当前安全基线保留成熟增量处理、有效证据复用与幂等去重；朴素全刷新仅是消融。算子用torch/cuBLAS成熟实现，不能用刻意弱实现报新机制收益。 |
| 可比条件 | 同membership/轮换/故障/到达序列、同证据权威性与新鲜度；改变政策或证据来源时另列，不能全归算法。unknown=0或单TTL仅作隔离负对照，不接入生产。 |
| 独立时刻 | 记录cancel、实际stop、safe条件满足、证据取得、release、后继请求成功；观察者独立于候选，使用共同可解释坐标。transport关闭不证明计算停止。 |
| 未恢复样本 | 同时报总数、恢复数、未恢复数、观察截止、右删失时长与覆盖率。只给恢复成功者的p95不足以证明整体恢复改善。 |
| 热路径代价 | 每次变更receipt字节/CPU/RSS，准入p95、guard持锁、NOWAIT/拒绝率、额外事务/写放大/存储，与控制面节省并列。 |
| 按维度占用 | 逐维known/held，按同币种/价表统计Token·秒或atomic金额·秒；缺观测时段保留missing，不能补0或算成实际消费。 |

纯诊断函数见[runtime_metrics.py](../../tools/perf/runtime_metrics.py)：recovery_summary保留未恢复与截止；held_area用整数累计并精确换算秒，支持大金额、不混币种。输入是假定独立受控观察；函数不验证生产JWS、不释放slot、不执行退款，也不证明候选机制正确。

## 验证与收益

先满足鉴权/绑定/预算/唯一终态/slot安全及无跨来源attempt，再按预登记主指标/最小收益/最大开销作成对重复比较。样本不足或区间跨0写未证实；全量错误/拒绝/未完成与质量退化保留。有限样本零错误不代替正确性论证。

先测E1的真实分层成本；E2/E3由获准GPU/模型/profile支持后执行。缺口包括可运行真实链路、CUDA框架/工具链与GPU授权、权重/许可、模型质量集、批准SLO、额度/预算/价表/停止参数。计划和CPU结果不是这些条件的替代。
