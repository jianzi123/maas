# MAAS-10 性能方法 v0.2：v0.4契约与离线工具

日期：2026-11-04。负责人：MaaS 资深性能优化专家。性质：方法与可执行离线工具；报告数字仅来自明确标记synthetic的固定夹具，真实实验及性能提升未执行。附件中的数字是实验候选条件，不是成员确认的产品默认值、SLO 或调用额度。

## 1. 依据、边界与待决策

本版基于MAAS-1需求v0.4、MAAS-2已设计复核的架构v0.4（正文附件01a1a637-46e4-7513-adfa-a0630c1efc96、契约包01a1a637-5727-730d-9662-60ec324daa42）及包内保留的v0.3预算正文。当前协议统一为票据v3、终态request.finalized 3.0、独立ObservationEnvelope 1.0。2.0事件与v2票据仅是历史，不作为当前分析器输入，也不做静默降级。预算算法、唯一结算、未知用量、原slot回收门槛继续继承v0.3。方法v0.1保留为历史；跨角色/共享契约改动仍由Mika与架构师负责。

成员决定：Go 唯一业务准入与结算，MySQL 唯一耐久预算/计量，Redis 速率门禁，Higress 实际选路；三维预算、固定来源、不自动重试生成或跨来源回退。每逻辑模型一个发布 CR；ModelRelease 名称、LWS 与 SGLang 为当前候选，具体兼容性待验证。CR 既不保存秘密，也不复制实时账本。

本次交付方法增量、离线分析器/测试/固定合成夹具、待审批运行清单及埋点映射。不下载权重、不创建服务/集群、不访问模型端点、不运行 GPU 或付费压测、代码仅限独立tools/perf，不修改MAAS-11控制器、共享契约或根模块；按仓库条件提交PR。沙箱再次出现 Windows 1909，经工具审批的沙箱外 Multica 查询与附件读取成功；这不证明沙箱账户修复。

| 阶段 | 进入门槛 | 可产生的证据 |
|---|---|---|
| 当前工具准备 | 方法已评审及本轮交接 | 本文、离线代码/测试、synthetic夹具与报告；无真实性能结果 |
| 受控链路基线 | 获准环境；Key/三维预算/slot/request/唯一终态内核；Higress、MySQL、Redis与受控上游就绪 | 鉴权/账本正确性及平台开销；不可冒充真实引擎性能 |
| 私有 SGLang 基线 | 上述条件，以及模型/权重许可、GPU/拓扑、兼容 ADR、获准部署和负载 | 私有推理与完整平台基线，含冷启动与资源 |
| 外部 API 基线 | 明确供应商/模型/协议/安全凭证引用、调用额度、价格与可信 Token 上界 | 端到端与平台观测；供应商内部排队/内核不可见须标不可获取 |
| 优化对照 | 固定基线与正确性通过；瓶颈 profile；对应变更授权 | 单因素对照与质量/取消/预算复验；未经运行不报提升 |

执行前由成员/Mika确认：目标模型及权重摘要/许可/访问渠道；GPU SKU、单卡显存、数量、节点/互联；可写环境与版本矩阵；目标 TTFT/TPOT/E2E/有效吞吐；负载及上下文支持；最大调用次数、输入输出 Token、金额、GPU 时长及墙钟时间；预算周期/数值/币种/冻结价表；资源与停止阈值。缺任一必需运行输入不影响本方法评审，但阻止对应实测。Codex 接入含义仍待澄清，不以文本 Chat 冒充兼容。

## 2. 测量口径与样本分层

使用同一进程单调时钟计算时长，UTC只用于关联。客户侧 `t0` 为请求计划发出时刻，`t_send` 为实际开始发出；记录发生器等待 `t_send-t0`。客户端观测 `t_first_content`、`t_last_content`、合法正常终止 `t_done`；Go 观测 receive/admission commit/finalization commit；Higress 观测授权、首字节、上游发送及传输关闭；模型观测入队、prefill、decode。跨机时钟记录偏差与同步方法，不用未校准时间戳直接相减。

| 指标 | 定义与分母 | 缺失/异常处理 |
|---|---|---|
| 可见 TTFT | `t_first_content-t_send`，首个非空可见文本；另报计划 TTFT=`t_first_content-t0` | role、心跳、usage-only、空 delta 不算；首字节与首片另列；无内容为 null，不填0 |
| 模型 TTFT | 引擎请求接收至首生成 token，标明包含的队列/分词阶段 | 与可见TTFT不同；外部来源不可见则 null；不混用引擎原生 TTFT 定义 |
| TPOT | 有逐 token 时刻及 `N>=2` 时，`(t_token_last-t_token_first)/(N-1)` | 以可见输出或引擎全部生成分开标记；`N<=1` 为 null |
| 客户端 TPOT 代理 | `visible_tpot_proxy=(t_last_content-t_first_content)/(N_visible-1)` | `N_visible`须由固定分词器完整输出计数；chunk可含多token，明确代理；不可称真实ITL |
| ITL/生成速度 | 真逐token间隔分布；速度为`(N-1)/decode_interval` | SSE仅有chunk时只报chunk-gap；隐藏推理与可见输出分列；不把字符数当token |
| E2E | `t_done-t_send`，客户端收到合法成功终止；另报计划E2E和last-content时长 | raw EOF、HTTP200但流中error、缺DONE都非成功；取消/超时/失败各自报终止时长 |
| 请求吞吐 | 成功请求数/共同观测墙钟 `T` | 同时报offered/sent/admitted/succeeded/rejected；拒绝不算成功吞吐 |
| Token吞吐 | 有可靠已知usage的实际输入、输出token分别求和/T；另报引擎生成计数 | 子集cache/reasoning不重复相加；未知为null并报覆盖率，不把预留/held计为实际token |
| 时限内有效吞吐 | `满足质量且成功且TTFT<=S_ttft且E2E<=S_e2e且可判定时TPOT<=S_tpot的请求数/T` | SLO待批；缺必要观测为不可判定，不入分子；同时报sent为分母的达标率及覆盖率 |
| 错误/拒绝 | 技术错误数/sent；各类拒绝数/sent；admitted失败数/admitted | 预算、速率、slot、锁冲突、依赖故障、上游故障、协议错误、取消、超时分别列出 |
| 取消 | 发取消至Go感知、可信网关传输关闭、模型abort确认、slot释放四个独立时长 | 关闭不证明供应商停止计算；模型不可见为null；slot释放不退款 |
| 冷启动 | CR提交→工作负载就绪→网关实际应用→业务可调用；另报进程启动→首个成功内容 | 分调度/权重加载/初始化/graph capture/发布屏障；每个条件有真实观测才算 |
| 资源 | 每GPU显存used/peak、KV容量/使用/逐出/重算、GPU利用率/功耗/温度；CPU、RSS、网络、磁盘、OOM | 标采集工具/单位/周期/缺失，NVML显存与分配器allocated/reserved不同；不相减冒充KV大小 |
| 质量与成本 | MAAS-9固定质量集，MAAS-7独立复验；已知token按冻结价表算平台成本 | 金额使用atomic十进制字符串；未知成本另列；不承诺等同供应商账单 |

客户端保留全量逐请求结果（无正文/秘密），分 `run_id/cell_id/replicate/source/model_revision/cache_state/result`。默认建议p50/p95；p99只在单格有效样本至少1000且额度获准时作描述并给区间。每项同时交count、eligible、missing、超时/删失数及所用分位数算法。不能把失败删除后只报成功尾延迟；成功分布与所有请求结果分布并排。TPOT报告逐请求分布与按生成token加权汇总，标明权重，二者不混用。

吞吐的主报告采用有限批次：从首个计划请求至该批全部终止或到达预先批准的drain截止的共同T，所有变体同样计首尾。稳态窗口如另报则预先固定边界，并报告窗外尾部、在途数及归属规则，不能靠截断尾部抬高吞吐。超时样本不当作在deadline处正常完成；报告删失及未完成比例。客户端发生器CPU/连接池瓶颈单列，实际发出率不足目标即标该格无效。

## 3. 采样、调用树与可归因性

所有基线格：客户端逐请求全量；服务侧计数/直方图全量；CPU/RSS、GPU/NVML、KV与网络建议1秒采集；MySQL/Redis统计建议5秒。短脉冲用峰值计数与小窗口profile补充，不能声称1秒采集捕获所有瞬时OOM之前的峰值。记录collector丢样、exporter队列、主机时间偏差和采样配置。

诊断小批次建议100% trace，正式性能格固定1%按request_id哈希采样并另保留错误/取消/未知用量样本，记录实际采样率及丢弃；账本与拒绝计数绝不采样。trace只用于分解，不用有偏的错误保留样本估总体延迟。对同一小格做一次观测开销校验；所有A/B使用相同采样配置，profile开启的运行单列，不当作吞吐主结果。

调用树为 `client → Go入口 → Higress → Go ext-auth → Redis、MySQL准入 → Higress上游 → SGLang`，流返回后 `Go唯一终态 → MySQL`。Go入口及Higress span含嵌套等待，绝不能把这些inclusive时长逐项相加。分别报告inclusive与exclusive/子span覆盖，并按同一request的时间区间做关键路径分析；不能用`p95(E2E)-p95(模型)`推算网关p95。

| 层次 | 必需观测 | 能回答的问题 |
|---|---|---|
| Go | Key验证、序列化/分词或上界计算、入口排队、ext-auth、转发flush/背压、cancel、终态持久化与DONE发送 | TTFT前业务开销；尾部是否卡在账本或慢客户端 |
| Redis | 连接池等待、命令往返、脚本执行、permit结果、epoch状态、重建 | 速率门禁与连接/网络的分别贡献；不可测服务执行时不从RTT猜 |
| MySQL | 连接池等待、事务总时长、各锁申请/返回、NOWAIT冲突、rate见证写、reservation/request/slot写、commit与ACK状态、终态/回收 | 全局容量/Key/窗口热点、持久提交成本；NOWAIT失败也须统计 |
| Higress | ext-auth等待、路由/适配、连接池、DNS/connect/TLS、上游首字节/末字节、flush、attempt_count、active_streams、sealed/关闭证据 | 实际选路及传输开销；证明没有自动重试与绕过 |
| 模型 | enqueue/schedule、tokenize、prefill、decode步/批、detokenize、KV逐出/重算、通信、abort确认 | 排队、计算、内存、通信或CPU调度瓶颈 |
| 网络/主机 | 各段RTT/连接复用、重传、带宽、CPU调度与GPU空洞、磁盘权重加载 | 能确认的网络/主机因素；未覆盖残差标unattributed而非全归网络 |

服务端原生TTFT可能以空文本的detokenize输出为终点，与本方案“可见内容”口径不同，须保留原名并增加观测scope标签。[SGLang Production Metrics](https://docs.sglang.io/docs/references/production_metrics) 是语义核对入口；目标镜像实际暴露的指标及桶仍须现场核验。

## 4. 固定负载矩阵

完整条件见同附 `experiment-plan-v0.2.json`。这些是等待审批的候选实验，不是可执行压测配置。运行前填写输入门槛并冻结 `resolved-plan.json`，生成其SHA256；每次更改条件产生新plan/run，不静默覆盖。

| 维度 | 候选固定值 | 冻结规则 |
|---|---|---|
| 长度L | S:输入256/输出cap128；M:2048/256；L:8192/512 token | 输入按固定tokenizer+chat template的实际转发文本计数；输出为上限，实际EOS长度另记；API body/字符/上下文不支持的格标unsupported，不暗中截短 |
| 并发C | 1、2、4、8 | C为发生器在途请求上限；必须<=批准运行上限。平台slot/限流/预算原值固定，不能为跑到8而放松；超slot格单列为过载/拒绝，不能算模型容量 |
| 前缀P | U:模板以外无共享输入；H:约75%输入为固定公共token前缀、预先热入缓存 | 公共前缀和后缀artifact hash固定，记录实际共享token数/命中；“U”不声称连模板都无命中；H预热也计调用/预算 |
| 核心格 | L×C×P，24格，stream=true | 仅逐步运行获准的子集；不一次自动扫全矩阵 |
| 非流式 | 3长度×C={1,4}×U，6格 | 客户端TTFT不可获得，不把完整响应时间当首token；引擎TTFT另报 |
| 冷启动 | C=1，S/U，权重本地缓存命中与未命中分别5次候选 | 仅获准本地已可访问权重；不自动下载或清用户缓存；进程冷/前缀冷/权重缓存冷分开 |
| 固定混合 | S/M/L按60/30/10%，C={1,4}，U/H各一份，固定shuffle seed | 4格；相同请求序列，防止仅优化同长请求；长度分布实际值随报告交付 |
| 开环 | 先用批准核心格得参考λ0，再冻结{0.5,0.8,1.0,1.2}×λ0 | λ0定义为该基线最后一个同时满足SLO/错误阈值的sent req/s；无SLO则不选λ0。预生成到达序列，限制最大在途与总数；撞安全上限立即停发并记未发计划 |

建议先运行4个探索格：S/C1/U、M/C1/U、M/C4/U、M/C4/H；C4不获准则该格不执行，不自动代换。其他格由结果和额度决定，A/B始终运行相同批准集合。

每格每变体候选目标 `N=max(200,20*C)` 个sent请求、3次配对重复、单次发压上限180秒；先触达时间/预算/请求数上限即停止新请求，并按原请求截止drain。样本不足200只能报描述统计，不能声称可靠尾延迟或为凑样自动突破上限。流结束失败也计sent；每个配对运行采用同一预生成序列，顺序固定为AB、BA、AB以降低时间漂移。对照前允许一次配置专属预热，建议至少30秒且2C个成功请求，最多120秒，未稳定则该次标warmup_failed；预热请求同样受业务限制并计入总额度。H额外按固定前缀预热清单执行；U预热使用独立前缀，避免污染测量输入。

不跨变体遗留热缓存：预热/重启/缓存处理仅用获准接口并记录；不能在共享生产实例清cache。冷启动计时不可删除初始化/graph capture。真实语义负载保留EOS，不强制越过EOS生成垃圾以凑长度；如引擎专用固定长度微基准获准，必须单列，不能替代平台结果或质量验收。

预算估算在运行前包含预热、冷启探测、失败/取消和全部重复：已选核心格若C<=8，3配对重复即每格每变体至少600个sent目标；24格两变体至少28800个测量请求，另加预热等。此数仅用于提醒审批的量级，绝非本轮执行授权；N、时间上限和提前停止可能使实际更少。按每格输入/输出可信上界及最坏冻结价表逐请求估算总Token/金额，不以实际EOS节省作为预先可用额度。

## 5. 正确性、异常和生命周期场景

下列是独立小批次候选，每场景10次，具体故障注入、两副本及生命周期操作必须另获准。优先用受控上游；与性能成功格分开统计，不用注入错误抬高拒绝吞吐。

| ID | 固定触发条件 | 必查结果/观测 |
|---|---|---|
| E01 | 单独耗尽请求预算；其他维度充足 | request_budget_exceeded；无上游、无新reservation/slot；拒绝不伪造终态事件 |
| E02 | 单独耗尽Token预算 | token_budget_exceeded；原子拒绝，未知占用不得被清零 |
| E03 | 单独耗尽金额预算 | money_budget_exceeded；按冻结价表/整数精度，无跨币种合计 |
| E04 | 速率超限、slot不足、MySQL NOWAIT冲突分别触发 | rate_limited/concurrency_exceeded/admission_busy分列；Redis许可可能保守消耗，不重复业务扣量 |
| E05 | 取消在首内容前、首内容后、已知usage前各10次 | 分三格；记录cancel传播/可信关闭/模型abort/终态/slot；未知usage为null与held |
| E06 | 客户端读速率固定受限、连接中断、原请求超时 | 有界缓冲与背压；无额外attempt；超时/取消不计为成功；停止后不能把模型继续计算当已证停止 |
| E07 | 受控上游缺失全部usage、部分usage、真实0、流式error/EOF | 0/null区分，known/held逐维结算；无DONE不成功，无usage不报0 Token吞吐 |
| E08 | Redis不可用/ACK未知/epoch重建；MySQL不可用/commit ACK未知 | 故障关闭；request/event幂等查证，不能重放生成；恢复耗时及rate见证热点 |
| E09 | 两Go副本争同一Key最后一份三维预算及一个slot | 提交不超额度/容量，唯一结算；双副本流量分布和锁冲突可追溯 |
| E10 | 同一终态重投、矛盾hash、迟到usage或关闭证据 | 同hash幂等/矛盾拒绝；slot回收不第二次结算/退款；trace不能作为账本退款证据 |
| E11 | 带在途流更新/回滚模型；新修订路由或登记未Ready | 原请求固定旧活动修订/来源/价格；新请求只用一致Ready状态；不跨来源fallback |
| E12 | 两模型并发发布、暂停/删除其中一个，排空及恢复 | 关联CR和共享对象条目；其他模型/Secret/PVC/账本保留；发布控制器不重置预算 |

对账：固定观察截止时刻，`admitted=五类已提交终态之和+仍在途/待恢复数`，拒绝在准入外；恢复完成后再次封账验证在途归零或明确阻塞。每request最多一个终态，每allocation最多一次释放；Redis计数/源日志不累加业务用量。对known、inflight_reserved、uncertainty_held按原周期及维度核对。首次真实调用前须完成最小耐久内核，不能等统计界面。

## 6. 停止条件与清理

实际批准数值填入伴随JSON的approval门槛；null表示不能运行，不是无限制。候选资源阈值仅供评审，运维可按设备安全规范收紧，不能自动成为生产默认。

| 条件 | 动作 |
|---|---|
| 实际上游来源/CR活动修订/价格与准入快照不符，重复attempt、越权、超预算/重复结算、任何秘密泄漏 | 立即停止整个实验的新请求，保留脱敏证据，隔离问题配置，交Mika及对应负责人处理 |
| 一次GPU OOM、Xid、设备失联，或容器OOMKill | 立即停当前格并停止升级负载，不自动重启/重试凑成功；先查profile与资源，不把失败格删掉 |
| 剩余额度不足下一请求最坏预留，达到总请求/Token/金额/GPU时长/墙钟上限 | 停发；保留原请求上下文drain并核对账本；已有held不能当可用余额 |
| 候选：连续30秒GPU显存>95%或主机内存>90%批准容量；温度/功率超过设备批准上限 | 停当前格，获准诊断后再决定；无有效采样不能宣称安全通过 |
| 候选：最近至少100个sent技术错误率>1%，或连续3次依赖故障 | 停当前格；预期负向格单独用其期望结果判定，不能让预期429触发成功格结论 |
| 候选：连续两个30秒窗口p95超过批准SLO的2倍，或队列持续增长30秒/到达批准在途上限 | 停发过载，记录offered与sent差；样本不足/无SLO时不启用该数值判据，但仍受硬上限约束 |
| 发生器实际速率无法达到计划、观测丢失、配置/样本hash漂移、账本无法查询 | 标格无效并停止，恢复输入后新建run；不自动通过增加并发补偿 |

停发不等于强杀在途模型。优先按原请求超时/取消契约排空；必须强制中止时遵守已授权处置，记录未确认的传输/计算/用量。仅可信关闭证据或经过验证的硬截止规则可回收slot；不按一次trace空白、context取消或TTL推断退款。发布排空/删除遵循MAAS-2，不为实验擅删finalizer、共享资源、用户权重缓存或Secret。结束后交仍在途、隔离slot、unknown held及待恢复数，不隐藏遗留占用。

## 7. SGLang profile与参数实验顺序

先通过目标模型/GPU/精度/驱动/CUDA/PyTorch/SGLang/attention backend/LWS的兼容ADR，冻结镜像digest与实际`--help`输出摘要。文档随版本变化，不能照抄最新参数到未知旧镜像；当前官方CUDA graph参数已有分prefill/decode配置，旧flag可能被弃用。下面参数只是需核验的入口名。[SGLang Server Arguments](https://docs.sglang.io/docs/advanced_features/server_arguments)

每一步遵循：提出瓶颈假设→保存原配置与profile→只改一个因素→同格复测→正确性/质量复验→保留或回退。参数依赖时在单因素筛选后只对有证据的两因素做2×2交互验证；资源拓扑改变的新结果另设基线，不与资源不同的旧结果直接宣称同资源提升。

| 次序 | 进入证据与实验 | 观察与否决条件 |
|---|---|---|
| P0 原样基线 | 保存全部有效默认、启动日志摘要；先受控链路，再SGLang完整链路；无patch | 建立平台/模型分解，确认发生器足够，预算和质量正确；无基线不跳调参 |
| P1 并行/拓扑 | NCCL/通信与内存profile；在固定总GPU/模型精度下比较可行TP，必要时PP/DP；MoE的EP仅在模型与互联支持时加入 | 每rank通信/空洞、单请求TTFT/TPOT与总吞吐；TP/PP/EP/DP维度与LWS组/Pod/GPU映射由MAAS-9/2确认，不机械相乘；禁止另加Router绕过Higress |
| P2 KV容量与前缀 | 先保持KV dtype，安全范围小步调整mem-fraction-static/容量，再独立比较radix缓存开关，U/H两类 | OOM余量、KV占用/逐出/重算、命中与尾延迟；公共前缀冷热分开；KV量化必须另列质量/硬件支持门槛 |
| P3 prefill切块 | 长输入prefill占用阻塞decode或峰值显存证据，比较批准档如1024/2048/4096；未支持档跳过并写原因 | TTFT/TPOT公平性、峰值显存、长短混合有效吞吐；不以截短输入改善TTFT；禁无限制切换max_tokens |
| P4 batch/调度 | 调度队列、实际batch、GPU空洞证据；独立调max-running-requests、max-prefill-tokens，必要时overlap/保守度 | 业务slot/速率/三维预算保持固定；若平台上限挡住模型调参效果，结论为当前受限/待另批引擎微基准，不放开业务规则 |
| P5 CUDA graph | CPU launch gap与capture/replay覆盖率证据；对照eager/目标版本graph及捕获batch范围 | capture冷启时间、额外显存、padding浪费、稳态TPOT；配置对应prefill/decode阶段，回退前一档；profile运行与正常性能格分开 |
| P6 attention/通信实现 | 前述参数后仍存在可定位热点，比较目标硬件/精度实际支持的backend与通信实现 | 输出质量、数值/确定性容忍、内存与错误；不凭宣传启用不兼容kernel，变化单列 |
| P7 量化/投机/算子补丁 | MAAS-9质量门槛；只有profile显示具体kernel/通信瓶颈才提出patch | 列热点占比、目标函数/调用、补丁版本/来源/适用形状、数值误差、预期上界、回退；由算法/对应负责人实施，MAAS-7独立复验 |

SGLang官方调优建议提示批量、KV利用率、prefill与调度之间存在取舍，但其中离线吞吐导向建议不能直接作为在线业务排队策略。[Hyperparameter Tuning](https://docs.sglang.io/docs/advanced_features/hyperparameter_tuning)；本项目以批准SLO内有效吞吐及业务正确性共同选择，不能只选最大batch。

profile采用逐层方法：低开销指标/trace定位平台或引擎→少量代表格使用PyTorch Profiler观察CPU/CUDA、prefill/decode和通信→必要时Nsight Systems看时间线，再针对单热点Nsight Compute。所有rank保存节点/进程/rank与修订映射；只profile批准的小窗口，例如10个请求或5秒上限，保留时间线和原始脱敏trace。profile控制端点仅管理网可达，不能对公开调用入口暴露。

官方区分在线serving、offline吞吐和静态单batch工具；后两者不能证明平台在线性能。[Benchmark and Profiling](https://docs.sglang.io/docs/developer_guide/benchmark_and_profiling)；只有获准的引擎微基准才使用它们，报告必须标出绕开的HTTP/调度/业务环节，不将其数字作为业务基线。正式平台负载始终经Go→Higress，默认无额外直连。

优化收益只有运行后才计算：延迟下降=`(A-B)/A`，吞吐提升=`(B-A)/A`；A为0或指标未知时不计算。每个相同格交原始A/B、三次配对差异与区间、失败/缺失/质量/预算结果，不只交百分比或最好一次。vLLM对照交MAAS-9统一模型与资源条件，不能拿不同精度、上下文或输出长度的结果证明引擎优劣。

## 8. 给MAAS-2与MAAS-11的埋点交接

这是请求架构师审定、后续实现时采用的清单，本次不改任务负责人或接管MAAS-11。字段名除现有契约外均为建议。精确清单见 `observability-handoff-v0.2.csv`。

**记录分层：** 当前request.finalized 3.0仍是封闭业务事件，必需invocation_binding，绑定model_release_uid/namespace/name/generation、release_revision、publication_id、activation_epoch、route_binding_sha256、admission_purpose及price_snapshot_id/price_version。预算/价格/能力/来源上下文保持准入时快照；旧在途不能跟随当前CR改写。独立ObservationEnvelope 1.0关联request_id、trace/span、experiment_ref、runtime_metadata_ref、gateway_observation_ref及retention_policy_ref；run/cell/replicate在run registry关联，不塞进终态或预算账本。

first_chunk_ms已由架构明确为Go入口至首内容delta的服务端时长，对应timing.server_first_chunk_ms；不等于timing.client_visible_ttft_ms。RuntimeMetadata只记实际采集的weights/tokenizer/chat_template/effective_config摘要、engine image/commit/profile及rank_mapping_ref，未知为null，ExternalAPI可not_applicable。具体19项映射见伴随CSV；Schema未有的细粒度信息标记为受控trace/rank/run关联或后续待审扩展，不能直接增添封闭envelope字段。观测与工具不产生授权、结算、退款、网关receipt或关闭证明；传输证据仍v1，以完整v3票据摘要绑定。

| 优先级/接收方 | 请求的字段或事件 | 验证方法 |
|---|---|---|
| 必需，MAAS-2/后端 | Go生成request_id；可信trace_id/span_id/parent与run/cell/replicate关联；拒绝独立观测记录 | 一条正常、拒绝、取消链能查询；外部自报ID不变成授权事实；trace头不泄露票据/预算/凭证 |
| 必需，MAAS-2/11 | 准入快照绑定model alias/source/CR namespace-name-UID/generation/active revision；actual route与gateway config revision | 更新/回滚中在途请求保持旧绑定；缺可信绑定关闭新准入；desired generation与observed/active分别记录 |
| 必需，MAAS-2/11/算法 | 权重artifact digest/tokenizer/template修订；引擎image digest/commit；有效参数hash/精度/backend；LWS UID/group/rank/pod UID/node/GPU UUID或受控映射 | request→active revision→不可变artifact/config快照可连接；记录实际运行配置而非仅CR desired；多rank完整 |
| 必需，后端/MAAS-2 | 分层时点、各准入/结算阶段span、预算拒绝维度/代码、价格/能力/策略修订、submission state、终态/slot各自状态 | known/held/null保留原语义；拒绝不伪造admitted/finalized；不能从观察器发第二份结算 |
| 必需，网关/后端 | 实际route/source与attempt数、ext-auth状态、传输关闭证据引用、取消原因及传播时点 | trace中的attempt_count不是可信退款证据；证据仍由已验证reporter产生并按原JWS校验 |
| 必需，MAAS-11/运维 | CR reconcile start/end/reason、observedGeneration/conditions、desired/active revision、资源应用与网关ack、业务准入开关、排空/回滚/清理各阶段及失败 | CR“写入”不等于“可调用”；共享对象只关联本模型条目；ExternalAPI无GPU/LWS资源记not_applicable |
| 诊断，运维/算法 | GPU/KV、batch/queue、通信、CPU/GC/网络、Redis/MySQL池和事务指标，trace export丢失 | 指标与pod/GPU/修订时间区间可连接；缺指标明确标missing，不生成虚假0 |

发布观测事件当前固定为request.observation以及 `release.reconcile / workload.ready / gateway.applied / admission.enabled / release.drain / release.rollback / release.cleanup`；其当前字段见ObservationEnvelope 1.0。它们是观测事件，不是新业务账本；共享契约不是已运行证据。每事件包含actor/controller版本、CR UID/generation、desired与active revision、resource reference、阶段结果/错误原因和时间；不要塞请求正文、Secret原值、完整URL查询参数或签名票据。

trace传播可参考SGLang的OpenTelemetry支持，实际SDK/传播头与Higress适配必须验证；不能把“文档可用”当成本项目已连通。[Production Request Tracing](https://docs.sglang.io/docs/references/production_request_trace)

request_id、trace_id、Key ID、CR UID、权重digest等高基数字段放受控trace/关联表，不做每请求Prometheus label。聚合指标仅使用有界service/stage/result/error_class/source_type/profile_id等维度，运行修订通过独立元数据关联；不把Secret引用的敏感值或Key原值放label。日志/trace允许的关联数据及保留期待架构/运维定稿，压测原始输出若用于质量核查须单独受控保存；正文不得进入常规日志。

## 9. 运行报告与验收映射

每次运行应交：批准记录及resolved-plan/hash；各镜像/权重/配置/fixture/hash清单；CR活动修订和实际route绑定；发生器工具版本/源码修订与命令参数（剔除秘密）；逐请求脱敏结果与采样配置；分层指标/资源时间序列；小窗口profile；账本对账；质量/取消复验；停止与清理记录；A/B汇总与限制。工具准备阶段提供固定synthetic报告实例；真实运行报告仍待后续获准执行。

| 需求/用例 | 本方案覆盖 | 本轮结论 |
|---|---|---|
| A01–A24调用、鉴权、流式、三维预算、MySQL/Redis恢复 | §2–6、§8，E01–E10，交MAAS-7运行复验 | 有方法，未运行 |
| A25–A29模型契约、来源、发布就绪、协调恢复 | 修订关联/发布分段、受控与真实来源分层 | 不替代CR Schema/部署验收，待MAAS-2/11 |
| A30–A32更新回滚、排空删除、共享隔离 | E11/E12及原请求不可变绑定 | 有观测与场景，未运行 |
| A33依赖与版本/Helm | 运行门槛与revision清单；WSL/GPU证据分开 | 运维验证待执行 |
| A34基线与优化 | 固定矩阵、profile顺序、A/B、质量/取消/预算验收 | 阶段一方法可评审；真实基线及一次优化对照尚未完成 |

本轮完成v0.4协议对齐和离线工具准备；固定合成夹具和本地测试只证明解析/计算行为，未验证目标引擎参数、真实质量/性能/成本或A01–A34运行验收。本阶段交付后提交in_review；真实链路、GPU及优化对照仍按Mika交接与输入门槛执行。

## 10. 离线工具计算约束

工具用法和报告格式见tools/perf/README.md，固定输入/输出见fixtures/synthetic.json与fixtures/expected-report.json。默认无网络路径、无服务；输入为已经脱敏的本地JSON，包含完整发送清单、一个全覆盖client ObservationEnvelope/请求、可选其他层观测、完整3.0终态及本地RuntimeMetadata/GatewayObservation。SSE wire片段只用于本地解析，合成文本不进入报告。实际导入不能携带秘密或真实正文。

本地sidecar字段scheduled_ms/sent_ms/end_ms、frames、visible_tokens、engine_token_times_ms、quality_pass、rejection_code是工具输入，不是新增共享契约。它们与clock_scope和冻结tokenizer摘要绑定，不能从usage-only或chunk数推算可见token；server/client/model时钟不互减。request.observation里的active_revision按该调用捕获的活动上下文匹配invocation_binding，当前CR状态另用release事件记录；不能由当前CR回填历史绑定。库验Schema，另核对跨记录publication、route摘要、价格、唯一终态、用量子集与账本向量守恒；只做诊断，不证明MySQL真实对账或slot释放。

窗口为[start_ms,end_ms]的预先声明发送/观察批次；所有请求必须位于窗口，end_ms=null的请求截至窗口末仍pending并显式计删失。吞吐分母使用整个声明窗口，不能删掉失败/拒绝/尾部；完整批次或固定drain截止的选择在运行前冻结。相同ID同内容重投只计一次，冲突或一请求多终态ID拒绝。缺完整client清单不能外推吞吐；字段缺失用null/覆盖率表示。不同invocation_binding单列revision_groups供追溯，跨修订汇总仅描述整个输入批次，不能拿它做同配置A/B。

有效吞吐以成功、可见TTFT/E2E、质量有结论且TPOT可判定为前提；N=1时TPOT不适用，N=0/计数缺失不能伪造判定。批准SLO缺失则count/rps=null。真实0计入known样本，全部未知时known_sum与Token吞吐为null，known子集合计同时报missing_admitted；held仅诊断列出，金额按币种/冻结价表分组不混加。嵌套stage只保留各段inclusive分布，不输出相加的“总开销”或p95相减残差。样本少于200的分位数标descriptive_only。

## 11. C01 有界修订与验收引用（2026-11-04）

完整判定以[验收契约v0.3](acceptance-v0.3.md)为准（来源附件01a1a67f-36a7-70d6-9529-76594d820a66）。本次只修复共同客户端时间窗C01；保留v0.2指标公式和v3/3.0/1.0协议，不修改共享ObservationEnvelope、预算/slot/结算或真实采集。

输入的window.start_ms/end_ms只有在完整发送清单全部使用同一可解释client clock_scope时才可计算批次吞吐。工具保留request↔自身client observation匹配校验，并新增跨request的scope一致性检查，覆盖成功、失败、拒绝及pending；混杂即拒绝整个输入，CLI退出2，无新报告，已有报告不覆盖。工具不执行时钟归一化，也不声称相同标签证明实际同步。

server/engine各自scope不加入上述客户端集合：服务端首片/分段duration保留各自口径，引擎token时刻只在自身scope内算差值。改变引擎时间原点不能改变TPOT；不同scope不得与客户端直接相减。多发生器共同run clock、映射/不确定度/有效区间须另行审定。

验证要求：Mika原反例由接受变为拒绝；单一客户端scope及服务端/引擎独立scope保持合法；混合scope的CLI退出2且不输出共同RPS、不泄漏输入。具体新回归及实际结果见c01-regression.md。旧41项测试通过只保留为既有用例事实，不能追溯地证明C01已通过；本次离线回归也不代表C02–C08真实运行验收。

C04探索与确认区分：原3次配对作为探索；确认收益至少5次配对、首批4格×2变体×5×200=8000测量请求、1280万输入/179.2万输出cap及C07收益阈值仍属待评审建议。批准SLO/资源/额度未具备时不执行、不判收益通过，计划execution_enabled=false保持不变。
