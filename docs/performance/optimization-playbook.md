# 优化实验手册

目标是在固定模型、资源、精度、请求序列、业务限额与质量门槛下，提升SLO内有效吞吐并观察TTFT/TPOT尾延迟。每次只验证一个瓶颈假设。当前已执行E0本地传输fixture；E1–E3仍受调用内核、网关、模型和额度门槛约束。

## 首批具体实验

| 编号 | 假设与单因素 | 固定条件 | 证据与停止条件 |
|---|---|---|---|
| E0 已执行本地夹具 | 保持同一合成HTTP/SSE响应，仅比较每请求建连与每worker复用 | 127.0.0.1随机端口；C1/C4；每case200请求；3次AB/BA探索；首内容延迟10ms、下一内容间隔5ms | 看真实TCP accept计数、TTFT/E2E、完整sent分母与cleanup。任何错误即停新请求；总限90秒。仅为controlled_local_http。 |
| E1 待真实平台链路 | 固定延迟受控上游，经真实Go→Higress调用，比较连接池/flush配置；MySQL热点单独测 | 相同Key/三维预算/slot/rate、publication/price、输入和连接条件；不绕过业务内核 | Go/Redis/MySQL/Higress分段；锁持有/NOWAIT/commit；冷/热连接；最后内容→结算→DONE。无耐久准入与唯一结算即不能运行。 |
| E2 待获准GPU | M/C4/U：baseline对照1024/2048/4096候选prefill切块，每次仅改一个值 | 实际模型/权重/镜像/GPU/topology、输出cap、其余调度参数和业务限额不变 | 版本--help及兼容ADR先核对；queue/prefill/decode、TTFT/TPOT p95、显存峰值、OOM和有效吞吐。不能截短输入制造提升。 |
| E3 待获准GPU | 在同一H负载中比较Radix缓存开/关；U负载同样开/关作负对照 | M/C4；固定模板/tokenizer；约75%共享前缀，保存实际token数/hash；同等预热 | 命中/逐出/重算、prefill、TTFT及质量/预算。不能只比较U与H就声称优化；缓存命中仍走准入/计量。 |

C4超过平台批准容量时跳过该格，不提高slot/限流。首批机器可读计划见[JSON](../../tools/perf/experiments/first-batch-v0.4.json)，execution_enabled=false；其中SLO、runtime identity与额度未填，不提供自动指向模型的执行器。

E0命令：

    python tools/perf/controlled_transport.py --output-dir tools/perf/reports/local-exploration --requests 200 --concurrency 1 4 --repeats 3 --max-seconds 90

这只会生成固定fixture的本地传输报告，不会变成E1平台基线；该工具无任意endpoint参数。analyze.py继续是纯文件离线计算器，二者职责独立。E0不能算模型Token、质量、预算或GPU收益。

## 技术项与判断顺序

| 技术项 | 先看什么 | 可以改什么 | 不能隐去的代价 |
|---|---|---|---|
| MySQL串行热点 | 全局容量保护行、global rate见证行、Key/窗口锁、commit和admission_busy | 同契约内减少非必要SQL/锁内计算，调整池与索引；锁结构变更另交架构师审定 | 不能删保护锁、弱化持久化、跳过预算行或把真源搬到Redis |
| SSE传输 | connect/TLS、服务端首片、客户端首内容、背压/RSS、结算尾部 | 连接复用、及时flush、有界缓冲、Vue增量渲染 | 不能提前发送DONE、丢弃usage或把HTTP200流内错误算成功 |
| prefill/batch | 长短混合queue、实际batch、GPU空洞与尾延迟 | 有版本证据的切块和batch参数，单因素比较 | 峰值吞吐可能牺牲在线SLO；不能增加业务容量冒充优化 |
| KV/前缀 | 每rank容量、命中、逐出/重算、权重/activation/graph占用 | 先调容量与运行请求上限；FP8 KV另需支持与质量门槛 | 显存高利用不等于高有效吞吐；不同权重/模板/安全上下文不能误复用 |
| graph/backend | CPU launch gap、kernel和通信时间线 | graph capture集合、目标硬件可用的attention backend | graph额外显存/冷启、KV容量变化及数值误差必须报告 |
| TP/MoE | 固定总资源的rank/topology、collective/dispatch/combine及expert负载 | 当前契约允许的TP；EP/DP/PP/PD扩展先做ADR | 增加GPU是扩容；不能无profile先改DeepEP或kernel |
| 冷启动 | 调度→加载→初始化→graph预热→receipt→准入 | 获准镜像/只读权重缓存、按不可变修订预编译 | 保留真实Ready/receipt屏障，不能提前放行缩短时间 |

全局锁是设计风险，不是已实测瓶颈。若准入/结算都串行持锁，简化上界受1/(每请求累计持锁时间)约束；加Go副本不会自动消掉此类瓶颈。先给锁/池/SQL证据，再评审改变粒度与rate_epoch屏障的方案。

SGLang参数依实际版本--help/镜像digest核对，参考[调优文档](https://docs.sglang.io/docs/advanced_features/hyperparameter_tuning)、[参数表](https://docs.sglang.io/docs/advanced_features/server_arguments)、[KV量化](https://docs.sglang.io/docs/advanced_features/quantized_kv_cache)、[MoE EP](https://docs.sglang.io/docs/advanced_features/expert_parallelism)。官方例子不是项目已验证兼容配置。

## 固定负载与收益判定

原24格是3种长度×C={1,2,4,8}×U/H。首批S/C1/U、M/C1/U、M/C4/U、M/C4/H，每格/变体/重复目标200 sent。探索3次配对；确认收益建议5次独立配对，4格×2变体×5×200=8000测量请求，按上界输入1280万/输出cap179.2万Token，另计预热、失败/取消与profile。这些是待审批规模，不是本轮模型调用授权。

提前冻结主指标/适用格/质量门槛及AB/BA顺序。+10%、配对95%区间下界>0仍是待评审建议；缺批准SLO只能交描述基线。统计单位是独立配对run，不能把同批相关请求当成独立实验。E0只做探索，报告不输出“平台提速通过”。

## 证据、回退与分工

每run填[实验记录](templates/experiment-record.md)，保留manifest/版本/fixture hash、完整请求、分格结果、对账、质量/取消和清理。单次越权、重复attempt、预算超额、重复结算或错误退款即否决；一次OOM/Xid停当前格。未知占用不得因slot回收/清理退款。

性能专家负责测量/分析；后端主责真实内核、MySQL/Higress适配；算法主责模型/参数及质量；运维主责获准环境/资源采集；MAAS-7独立复验，Mika协调共享契约。工具与文档不重复接管同事实现。

配置回退走受控发布修订/新publication与epoch，不绕过CR直接改运行对象。生产或真实目标变更仍需对应授权。本轮无集群写入、权重下载、GPU、供应商或付费调用。
