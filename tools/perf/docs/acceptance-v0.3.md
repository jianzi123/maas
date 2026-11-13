# MAAS-10 可核验交付与验收契约 v0.3（修订草案）

本稿针对成员指出的“交付条件空泛”补充技术判定。它规定要交什么、怎么复算、何时失败；不代表已运行或批准 GPU/模型调用。硬性计算/一致性要求用于本轮修订；下文性能收益政策是待评审建议，不冒充成员已确认的业务 SLO。

## 1. 当前结论与本轮必须修复项

已交付提交：86f5408e100de6c276a2af543051098c3d4d5669，仅 tools/perf。Mika 上轮独立复跑 41 项既有测试通过，但这些用例没有覆盖跨客户端共同时间窗。

本轮对原 synthetic 夹具作一个修改：只把第一个 request 及其 client observation 的 clock_scope 同时改成 other-client-monotonic。工具仍接受9个sent并输出4.0 success_rps。这个数字是原夹具的人造运算值，不是性能；缺口是聚合前未证明各客户端时间坐标可比。复现脚本见同附 MAAS-10-clock-scope-reproducer.py。

C01 修复验收：
- 未归一化输入的所有客户端记录必须使用同一个可解释 clock_scope，才能共享 window.start_ms/end_ms 计算批次吞吐；作用域混杂必须拒绝，CLI退出2且不产生新报告。不能只比较 request 与它自己的 observation。
- 本轮最小实现采用拒绝混杂作用域；无需开发分布式时钟服务或修改共享ObservationEnvelope。单一作用域标签也不证明实际时钟同步，导入器须对来源负责。
- 测试至少覆盖：单scope成功；混合scope拒绝；同一request/observation错配拒绝；server/engine独立scope仍可在自身坐标内计算时长；CLI拒绝且敏感输入不回显。
- 未来若支持多发生器，另定义共同run clock、每发生器的映射/不确定度/有效区间及校验。NTP墙钟相近不足以直接相减各进程monotonic时钟。本轮不自动扩展该能力。

因此“41测试通过”保留为事实，不能继续据此宣称共同时间窗验收通过。当前阶段待C01修复和复验后再提交in_review。

## 2. 指标必须有逐请求可复算定义（C02）

每个run交完整发送清单；以request_id去重，同ID同内容重投只计一次，冲突直接拒绝。每项同时给eligible/count/missing及覆盖率，不能只交p95。

| 指标 | 输入与公式 | 判为不可获取/失败的条件 |
|---|---|---|
| 可见TTFT | 客户端同一monotonic坐标中，首个非空content事件收齐时刻减实际sent时刻；另报计划发出到首内容 | role/空delta/心跳/usage-only不算；无内容为null |
| 服务端首内容 | 原终态first_chunk_ms及其原Go口径单列 | 不重命名为客户端TTFT，不把二者相减当网络p95 |
| 可见TPOT代理 | 完整可见输出经冻结tokenizer计数N，(last_content-first_content)/(N-1) | N<=1为null；N=1时TPOT SLO不适用；chunk数不代替N；缺分词器摘要不能算 |
| 引擎TPOT/ITL | 引擎本机逐生成token时间戳，在其自身scope内计算；与可见输出分开 | 只有SSE片段间隔时只能叫chunk-gap，不报真实ITL |
| 成功E2E | 客户端合法成功终止时刻减sent时刻 | HTTP200+流内error/raw EOF/缺DONE非成功；取消/失败分别报termination，不混入成功E2E |
| 成功吞吐 | succeeded/T；T为批准共同观察窗，包含尾部或预先冻结的drain截止 | 不同未归一化客户端时钟拒绝；不能删失败、拒绝或窗外尾部后重算更短T |
| Token吞吐 | 已知实际input/output分别求和除T，同时报known/admitted覆盖率 | 全未知为null；真实0保留0；cache/reasoning子集不重复加总；reserved/held不算actual |
| 有效吞吐G | 同时成功、质量通过、TTFT/E2E及适用TPOT达标的请求数/T | 任一必要SLO/质量/可见计数未知则不能判定，必须报eligible/sent；不得把拒绝当有效完成 |
| 分位数 | 固定线性插值index=(n-1)q；分开all-sent观测分布和success分布 | n<200只作描述；p99至少1000有效样本才展示，仍不声称精度保证 |

离线固定向量须能复算：9 sent=8 admitted+1 rejected；8 admitted=4 succeeded+2 failed+1 cancelled+1 pending。首条可见TTFT=100ms、服务端首片=60ms、TPOT代理=80/3ms；known total=41，unknown token held=420不能并入41。计数/整数金额精确相等；浮点公式用明确容差（建议绝对1e-9，仅计算器测试，不是采集时钟精度）。不能靠重新生成expected文件自行证明正确。

## 3. 每一次运行都要冻结身份与资源（C03）

交 resolved-plan.json + SHA256、versions.json、rank-map.json、fixture-manifest.json；字段至少包含：
- model/source及协议；CR UID/generation、release_revision、publication_id、activation_epoch、route_binding_sha256和价格修订；desired/observed/active分开。
- 权重、tokenizer、chat-template摘要；engine image digest、commit、实际启动参数/有效配置hash，不能只记镜像tag或CR desired。
- GPU SKU/每卡显存/数量、节点/rank到GPU映射、互联；CPU/NUMA、驱动/CUDA/PyTorch/attention backend、Go/Higress/MySQL/Redis/LWS版本。
- precision、上下文、TP/PP/DP/EP实际布局；采样/预热/种子/请求序列hash；预算/slot/限流/SLO及停止配置。

每个已准入request都可关联完整InvocationBinding及其实际runtime/gateway观测；不适用字段显式not_applicable，未知为null。改变资源/精度/输出长度/预算规则必须新建run；增加GPU后的收益不能叫同资源优化。

票据v3、终态3.0、ObservationEnvelope1.0严格分流；观测不成为授权、结算、退款或传输关闭证明。工具只检查导入元数据，不声称验证JWS或真实MySQL账本。

## 4. 基线负载和数量可提前算出（C04）

首批候选条件沿用现有方法，执行仍须批准：
- S=256输入/128输出cap，M=2048/256，L=8192/512；token数包含实际chat template，保留EOS实际长度，不强制生成垃圾凑cap。
- 完整矩阵：3长度×C={1,2,4,8}×U/H=24格。U仅模板外无共享前缀；H约75%共享前缀且预热，保存实际共享token数和命中率。
- 首批只选S/C1/U、M/C1/U、M/C4/U、M/C4/H。平台不准C4则该格不执行，不提高slot/限流绕过业务规则。
- 方法v0.2的3次配对可作探索；用于确认收益，本稿建议至少5次独立配对重复，AB/BA顺序提前固定。每格/变体/重复目标200 sent，单次发压180秒上限；达到额度/时间先停，样本不足不能自动追加请求。
- 按4格×2变体×5重复×200，测量目标8000 sent。仅按候选长度上界计，输入12,800,000 token、输出cap1,792,000 token；另加预热、冷启探测、失败/取消及profile调用。此算式不是调用授权。
- 金额预估逐请求按可信预留上界及最坏适用价表计算并按规则舍入；不能预支EOS缩短或缓存折扣。tokens按计费类互斥分组，避免reasoning/cache再加一次。
- 预热、冷启和profile另列run，不混入稳态主结果；共同T/停止/drain规则对A/B相同。开环λ须等SLO合格基线后冻结，不先虚构容量。

## 5. 正确性与容量恢复采用零容忍否决（C05）

每个负向子场景候选10次，资源/故障注入须获准；任何一次违反不变量即本轮不通过，不取平均掩盖：
1. 请求/Token/金额分别耗尽：无新上游attempt、无新业务预留/slot；拒绝与速率/并发/NOWAIT原因分开。
2. 两Go副本争最后预算和最后slot：提交不超上界，一个request至多一个终态；Redis许可不是第二账本。
3. 三种取消点（首内容前、后、usage前）：分别记录cancel→Go感知、可信传输关闭、engine abort、slot释放。传输关闭不等于供应商停止计算。
4. raw EOF、流内error、usage全缺/部分缺/真实0、ACK未知：失败不计成功；null不改0，未知维度保留held，不能重放生成。
5. 同hash终态重投幂等；冲突hash/一request多个终态身份拒绝。slot回收只动容量及释放审计，不能再结算/退款。
6. 带在途流更新/回滚：老请求保留原绑定/价表，新请求只用一致Ready的新publication/epoch；删除先关准入再排空，不误删其他模型共享条目。

证据必须是脱敏request/terminal/ledger导出、可信receipt/关闭引用、allocation fence和释放审计，而非截图或trace空白。对每维核验：
reserved + overrun = known_used + unknown_held + released。
对准入集合核验：
admitted = 五类终态之和 + pending/recovery。
终态、释放、原窗口/币种及价表逐项核对。fake-client/envtest只证明其覆盖的受控逻辑，不能签发生产Ready或代替真实账本并发验收。

## 6. 瓶颈与参数优化必须有对应证据（C06）

| 怀疑瓶颈 | 必交证据 | 可试的单因素 | 否决条件 |
|---|---|---|---|
| 平台准入热点 | Redis池/RTT、MySQL池/锁/NOWAIT/commit、Go ext-auth分段和调用树 | 对应实现方在不改账本语义下改池/锁竞争 | 只提高限额/减少结算获得吞吐 |
| 引擎排队/调度 | enqueue→schedule、队列深度、batch分布、CPU/GPU时间线 | 固定GPU/slot的batch或调度参数 | 未记录offered/sent差，发生器先饱和 |
| prefill干扰decode | 长短混合下prefill/decode时段、TTFT/TPOT尾延迟和峰值显存 | 目标版本实际支持的prefill分块档位 | 截短输入或把质量退化当收益 |
| KV/前缀缓存压力 | 每卡KV容量/逐出/重算、U/H命中、显存峰值与OOM | 缓存开关或容量，分别单因素 | 只测热前缀、隐藏冷启动或OOM |
| GPU launch/通信 | 对应rank的CPU launch gap、CUDA/通信时间线、实际拓扑 | graph覆盖/并行布局/backend | 缺profile就改kernel；换硬件冒充参数收益 |

先低开销指标定位，再批准小窗口profile（候选10请求或5秒上限）；profile开启的run不当主吞吐结果。所有rank可追溯，工具/采样/丢样明确。nested span不能直接相加，p95不能相减推出另一个p95，无法归因的残差保留未知。

## 7. “有收益”的通过与不通过（C07，收益政策建议待评审）

在运行前固定主指标、适用格及质量门槛，禁止跑完后选最有利指标。
- 吞吐目标：主指标为SLO/质量合格有效吞吐G。建议通过条件为相同批准负载集合G点估计至少+10%，且重复run配对差异的95%区间下界>0。
- 延迟目标：建议固定某个关键分位数至少降低10%，且同一资源/负载下G不下降；不能改成只比较成功最快子集。
- 统计单位是独立配对run，不能把同一批相关请求伪装成大量独立实验。提交每对结果、估计方法/假设/脚本与区间；少量重复或明显漂移不能给可靠显著性结论，降级为探索。
- 每格报完整样本、错误/拒绝、OOM、质量与账本结果；重要场景不能只因汇总提高就隐去退化。质量集/seed/评分器固定，允许退化容差须事先获准；没有容差不能事后自定。
- 绝对SLO由目标模型、GPU和使用场景定：S_ttft、S_tpot、S_e2e、最小G及适用条件。任何必需字段为空只能交描述基线，不能出具SLO达标或优化通过结论。当前没有可据以承诺绝对毫秒值的模型/GPU输入。

收益为零、区间跨0、质量退化或触犯C05，结论都应如实写“未证实/不通过”，不能把交过优化建议等同A34完成。

## 8. 运行停止与最终交付物（C08）

一例越权、重复attempt、绑定/价表错配、重复结算、超预算、秘密泄漏，立即停止整个实验的新请求；一次OOM/Xid/OOMKill停止当前格且不升级负载。达到请求/Token/金额/GPU时长/墙钟上限或下一请求最坏预留不足即停发。其他资源/错误率/SLO阈值须在resolved-plan中有值；null不是无限。

停发后按原请求deadline/取消契约drain；截止时仍pending/隔离slot/held必须清楚列账，不能为收尾擅删finalizer或用TTL退款。任何未完成恢复均标失败/阻塞项。

交付包至少包含：
- manifest.json：commit、全部输入/输出hash、协议版本、synthetic/controlled/real证据级别。
- resolved-plan.json、versions.json、rank-map.json、fixture-manifest.json。
- requests.jsonl、observations.jsonl、terminals.jsonl、ledger-reconciliation.json；使用脱敏导出，不能附密钥或常规日志正文。
- per-cell-results.csv、summary.json、资源时间序列、profile索引、quality-regression.json、cancel-and-reclaim.json、cleanup.json。
- reproduce.md：固定命令、环境依赖、采集/分析/对账步骤；PR或可审commit、未执行项与限制。

离线工具阶段只需合成样本、对应报告与真实本地测试；不要求伪造上述真实运行证据。当前仓库缺独立整合base是PR交付限制，须单列，不能通过创建占位base或用41个离线测试替代合入/性能验收。

责任：性能专家负责C01修复、指标/分析与A/B证据；后端/网关负责可信埋点和真账内核；运维负责环境/拓扑/资源与采集；算法负责冻结模型/质量；MAAS-7负责独立正确性复验。Mika按上述具体证据交接，不再以“环境齐备”一句概括通过条件。
