# P25-AA v0.26 采前协议（实施与一次资格窗口）

本协议独立于[v0.25离线design_only](elit01-representativeness-audit-v0.25.md)，不回写历史。Mika接受的端点仅为本窗测量重复性；不是零别名偏差、统计等价、任意KV收益可分辨、旧query资格或N/M收益。原34/64、Full严格0/18、旧bank与原host阈值保留。

## 冻结分母、顺序与别名

16层＝full/bare × B3/B8 × native/mature × boundary_first/interior。参考REF为48计入参考＋8过渡＝56块；全新HOLD为64资格＋8过渡＝72块；总128块，每块10调用，共1280计时调用。参考每层3块，HOLD每层4块；32组别名配对全部保留，缺失差/比值为null。

scope顺序full→bare，B顺序3→8；每格N/M顺序按pair奇偶、B和phase轮转，别名在同一层两对按AB/BA反转。完整128身份/alias/pair在aa_protocol生成的plan冻结，不在采后配对。capture始终native后mature，尺寸1/2/4/8；B3实际cap4，B8实际cap8，默认split cap8不改。

每个实现内A/Aprime字典条目指向同一个已绑定method对象。full直接ModelRunner.forward，bare直接该CUDAGraph.replay；标签不传给模型，不增加lambda或另一wrapper，不另捕获图。每块事件之前核实际callable/self/function、graph、执行stream、input/scratch/index指针与pool；与本进程冻结值比较。跨进程参数与输入**数值hash**一致，地址不跨进程比较。

## 真实caller和数值证据

仅在初始化capture期间临时观察MHATokenToKVPool.set_kv_buffer，记录实际capturing调用、30层和1/2/4/8尺寸及原方法source hash。native与mature来源须不同，mature为已交直接store_kv_cache绑定。观察器随后撤除，不进入热段；source hash与固定SGLang源码锁保留。

每格前后复用完整logits/KV finite/shape/hash/bitwise门禁；另保存实际可读KV上下文（含B3的padding槽0）、slot表及输入元数据hash。槽0在两阶段每格初始化时统一清零并同步，此操作位于gate/预热之前，不触及事件热段。它是本新协议显式初始条件，不重写旧实验。原生图、参数和输入值须在本进程内保持；HOLD先核REF冻结的参数/输入值，再运行资格块。

## 计时边界与额外工作

每块：真实bookkeeping→边界ledger追加/flush/fsync（第一角色）与资源观察→原replay_prepare/同步及身份核验→begin event→10次同一selected method→end event→原有完成同步→elapsed读取/记录。10次selected内无新增同步、query/NVML轮询、Profiler或研究参考。event是stream区间，host gap/prepare/enqueue/wall及IO分别保留，不叫kernel总和或physical GPU idle。

全窗另有：192次预热forward、32次门禁forward、8次extend/prefill入口、16次别名registry准备、16次可读输入快照、8次padding初始化（30层K/V共480次zero_调用，8次setup同步）。capture内部forward次数不凭猜测计入；保留caller原计数并标unknown。数据读取、finite、hash/压缩、所有启动与归档都耗同一父预算，不塞进1280调用分母。提前退出时保存实际returned计数/未知，不把计划额外调用当已完成。

## 唯一父窗口与两进程生命周期

launch_aa_window在Windows启动唯一600s墙钟，等待纯CPU supervisor ready，将WSL启动已消耗时长扣除，再发一次共享lease；额外保留1s派发安全余量。Linux supervisor独占GPU0 research锁贯穿两进程/冻结/记录，job引用同一window ID和lease hash，worker继承锁FD，必须是该父进程实际子进程。每个job不能另取600s。

REF退出并收齐后，以其16层共同stream中位数冻结bank及参数/输入hash，然后才启动全新HOLD。parent clock只用于自身生命周期/预算；每worker独立clock_scope，计时只比较duration，不合并monotonic坐标。source、plan、manifest与bank hash保留，执行、结果及事后交付SHA分列。

整窗540s停止新增工作：父进程发停止信号，worker收尾并保存所有缺失身份。10s后仍未退出则只终止该确切自有worker PID；事前取得daemon保护PID，不按进程名杀服务。600s是Windows总硬截止，包含启动、capture、预热、gate、测量、归档、分析与收尾；不是各进程600s。所有进程前台收齐。锁忙、显存不足或任何身份/数值/期限错误立即收口，不启动第三worker或补采；保持128完整计划分母。

资源沿既有授权：GPU0、allocator/planner0.20、req8/KV512/context128、cap8，两个新进程启动前均≥1GiB空闲。固定Torch2.8.0+cu128/CUDA12.8/Triton3.4/SGLang0.5.2/b0d25e7/sgl-kernel0.3.9.post2及Torch图源码hash；CUDA_VISIBLE_DEVICES不得把device0映射到其他物理GPU。只用既有config/tokenizer和DummyModelLoader人工权重，HF offline，不下载权重或修改全局环境。

## 新资格与解释边界

HOLD全部64条完整/有效且每条落在同层**共同**先验max(250us,5%×stream先验)内，且完整生命周期、caller、图/输入/参数与数值门禁通过，才通过工程小窗。失败、缺测、无效、超差全部保留，任一即拒绝。每个别名配对交Aprime−A、Aprime/A，分层交完整范围，不将其不等于0隐藏在“端点都过”后面。10ms先验的9.5/10.5ms算术用例在CPU测试中明确：都可过门槛，但差1ms、比值非1；合成夹具永不报告为真实GPU资格。

原host max(250us,5%)与500ms上限保持host含义，登记为legacy_host_gap，未与新stream目标混填。通过不证明旧query/idle根因、N/M收益或模型质量/Engine/serving/TTFT/TPOT。新runner仍需对应独立复核；旧QA16/32不重派。本批到资格结果停止，失败只交最小反例和真实trace需求，不追加Profiler或重跑到好。

## 入口与采前检查

所有GPU入口同时需要plan.execution_enabled=true、显式--execute及正确父窗口/继承锁。默认创建disabled plan。--help/--validate-only使用标准库，不导入torch/sglang/pynvml。实际Windows及WSL验证、18项新CPU检查日志随本批交付；包括别名/graph、caller、参数/输入、缺测/重复、clock、晚冻结、预算重置及解释边界。开发期代码拼接与验证夹具路径问题在采前修复，没有用失败检查启动GPU。

~~~text
aa_protocol.py --create --experiment <id> --checkout <clean-four-lock-SHA> --enable-authorized-window --plan <new-plan>
launch_aa_window.py --plan <plan> --output <new-one-shot-dir> --protected-daemon-pid <actual-pid> --execute
analyze_aa_window.py --plan <plan> --root <one-shot-dir>/window --output <new-offline-report>
~~~

实际绝对路径、命令、受保护PID、source/manifest/plan/bank和生命周期在运行产物保留。此处不提供或启动N/M主比较。v0.25仍为已完成离线设计；本协议的执行结果另册记录，不能据本协议文字当已执行。

