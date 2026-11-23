# v0.25：代表性为何失败，下一方法究竟能回答什么

本轮只读固定交付dbb062606a2ce4ebfdd7218b17151f071ea043b4下的v0.24原件。GPU执行、补采和模型调用均为0；没有新主比较计划或执行入口。旧qualified=false、34/64（query2/32、idle32/32）、Full严格0/18、bank和原阈值保持。协调者已核完整性，旧P2的独立QA签收也保留原范围，不能用来证明本模板合格。

## 从总数转到可核对的时间记账

用同一进程monotonic时钟定义：D是前块完成观察，P0是prepare开始，P1是prepare结束，Q0/Q1是外部query调用开始/结束，S是本块提交。query行满足：

~~~text
G = S − D
  = (P0 − D) + (P1 − P0) + (Q0 − P1) + (Q1 − Q0) + (S − Q1)
  = prefix     + prepare   + pre_query + query       + post_query
~~~

prefix内部再分成前块bookkeeping、真实ledger追加/flush/fsync、未细分的剩余前缀。三者不重叠；IO和bookkeeping已经在prefix里，不能加第二次。每一行以整数ns核恒等式，分组均值以有理数核恒等式；**median差不能这样相加**。没有query的idle行保留真实wait区间，query计时为不执行该操作的0，遥测状态则为缺失，不能填0。启动根节点的bookkeeping没有观测，明确标为unobserved，而不是宣称测得0。

新只读入口audit_reference_representativeness.py读取全部36项清单、128行/80query/56边界观察，逐条核hash、时钟、前后继、嵌套、分母，再输出rows.csv和audit.json。[完整16层分解表](../../../tools/perf/operators/local_gpu/evidence/reference-audit-v0.25/final/tables.md)含每层3个reference与2个query holdout的均值差；32个idle holdout和16过渡也全在逐行输出中。

## 真正新增的三个观察

全16层等权时，query holdout的平均gap为259.154053ms，参考为286.498245ms，变化−27.344192ms。其中prefix−22.280768ms（真实IO−13.917778ms、剩余前缀−8.409438ms、bookkeeping+0.046448ms），prepare−0.276560ms，query−4.788939ms，query前后+0.002075ms。这只是记账，不是“query只影响4.8ms”的因果结论。

| 分层 | Δgap ms | Δprefix ms | Δprepare ms | Δquery ms | 说明 |
|---|---:|---:|---:|---:|---|
| full/B3/native/边界 | −354.138 | −203.398 | −7.095 | −143.645 | IO与未细分前缀同时大幅变化 |
| full/B8/mature/内部 | +285.101 | −0.033 | +0.075 | +285.058 | 几乎全部变化落在query区间 |
| bare/B3/mature/边界 | +183.803 | +4.334 | +6.481 | +172.988 | 与full同类角色的方向也不一致 |

Δ均为query holdout−reference。四舍五入仅用于展示，末尾细小的query前后区间也在原表中。正负大幅抵消使全局平均看起来接近，不能因此选一层当全局原因。[全部分层图](../../../tools/perf/operators/local_gpu/evidence/reference-audit-v0.25/component-deltas.png)不筛掉任何层。

第二，源码“同一函数”不等于运行链状态一致。固定[边界入口](../../../tools/perf/operators/local_gpu/bench_cadence_reference.py)在边界IO后显式导入host_state；首个参考边界可能承担首次模块路径，后续走缓存。该行未细分prefix达到352.938411ms；原件没有导入前sys.modules或导入独立计时，**不能把352.9ms直接叫导入耗时**。剩余区间还含资源查询、主机观察、解释器和调度等待。文件追加位置、缓存和fsync路径也不同：全部实际边界IO为7.898189–262.318066ms，不能用空函数/不落盘的校准替换它们。

[prepare](../../../tools/perf/operators/local_gpu/reference_runtime.py)实际执行replay_prepare、cuda.synchronize和图身份检查。参考prepare均值3.383482ms、范围1.450659–22.706148ms；query holdout均值3.106922ms、范围1.271775–14.645920ms。它含H2D/metadata准备与同步等待，不能自动归为纯CPU成本，更不能从一次prepare变慢推断某个kernel瓶颈。

第三，[telemetry](../../../tools/perf/operators/local_gpu/run_decode.py)是每次启动外部nvidia-smi并等待返回，不是单独NVML函数的设备计时。80次调用为84.547209–852.390857ms；没有分开spawn、driver、格式化和读取。query组有80个遥测点，idle与过渡均没有该遥测；缺失取决于策略，无法拿query组的频率去给idle组补值。已有点的SM时钟为270–1980MHz，其中66/80为1980MHz；边界loadavg为34.005859–58.991211。它们说明记录并非处处相同，但没有饱和阈值、其他任务身份、连续驱动/频率轨迹，不能确认CPU饱和、降频或驱动是设备漂移原因。CSV墙钟与monotonic/设备时钟没有校准，不直接相减。

## 现有设计能识别什么，不能识别什么

可复算的是：这个进程里哪些**被记录的主机区间**变化、旧匹配为何失败、实际出现的事件区间和完整失败分母。它不能识别“单独执行query”或“单独physical idle”对GPU的因果效应。

- 全部参考先运行，holdout后运行，phase与时间顺序完全绑定；这叫未用于拟合的时间holdout，不等于独立IID样本。
- query/idle位置预先固定，前序策略和carryover不同。N/M首位虽平衡，也不会自动平衡驱动、cache、温度或操作系统负载。
- idle会主动等到先验deadline，32/32命中是控制器行为的核验，不是query分布代表性的独立证据。
- CUDA event包住10次提交，得到的是stream区间；可能包含队列暂空和提交停顿，不是所有kernel执行时长之和。host enqueue、event elapsed和host wall并行/嵌套，不能相加。
- full与bare_graph是不同scope，B3还pad到cap4；不能将某一scope的条件结果外推Engine、serving、模型质量或TTFT/TPOT。

本轮没有构造n=3/2的“显著性”结论、bootstrap置信区间或收益排名。序列依赖和样本量不足时，一个好看的CI不能补上不可识别的机制。

## 判定：当前固定bank方法在该窗口不适用

16层的参考跨度都超过各自完整容差带宽，30条超差仍有11高/19低。更强的算术反例是：现有80个query链中有**5条gap超过525ms**。原允许target≤500ms、容差max(250us,5%)，所以任何合法固定target的最大接受上界都不超过525ms。保持这些实测链不变时，即使事后选target，也不能让这5条通过。具体ID全部保存在audit.json。

这不是对新干预后行为的模拟：加等待、改采集器或改变环境都可能影响后续链。但它足以否定“仅把旧共同target抬高/重算就能修好本窗口”的建议。不得把上限改成1秒、筛掉慢样本或重新跑到匹配。当前同步CLI query↔固定median sleep作为严格全匹配的因果工具，在该窗口不适用；原bank不修补。

## 新的采前设计 P25-AA：先检验无热查询的测量稳定性

**这是待评审的资格设计，不是本轮批准的GPU运行，也不是N/M主比较计划。没有生成runner、可执行schedule或GPU命令。** 原GPU许可有效，只是本次交接限定离线。该设计不声称修复旧query模板，而是明确换一个可识别问题：在固定、无热段query的SGLang静态调用协议下，同一实现的两个别名是否可稳定测得相同stream成本。

A与A′必须指向**同一实际graph/实现**；对native和mature分别做自身A/A，不把N/M差异当A/A零假设。后续只有成熟实现之间的独立单因素比较才回答KV工程收益，这份设计不预生成那项比较。

### 1. 要估计的量与仍存在的混杂

主量为每块10次固定调用的CUDA stream-event区间，分full/bare、B3/B8、实现与边界/内部角色报告。A/A别名的调度和数据路径必须相同，预期差异为0；本阶段只检验测量协议和环境能否分辨这个零差异。host wall、enqueue、gap、prefix都保留为辅助量，仍不叫纯kernel时间或physical idle。

移除热段外部query是新协议的定义，不能从中推断原query的单独作用。缓存、频率、前序操作与主机提交仍可能影响stream时间；随机/平衡别名标签只能防止标签与顺序的系统绑定，不会把所有状态变成已观测。需要真正kernel归因时，另批在同条件下采独立Profiler trace；不能让Profiler常驻本资格热段。

### 2. 参考策略和测量链

第一次显式模块导入、格式化器/事件对象建立、目录/ledger首次触达在初始化阶段记录，不能藏起来；随后参考与holdout使用同样的已声明稳态链。原始启动/捕获/预热开销单列，不算成测得的稳态改善。真实bookkeeping、边界ledger追加/flush/fsync仍计时，残余prefix的资源查询/host观察再拆细，禁止把残余直接命名为驱动或调度。

热段不启动nvidia-smi、NVML轮询线程或后台采集服务；设备清单/资源门槛在预登记边界观察，其干扰在两阶段对称保留。这样也意味着热段设备状态不连续可见，报告必须保留这个缺口。无query并不保证稳定。

参考共用每个(scope,B,实现,角色)先验stream-event中位数。不能按A/A′分别拟合；全部参考行、未匹配与准备开销冻结保存。已批准旧logits/KV finite/完整角色/bitwise门禁继续使用，不重新请求旧QA签收。

### 3. 冻结身份、分母与独立holdout（评审建议值）

| 项目 | 拟采前固定内容 |
|---|---|
| 16分层 | full/bare × B3/B8 × native/mature × boundary/interior |
| reference进程 | 每层3块＝48＋8过渡＝56块；冻结全部参考后才开始另一进程 |
| holdout进程 | 每层4块＝64＋8过渡＝72块；每层A/A′各2，不用它们调整先验 |
| 完整资格分母 | 128块/1280计时调用；参考48、holdout64、过渡16，不按结果增删 |
| 额外调用 | 预热、prefill、门禁、内部capture另列，全部消耗同一总预算；内部capture调用量未知则标未知 |
| 新AA端点容差 | 建议max(250us,5%×先验stream块时长)，64/64完整且命中才过工程小窗门槛 |
| 原host-gap规则 | 原max(250us,5%)和500ms上限不改；新AA通过也不能宣布旧query模板通过或host等价 |
| 版本/源 | 原固定SGLang0.5.2/b0d25e7、Torch2.8+cu128、cap8、同参数/输入/实际backend、source/manifest/hash |
| 进程与时钟 | reference与holdout全新独立进程，同资源串行；跨进程只比duration，不合并monotonic坐标 |
| 资源与硬截止 | 原GPU0/research锁、allocator/planner0.20、req8/KV512/context128、≥1GiB；两个进程共享总600s，内部540s退出，不是各600s |

这里复用数值形式是**新端点的待评审容差**，不是给旧host-gap规则重新解释、放宽或批准产品SLO。其适合性要在采前确认，不能看过新holdout再改。A/A小窗64命中也不是统计等价证明、跨环境稳定性或性能收益。绝对SLO/质量目标仍按真实模型和硬件另定。

先冻结协议、来源、参数/输入摘要、两进程及别名轮转身份、全部分母、时间窗与失败条件；reference完成后再冻结新先验hash，然后独立holdout。旧v0.24文件始终只读。两进程的参数数值hash应一致；地址/graph对象ID只要求各进程内稳定，**不能要求跨进程地址相同**。实际backend、图cap、padding、KV写槽和完整logits/KV都要有证据，metadata标签本身不证明caller命中。

本设计只有资格规模和角色规则，没有生成下一项N/M优化比较的运行身份/次序或可执行计划。正式实现/采样需下一次明确交接，先审方法是否回答了真正的问题。

### 4. 否证、缺失与停止

锁忙、资源不足、源码/参数/输入身份不符、别名实际走不同graph、任何finite/完整状态失败、跨clock错误、phase重置前后继、deadline到达，立即停止并保存所有计划缺失身份。预算不足不能把128分母缩小，也不能增第三进程补齐。全部慢态/超差保留。

64条holdout任一缺测、无效或不满足冻结AA门槛，即拒绝该无热查询测量方法在本环境中用于后续收益判断；不重试到好、不放宽容差。如果A/A仍不稳定，下一步先定位提交/队列/主机调度的真实trace，或承认当前环境不能分辨目标效应。不能转头用kernel数量或教学原型单次快态宣布收益。

若目标改为“把遥测移到边界以后，总调用协议开销变多少”，可以另行设计有随机分配的完整策略比较。那个效应包括query、等待、prepare、carryover的总变化，不需要假装单独识别query；它是另一估计量，必须另批冻结完整分母、模型/质量/SLO及失败口径。本稿不生成该主比较，也不将本128行回填成其证据。

## 复现、交付与后续排序

仓库根目录下，完全离线运行：

~~~bash
python tools/perf/operators/local_gpu/audit_reference_representativeness.py --root tools/perf/operators/local_gpu/evidence/reference-v0.24 --output /path/to/new-audit
python -m unittest discover -s tools/perf/operators/local_gpu -p 'test_representativeness_audit.py' -v
~~~

新输出目录必须不存在。11项新回归覆盖嵌套重复计数、前后继、clock、query/IO缺失、idle与启动未知以及全部真实128行；没有重跑旧36项或QA16/32。开发期CSV辅助导入缺失由真实数据回归发现并修复，最终日志为11/11；没有拿初始失败当通过。

材料映射继续沿[B03归因](notes/B03-principles.md)和[B06 Graph生命周期](notes/B06-cuda-graphs.md)：原生图重放减少launch并不自动消除host观测干扰，固定地址/池生命周期也不是进程间数值成本稳定性的证据。本轮没有新增原文搜索或论文复现。

下一顺序是：先评审是否接受P25-AA这个新问题和门槛，再实现测量链细分与别名零差异资格；通过后另批形成成熟KV单因素比较，失败则交环境分辨能力未知/不适用。E-LIT-02/03、stage2可读分段、同次同层同槽写入证明后save=False、cap8及MAAS-15原验收边界均保持。本轮不修改产品后端、部署包或共享契约，也不把人工权重调用作预训练质量、Engine/serving证明。
