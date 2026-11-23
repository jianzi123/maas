# E-LIT-01 真实参考模板资格小窗（v0.24）

这是原108 cluster主实验之后的独立模板资格验证，不重写原记录。原Full严格匹配0/18、单独query/idle原因与稳定收益未知，均保留。

## 采前约束与分母

一个新GPU进程，一个轮转R01；顺序为reference → 冻结 → holdout。scope按full、bare_graph，B按3、8。B3实际padding到cap4；B8使用cap8。每个scope/B内native、mature次序按pair奇偶轮换；holdout另反转初始次序。reference六对；holdout八对，模式为query,idle,idle,query,query,idle,idle,query。每对第一块为boundary_first，第二块为interior。

16个分层 = 2 scope × 2 B × 2 variant × 2 role。每层3个query参考、2个query holdout、2个idle holdout。共48参考 + 64 holdout + 16过渡 = **128块/1280个计时调用**。每phase/scope/B的两块过渡也各运行10调用，保持独立身份和原始时点，不参加预先定义的64块资格分母。它们承接切格、gate、预热、冻结I/O；不能据此忽略异常或隐藏慢态。另有192个预热调用、32个gate forward、8次extend/prefill与框架内部捕获；不塞入1280分母。它们都占600s总墙钟预算。

## 真实执行链与共同先验目标

previous_done仅在启动事件后初始化一次；之后只更新为真实热块完成后观察到的monotonic时点。跨格、I/O、冻结、长过渡均不重置。
每块的路径为：上一热块完成 → CUDA elapsed读取/构造原始行/JSON序列化 →（对首块：真实ledger追加、flush、fsync、资源/host观察）→ replay_prepare/同步/实际图身份核验 → query或一次deadline sleep → submit → 10次原生图或完整forward → 设备完成同步 → bookkeeping。主机同步是测量边界，不修改产品热路径；本实验本身不测无同步serving。
reference与holdout使用同一入口、真实边界I/O和观察；holdout不会额外在热链中计算匹配或重新拟合。目标按每层3个reference gap中位数取得，两种holdout模式共用它。idle只睡到previous_done + prior_target；已经超时不补偿、不回退、不重试。
host completion→submit gap包含主机工作与prepare，**不是物理GPU idle**。事件计时与主机时间分别保留，Profiler不在热段运行。

## 冻结、资格及停止

采前plan冻结代码文件hash、固定官方源码锁、资源、全部128身份与原阈值。参考结束后先写原件，再冻结目标bank及reference行hash，然后才执行独立holdout。目标上限500ms；匹配容差保留max(250us,5%×target)。不得按policy后拟合，亦不回填v0.22旧目标。

合格要求：64/64计划holdout完整、同scope/process/clock、前后继连续、各自落在共同prior容差内；16份完整logits/KV门禁通过、原参数/图指针/输入保持、采集无错误。missing、慢态和超差都保留，任一项失败即不合格。合法但不匹配是负结果，不强制伪装为采集错误。独立QA签收是未来主比较的另一前置，本窗口通过本身不授权主比较。

只执行一次，GPU总墙钟600s（内部停止540s，外层timeout600s），GPU0同research锁，allocator/planner均0.20、req8/KV512/context128、至少1GiB空闲。锁忙/资源不足即记阻塞；运行错误/不合格不追加补采。禁止共享WSL重启、全局修改、新权重下载及付费调用。E-LIT-02/03不启动。

## 可复现入口

在已批准WSL和原固定venv中：

~~~bash
python reference_protocol.py --create --experiment ELIT01_REF24 --checkout <clean-execution-SHA> --plan <new-plan.json>
python bench_cadence_reference.py --plan <plan.json> --output <new-window-dir>
python analyze_cadence_reference.py --plan <plan.json> --root <window-dir> --output <new-analysis.json>
~~~

完整外层600s命令、执行SHA、UTC、退出码与总墙钟另见该次command.json。Windows下可运行 python -m unittest discover -s tools/perf/operators/local_gpu -p 'test_reference_qualification.py' -v；合成单测仅校验验收器，不是GPU证据。

## 证据边界

SGLang0.5.2固定b0d25e7、Torch2.8、现有SmolLM135M配置和DummyModelLoader人工权重，实际ModelRunner/CudaGraphRunner。每份门禁保存完整[B,49152] FP32 logits和[30,2,B,3,64] FP16 KV，并严格核双方finite/shape/hash/bitwise。这不代表预训练质量、Engine/serving或TTFT/TPOT。Ada本机结果不外推Hopper/Blackwell。既有官方文献和固定源码卡解释机制，本轮不新增泛化性能宣传。

## 本轮实采与资格结论（2026-11-23 UTC）

**采集完整，模板不合格。到此停止，未补采、未生成或执行主比较计划。**

- 执行代码提交 e816a744a61166213186bd4835296e4b24c3e4ff；独立四锁/实际执行提交 1bc758cd2fe16992f81a5194e8a32a4279227d53。
- plan语义SHA256：192d80712b2955543b0a14955d4a0858c556db7d18ded7bc5fe80e042f261e36；原文件SHA256：30aeec5b33108c775b77382caac47d1400668475bcbda83659fb5b669642f600。
- bank语义SHA256：bb86a22e693948878ef8577a034368d74675c24bb23a7024e8dcd55e4de7c9dd；原文件SHA256：0c219eaacdd64d8c706a81bc1e023882a171edca5d7606ec0e15b8615501f6dc。

- 一个前台GPU进程，357.615s外层墙钟（含WSL/解释器启动等）、336.815s采集器内部计时；正常退出0表示采集完成，不表示资格通过。
- RTX4070 Laptop / 8188MiB / CC8.9 / 36SM，驱动581.29；采前6177MiB空闲。Torch2.8.0+cu128、CUDA12.8、Triton3.4.0、sglang0.5.2/b0d25e72c401f37b55d689ddbf05b8c583afe854、sgl-kernel0.3.9.post2。
- 128/128块、1280/1280计时调用，48参考/64 holdout/16过渡，真实missing0、invalid0。80次完整query观察、全部边界I/O、bookkeeping时点、prepare和事件/主机计时均保留。内部graph capture调用量未计入1280，不声称已知其总调用数。
- 16/16 gate、64向量引用完整验证；跨参考/holdout同scope/B输入hash相同，参数和原生图身份保持。峰值Torch allocated316946432B，仅为Torch口径，不是整进程或整卡峰值。
- 作者新18项资格回归＋重跑既有36项协议/门禁回归通过。另对本次实采gate做7种损坏拒绝，均失败关闭。它们不是独立QA。

| holdout层 | 计划/测得 | 匹配 |
|---|---:|---:|
| full/B3 | 16/16 | 9 |
| full/B8 | 16/16 | 8 |
| bare_graph/B3 | 16/16 | 9 |
| bare_graph/B8 | 16/16 | 8 |
| 全部query | 32/32 | 2 |
| 全部idle | 32/32 | 32 |
| 完整资格分母 | 64/64 | **34** |

[全部holdout超差图](../../../tools/perf/operators/local_gpu/evidence/reference-v0.24/holdout-errors.png)与[完整原件目录](../../../tools/perf/operators/local_gpu/evidence/reference-v0.24/)可逐行核对。绿色带为原先冻结容差；图不删除30个超差，也不展示筛选后的收益。

### 一个可手算、可运行的真实反例

按冻结顺序取首个超差，非按最大误差挑选：ELIT01_REF24/holdout/full/B3/p0/native（interior）。它使用的三个先验参考中位数为207.192994ms，实际gap223.403356ms；误差16.210362ms，大于原容差10.3596497ms，因此不合格。原query调用自身217.717464ms；before_prepare1.175324ms、prepare4.498182ms、ready→submit217.729850ms，这些主机区间相加得到同一gap。前块bookkeeping位于before_prepare内，不能再加一次。

这说明了怎样核验时间分解，不能把该query耗时当成原6–7ms/13–15ms设备成本漂移的因果证明。CUDA事件是设备区间，host gap是主机观察区间；nvidia-smi CSV的墙钟时间原样保留，不拿它与monotonic或设备时钟直接相减。32/32 idle匹配说明该次deadline结果符合先验目标，不证明物理GPU idle等价。只有2/32 query匹配，说明当前静态参考代表性不足；不能因此放宽原容差或按策略后拟合。

仓库根目录下可完全离线复现，不触发CUDA：

~~~bash
python tools/perf/operators/local_gpu/analyze_cadence_reference.py --plan tools/perf/operators/local_gpu/evidence/reference-v0.24/plan.json --root tools/perf/operators/local_gpu/evidence/reference-v0.24/window --output /path/to/new-analysis.json
python tools/perf/operators/local_gpu/reproduce_reference_error.py --plan tools/perf/operators/local_gpu/evidence/reference-v0.24/plan.json --root tools/perf/operators/local_gpu/evidence/reference-v0.24/window --row ELIT01_REF24/holdout/full/B3/p0/native --output /path/to/new-repro.json
~~~

结果应为integrity_valid=true、qualified=false、matched_holdout=34。已保存实际命令、退出码及minimal-repro.json；输出目录/文件必须全新。18项回归中的合成输入明确标为UNIT_SYNTHETIC，不能混入这128块原件。

### 独立签收与下一研究顺序

QA于本批评论01a208a6-0531-71e4-9ff0-6d40e14aae2f独立关闭旧ELIT-QA-01/P2范围：修复实现3a2966225cd0102663687ad281a0264cb5e0822e、provider head4ab8a277efe5edb9219d83cc9aea204add36af8e；QA代码0e8ec0f2b4937801cdec8b48df06aaeece9d4df3、QA四锁39ef6d7feaee02474e88d0b5a0f0fefffc5c9380，16/16唯一用例、32次CLI，未执行GPU。这里引用其回交，不当成本作者重跑或本新模板已获独立验收。

当前最先需要解决的是**参考模板代表性**，不是据本窗口宣布模型优化瓶颈。下一批可先离线比较30个超差与全部先验参考的prepare/query/边界前缀分布，并核对初始化、进程负载和轮转时间等尚未解释的共变；若拟采用新的校准设计，必须先登记新设计并重新冻结，再另批取得资格，不能拿本holdout回填旧目标。本批没有追加GPU采样，没有自动进入该下一批。

只有模板holdout合格并保留已获门禁签收，才考虑恢复E-LIT-01主策略比较。E-LIT-02仍须保证stage2可读分段全部定义，E-LIT-03仍须同次同层同槽写入证实后才能save=False，cap8默认不改。原108cluster/1080块/10800调用、Full严格0/18和稳定收益未知均保持。

机制解释继续沿[固定版本原文与源码资料卡](README.md)和[从原文到实验](../engineering/21-literature-to-experiments.md)：CUDA Graph固定地址/生命周期，不会自动消除主机观测与I/O差异；Flash-Decoding分段和FlashInfer plan/run各有不同正确性前置。本次不新增宣传倍数、Hopper/Blackwell外推或未实测的Engine/serving结论。
