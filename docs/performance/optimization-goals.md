# 深化优化目标：从可学习到可验证

目标不是“把所有kernel都改一遍”。先选能影响主指标的具体问题，登记成熟基线、约束、证据与否证条件，再决定是否值得实施。下面八卡是研究/排查顺序，不是已确认热点，也不是执行授权。

## 1. 统一北极星与三层目标

主指标G为同一共同观察窗T中，同时成功、质量合格且适用TTFT/TPOT/E2E达标的请求数/T。达标率另为合格数/sent；失败、拒绝、取消和pending不能从sent清单或尾部观察中删掉。必要SLO/质量未知时只能交描述结果，不判达标。

| 层 | 目标 | 验收边界 |
|---|---|---|
| K 算子 | 同shape/dtype/layout下减少成熟baseline的设备时长或等价数据搬运 | 必须数值正确；逻辑带宽不等于实际DRAM；局部收益只在本层成立 |
| R 运行时 | 同资源/精度/负载/业务约束下提高G，满足尾延迟/资源/质量条件 | 按长短/冷热/模式分层，保留失败、未恢复和观测开销 |
| E 端到端 | 将改善传到受保护平台与客户端 | 完整来源/修订/价格与账本、取消/容量/清理证据，不用fixture代替 |

优化角色以K/R为主，E层协作归因。新增资源、模型/GPU实验、政策/共享契约调整仍按已有授权和评审流程。

## 2. 把门槛写成可判定状态

每卡先登记delta（最小有效收益）、质量误差/容忍、显存/功耗/成本上限、关键场景最大退化与观察窗口。尚未批准的字段为null；null不是无限或自动通过。

已有“确认收益建议5次配对、G至少+10%、95%配对区间下界>0”继续标为待评审建议，不能直接套作全部算子目标，也不能仅凭5次就宣布统计可靠。统计单位是独立配对run，区间方法/假设/漂移要交代。

建议状态：
- draft：只定义问题与已有证据。
- ready_for_review：基线/条件/门槛及证据计划完整，等待决定。
- approved_for_experiment：具备具体授权和可执行环境。
- exploratory：已有有限样本，只作探索。
- validated_at_K/R/E：只能标实际验证到的层。
- rejected/inconclusive：触碰不变量、收益不稳或成本过高；保留负结果。

## 3. 先评估“局部更快是否值得”

用[进阶A01](advanced.md)的串行上界筛选：p为热点关键路径占比，s为局部加速，S≈1/((1-p)+p/s)。教学算例中10%占比即使2x也只约+5.3%；不能承诺全链路+100%。

门槛应从产品/框架目标反推：先有deltaE/影响比例及资源约束，再决定deltaK是否足以支撑目标。涉及排队、批处理或容量跨阈值时，上界模型不再代表真实吞吐，必须实测。

## 4. 八张目标卡

机器登记与本节一一对应：[optimization-goals.json](optimization-goals.json)。它是文档建议，execution_enabled=false；不替换既有算子或E1–E3计划。

### K01｜Attention与KV访问（operator / P0）

- **主指标与目标规则**：同一Attention子路径的device_event_ms；实际DRAM字节与有效工作量作解释量。达到预登记算子收益δK且满足数值/显存约束；只有传到R层才称运行时收益。
- **合理基线**：固定版本当前可用的成熟SDPA/FlashInfer或引擎backend；dense参考仅校验数学语义。
- **进入证据**：同一shape分布中Attention/KV或布局搬运占关键路径，且timeline与带宽/复制证据相互支持。
- **单因素动作**：一次只选择backend、布局/索引搬运或可等价融合中的一项。
- **保持不变**：Q/K/V shape、MHA/GQA/实际分页布局、mask、dtype/精度、KV长度/缓存状态、GPU和版本。
- **正确性**：suffix causal、全遮罩、GQA头映射、边界长度、finite和相同输出语义；MLA需另建参考。
- **代价/约束**：保留临时张量/拷贝、峰值显存、prefill/decode尾延迟及质量影响。
- **必交证据**：逐shape原始时延、stride/dtype、数值误差、kernel/DRAM/copy时间线、占比及基线来源。
- **停止/淘汰**：成熟baseline已优；目标占比太小；减少局部时间却增加搬运/显存或模型误差。
- **当前可做**：复核已有CPU mask/GQA练习和固定SHA入口，登记目标shape；不从dense CPU结果推断分页GPU性能。

### K02｜GEMM与Grouped GEMM（operator / P0）

- **主指标与目标规则**：按M/N/K、组分布分层的device_event_ms，逻辑TFLOP/s仅辅助。在同输入/输出语义和精度下相对成熟baseline达到δK；小M/大M分别判定。
- **合理基线**：torch.mm/cuBLAS或当前量化引擎成熟实现；16×16教学tile不是为了制造收益的弱对照。
- **进入证据**：local GEMM或组调度/重排暴露在关键路径；区分小M利用率、访存与通信。
- **单因素动作**：一次只改已有backend、组组织、布局准备或同语义融合。
- **保持不变**：M/N/K及尾部、组数量/shape序列、stride、dtype、TF32/量化政策、GPU/拓扑和输出。
- **正确性**：候选/cuBLAS/reference finite、原atol/rtol、尾部与正常值；共享host门禁通过不等于GPU通过。
- **代价/约束**：准备/重排/额外launch、workspace、峰值显存、TP all-reduce与精度变化。
- **必交证据**：成熟baseline版本、组清单、原始时延/误差、分配/准备范围、计时与通信边界。
- **停止/淘汰**：只能战胜naive循环；小矩阵launch损失未解；去掉collective或降精度才有收益。
- **当前可做**：运行现有宿主21场景并读cuBLAS行列主序映射，拟定small-M与prefill-M实验表。

### K03｜RMSNorm与相邻运算融合（operator / P1）

- **主指标与目标规则**：同输出语义的device_event_ms与logical IO GB/s代理。相对原生rms_norm或当前成熟融合baseline达到δK，所有输出和误差同时满足要求。
- **合理基线**：PyTorch原生rms_norm；若已有残差融合则必须纳入当前baseline。
- **进入证据**：norm/相邻launch及重复读写在trace中占比足够，且不是其他算子等待造成。
- **单因素动作**：一次选择block/布局，或在明确语义下研究残差/量化融合。
- **保持不变**：行数/行长、epsilon、accumulation与输出dtype、weight、残差的全部输入输出。
- **正确性**：masked lane、全零、尾部、strided参考、finite；不得漏比较残差或量化输出。
- **代价/约束**：寄存器/shared memory、occupancy、临时缓冲、数值误差与实际模型影响。
- **必交证据**：成熟baseline、每shape误差/时延、寄存器与访存、融合前后操作及IO边界。
- **停止/淘汰**：少launch却更慢；输出遗漏或误差超界；只在玩具行长有优势。
- **当前可做**：完成CPU RMSNorm练习及Triton代码阅读，目标GPU行长仍待环境/shape冻结。

### R01｜J02长短混合prefill/decode调度（runtime / P0）

- **主指标与目标规则**：J02下SLO内有效吞吐G；TTFT/TPOT分位数与未完成比例作约束。同J02/资源/业务规则下达到批准的δR，长短分层SLO及正确性均成立。
- **合理基线**：冻结当前可用的调度/切块配置，不用刻意弱化队列/批处理的naive实现。
- **进入证据**：长prefill与decode时段有干扰、queue或尾延迟证据；发生器本身未饱和。
- **单因素动作**：先仅改chunked prefill候选1024/2048/4096之一，再单独研究batch参数。
- **保持不变**：J02固定200条120/60/20顺序及hash、模型/精度/输出cap、GPU、C/到达计划、slot/rate/预算。
- **正确性**：保留实际EOS、失败/拒绝/pending，不能截短或丢长请求；质量/取消/账本复验。
- **代价/约束**：长prompt TTFT、调度CPU、饥饿、峰值显存/OOM、offered与sent差距。
- **必交证据**：完整请求与共同窗、按S/M/L及U/H分层的G/尾延迟、queue/batch/prefill/decode trace。
- **停止/淘汰**：只改善齐长平均值；靠排长队/提高业务slot；总体G提高却重要格SLO失败。
- **当前可做**：检查J02序列与采样表；实际SGLang/模型实验保持禁用。

### R02｜KV容量与前缀复用（runtime / P0）

- **主指标与目标规则**：相同H负载的G与TTFT；KV命中/逐出/重算和显存为解释量。同H on/off达到δR且U负对照/质量/预算无不可接受退化。
- **合理基线**：当前成熟缓存/逐出配置；不能以U换H作为优化对照。
- **进入证据**：有实际共享token前缀，或KV压力/逐出/重算限制容量与尾延迟。
- **单因素动作**：一次只改缓存开关或容量；KV精度变化单独立项。
- **保持不变**：权重/tokenizer/template/安全上下文、实际prefix hash、同等预热、KV/graph/activation总资源预算。
- **正确性**：模型输出与usage语义保持；命中仍完整准入计量，未知不当0。
- **代价/约束**：匹配/逐出CPU、缓存压力、冷态、隐含重算、额外内存/数值误差。
- **必交证据**：同H开关与U负对照原始数据、命中长度、逐出/重算、每rank内存账。
- **停止/淘汰**：只剩命中率提高；冷/长请求退化；以额外显存或隐式质量变化换收益。
- **当前可做**：登记prefix/tokenizer模板条件；普通KV公式与MLA/分片边界先算清。

### R03｜CUDA Graph与launch开销（runtime / P1）

- **主指标与目标规则**：同负载的G/TPOT尾延迟；launch gap与graph命中作解释量。同资源预算下稳态达δR，冷捕获成本和KV/显存约束单列并满足批准门槛。
- **合理基线**：当前有效graph配置；eager用于消融，不默认将已启用优化删除再当生产基线。
- **进入证据**：CPU launch gap可见、batch满足可捕获条件，实际can_run/命中数据支持。
- **单因素动作**：一次只调capture batch集合或对应phase配置。
- **保持不变**：实际batch分布、模式/shape/dtype、backend、GPU、图外准备与缓存/资源条件。
- **正确性**：fallback仍正确，输入更新/指针/生命周期合法；不隐藏无法捕获的样本。
- **代价/约束**：graph额外显存、padding、capture/首次请求、KV挤压及准备CPU。
- **必交证据**：命中/fallback计数、NVTX timeline、冷/稳态、分rank显存及尾延迟。
- **停止/淘汰**：GPU本已持续忙；命中少；省launch的收益被padding/显存/准备抵消。
- **当前可做**：沿固定SHA graph guard/capture/replay定位观测点；只生成采样命令。

### R04｜TP与MoE暴露通信（runtime / P2）

- **主指标与目标规则**：同总GPU/拓扑下的G和暴露在关键路径上的通信时间。达到δR且实际通信/计算/尾延迟和数值正确；增加GPU另归扩容。
- **合理基线**：当前可用的成熟collective/调度实现，保留已有overlap。
- **进入证据**：collective/dispatch/combine或expert负载偏斜在关键路径显著。
- **单因素动作**：契约允许的TP/通信组织；EP/DP/PP或PD扩展先提交ADR。
- **保持不变**：总GPU与互联、rank布局、模型/精度、消息大小与expert分布、业务负载。
- **正确性**：不省略all-reduce/同步或丢expert token；跨rank数值和异常处理验证。
- **代价/约束**：通信buffer、额外同步、overlap失效、拓扑与调度复杂度。
- **必交证据**：各rank timeline、实际消息/带宽、负载偏斜与全量请求结果。
- **停止/淘汰**：只减少总通信而未减少暴露时间；换硬件冒充收益；复杂度超出净收益。
- **当前可做**：整理拓扑/rank/消息实验字段；当前单卡本机不执行多卡实验。

### E01｜将算子/运行时收益传到受保护平台（end_to_end / P1）

- **主指标与目标规则**：客户端SLO内有效吞吐G及按shape/来源/修订分层的TTFT/TPOT/E2E。在相同业务和质量约束下达到批准δE，安全不变量零违反。
- **合理基线**：真实Go→Higress→获准来源、当前成熟安全准入/结算路径；fixture只作工具练习。
- **进入证据**：已有K/R层证据，且真实API/网关链路和观测可运行。
- **单因素动作**：沿已评审实现传播单项改动；平台归因与原后端/网关负责人协作。
- **保持不变**：模型/资源/精度、输入输出与请求序列、Key/slot/rate/预算/价格、publication/route和观察窗。
- **正确性**：鉴权、固定来源、取消、唯一结算、unknown/held与slot分离；任何一次违反即否决。
- **代价/约束**：Go/Redis/MySQL/Higress热路径、guard/NOWAIT/commit、观测开销及冷启动。
- **必交证据**：同一请求身份的client/Go/Worker数据、账本/质量/取消/清理与配对run报告。
- **停止/淘汰**：只有单算子或loopback数字；省略业务规则；净G无改善或资源/成本超上限。
- **当前可做**：对照实际内核与网关装配状态列门槛；E1未通时不生成平台收益结论。

## 5. 第一轮如何选，不机械串行

当前先完成K01/K02的已有参考、shape表和源码观测点；K03作融合/带宽案例。GPU获准后，按真实profile占比选一张K卡，候选不优就保留并淘汰；不要为了交付“优化”强写补丁。

R01/R02共用固定J02和U/H对照，R03需要launch/命中证据，R04需要多卡与ADR。E01只在真实链路可用时核验传播收益。当前本机的工具/授权缺口见[工作台](operator-lab.md)，不在课程里打开execution_enabled。

每轮最多选择少量有证据的单因素；有交互再登记小型因子实验。统一使用[目标卡模板](templates/optimization-goal.md)与[实验记录](templates/experiment-record.md)，按[执行手册](optimization-playbook.md)交付。完成准备文档、写出假设或跑过CPU回归，不等于该优化目标已验证。

## 6. 从目标卡走到具体工程改动

先用[工程主教材](foundations/README.md)推导数据结构与失败模式，再在真实 profile 出现相应触发时选题。下表给每张卡一个可落到代码和证据的方向，仍不声称已确定瓶颈。

| 目标卡 | 先解释一个具体问题 | 实现前必须写清 | 什么结果会推翻假设 |
|---|---|---|---|
| K01 | Q长2/KV长5的suffix mask与GQA，分页地址怎样读 | position/length、head映射、页表/stride、有效输出语义；对照[算子章](foundations/03-kernels-and-profiling.md) | 数值虽finite但mask错；少搬运却多转置/临时张量；R层无净收益 |
| K02 | M=37/N=53/K=29的尾部，以及真实small-M分布 | tile索引、cuBLAS布局、准备范围；Grouped GEMM登记每组shape和重排成本 | 只能战胜教学tile，或忽略prepare/通信才有收益 |
| K03 | residual+RMSNorm需要r/y两个输出 | 融合前后读写/launch与归约精度，全部输出的消费者 | 漏掉r、精度不符或register压力吞掉节约 |
| R01 | 六步调度中prefill与decode怎样竞争 | budget不等于GPU成本；计划/提交/完成分离；公平性与长请求上界 | J02长格饥饿、失败/pending上升，或者依赖更高slot才快 |
| R02 | P5 refs=0但inflight=1为何不能复用 | 完整页共享、半页COW、分配代次、完成/隔离证据与每rank预算 | 迟到写污染、跨安全域命中、冷态退化或质量改变 |
| R03 | Graph多占384MiB会怎样挤压KV | shape签名、命中/fallback、padding、输入地址生命周期和总显存 | 虚构案例KV上界68降55说明容量代价；实际G/长尾更差即否证 |
| R04 | 行/列并行的矩阵分片与归约位于哪里 | 真实rank映射、逐rankbuffer、消息和依赖；见[框架接口](foundations/05-framework-design.md) | collective总量下降而暴露时间不降，或靠省同步/漏token“加速” |
| E01 | K/R变化怎样传至同一受保护请求 | 原R/trace与活动修订、client/Go/Worker测点、唯一账本和真实路由 | 只有fixture、跨时钟拼窗、削弱准入或缺账本/取消证明 |

这里的资源和shape是教学算例。真实优化建议固定两份结果：一份是局部机制是否成立，另一份是同资源/精度/业务约束下的整体收益与副作用。若前者成立、后者失败，应保留负结果，不能更换分母或删掉困难样本。

框架建设按[R0–R3与D0–D3](foundations/06-build-and-review.md)分阶段评审：先做数学/状态参考与可恢复接口，再接真实适配器，最后做负载、质量和生命周期验收。工具准备不等于开启真实实验。
