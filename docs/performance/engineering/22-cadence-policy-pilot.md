# 22｜E-LIT-01真实三策略入口与冻结首批

本章接续[第21章](21-literature-to-experiments.md)的E-LIT-01，仅实现查询/空闲策略。E-LIT-02/03与原0.21设计快照不改，旧bench_kv_interleaved默认行为和原始样本不变。

## 实现与预登记分母

新增cadence_protocol.py生成/校验不可变计划；bench_kv_cadence.py执行；analyze_kv_cadence.py按计划复算。CLI --help/--validate-only无需导入GPU框架。计划含实际源码hash，错误配置/身份/源码在GPU导入前拒绝。

首批两独立进程R01/R02，固定native先捕获；策略按三轮Latin轮转及反向次序，N/M配对顺序同样预登记。每cluster是**总共10块**，N/M各5块，每块10调用，共100调用（每变体50）。Full为主scope：主指标是完整cluster的wall纳秒/100个计划调用，包含策略和准备，从首块prepare之前到末块完成；不含cluster边界归档I/O。Bare_graph单列诊断，不能与full合并。

矩阵B3/5/8，prefill12后KV上下文长度13，静态重复不推进生成token。每scope/每进程27cluster；两scope×两进程共108cluster、1080块、10800调用/重放，其中full540块、bare540块。块有相关性，不当总体显著性样本数。

## 三水平及匹配定义

- query_block：每块前调用既有telemetry。
- query_cluster：仅cluster首块前查询；其余块不查询、不额外sleep。
- idle_matched：不查询，等待至“上一完成host观测时间＋采前冻结目标gap”的deadline。只sleep一次，不忙等、不重试追赶快样本。

采前用B3/full准备模板，对N/M各校准10次真实查询，保存全部20次。目标为各变体完成→提交代理gap的中位数；最大允许500ms，超限不进入主采集。Runtime manifest在任何比较块前冻结目标、校准hash、模型完整参数hash、图/指针、版本及clock_scope。每cell在其首块前冻结实际input hash，不采完重定配对。

每块保存query开始/结束、上一完成/ready/submit/enqueue/done、准备前缀、ready→submit、请求/实际sleep、目标gap、绝对/相对误差。匹配阈值预定max(0.25ms,5%目标gap)，超差块保留并降级归因资格，不过滤后宣布收益。该gap为host观测的自身device完成到下一提交，不是物理GPU idle计数；准备kernel/CPU记录和未观察的其他活动仍可能影响它。

三水平比较复合策略效果，不自动分解出查询或idle根因。主cluster wall与按变体的块event/host/wait分别报告；CUDA事件可含host/driver间隙。Cluster边界I/O被下一块的实际gap记入，不隐藏其扰动。

## 门禁与异常

复用已验原生dummy ModelRunner、独立backend/图pool，默认cap8。完整logits、全30层真实写槽在校准与cell前/后检查，快照按内容hash无损去重，校验不进入热段；参数全hash、图/指针及静态input再核一致。没有Profiler混入干净热段，本批不重跑旧DAG QA。

计划、run/replicate、scope、cluster/triplet、N/M pair、slot、clock与源码身份逐项校验。缺测仍有计划ID，超时/中断不补快块；没有结果的进程也在1080块分母。锁忙、低显存、数值/图身份、query错误和deadline即停，不产成功采集结论。内部570s保留收尾时间，外部timeout600s；一进程失败后不继续下一GPU进程。

资源沿GPU0/原research锁、allocator/planner0.20、req8/KV512/context128、运行前≥1GiB空闲，单GPU串行。人工权重静态调用/重放不代表预训练质量、TTFT/TPOT、Engine/serving或平台收益。

## 实际入口与复现

~~~powershell
# 在仓库目录，先提交代码/来源锁，再冻结计划；运行目录必须全新。
$cadenceCheckout = git rev-parse HEAD
python tools/perf/operators/local_gpu/cadence_protocol.py create --experiment elit01-pilot1-20261115 --checkout-commit $cadenceCheckout --output ../deliverables/elit01-v0.22/plan.json
python tools/perf/operators/local_gpu/bench_kv_cadence.py --plan ../deliverables/elit01-v0.22/plan.json --run-id R01 --output ../deliverables/elit01-v0.22/R01 --validate-only
~~~

GPU执行需在原获准WSL/venv。实际600s前台命令随本批command.json交付。入口为：
~~~text
bench_kv_cadence.py --plan PLAN --run-id R01 --output NEW_R01_DIR
bench_kv_cadence.py --plan PLAN --run-id R02 --output NEW_R02_DIR
analyze_kv_cadence.py --plan PLAN --root ROOT_WITH_R01_R02 --output NEW_ANALYSIS.json
~~~

## 本批结果

代码预检16项无GPU回归通过。真实首批结果在采集后填入，当前不预填根因/策略收益。旧文献卡false仍是历史设计状态，不解释为重新等待既有GPU许可。
