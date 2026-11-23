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
