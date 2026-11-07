# 推理框架工程实现卷

本卷补充可运行实现、算法推导、状态不变量、源码追踪和故障实验，面向准备承担推理运行时、GPU算子或部署框架开发的成员。前置是[六章基础教材](../foundations/README.md)，但每章都指向具体代码、输入、预期与评审问题。

最新接续见[第13章：受控异步运行时](13-runtime-loop.md)，已将Scheduler、PagePool和Worker接成可运行CPU闭环，补七个故障/背压场景与38项回归；原八类算法实验接口保留。

## 章节与实现对应

| 章节 | 主要内容 | 可核查实现 |
|---|---|---|
| [1 GPU执行](01-gpu-execution.md) | warp地址、sector、bank广播/冲突、寄存器与occupancy上界 | layout_lab |
| [2 GEMM工程](02-gemm-engineering.md) | tile/尾部/stride、线程分工、准备成本与成熟baseline | tiled_gemm＋已有CUDA骨架 |
| [3 在线Attention](03-online-attention.md) | softmax状态合并推导、GQA、suffix mask、分页重组 | attention_lab |
| [4 变换与量化](04-transforms-and-quantization.md) | RoPE、残差/RMSNorm双输出、W8分组与误差上界 | transforms_lab |
| [5 KV所有权](05-kv-ownership.md) | generation、COW、OOM原子性、batch pin与回收 | kv_lab |
| [6 容量调度](06-scheduling.md) | 半完成死锁、保守预留、prefill/decode与取消 | scheduler_lab |
| [7 Graph与采样](07-graphs-and-profiling.md) | 双缓冲寿命、guard/fallback、KV预算、采样开销 | 原profile_operator dry-run |
| [8 并行与投机](08-parallel-and-speculation.md) | TP行列并行、MoE逆路由、ring成本、PD与采样概率 | distributed_lab |
| [9 耐久恢复](09-durable-release.md) | 两份SQLite、真实进程退出、原命令恢复与owner失效 | durable_lab |
| [10 测量统计](10-measurement-and-statistics.md) | run级配对、estimand、bootstrap、风险集与右删失 | statistics_lab |
| [11 源码追踪](11-sglang-source.md) | 固定SHA调度/Graph/KV/backend调用链与阅读作业 | 8份hash/AST审计 |
| [12 工程作业](12-engineering-projects.md) | 实现任务、反例、证据与评审矩阵 | 跨模块练习与阶段交付 |
| [13 异步运行时](13-runtime-loop.md) | 计划/提交/完成、输出信用、取消/代次隔离、真实CPU线程 | runtime_core/runtime_worker/runtime_lab |

## 直接运行

从仓库根目录，使用已有Python3.11+与NumPy2.3.5；依赖沿用[CPU锁定文件](../../../tools/perf/operators/requirements-cpu.txt)。不需要Torch、CUDA、模型或平台Key，也不自动安装依赖。

~~~text
python tools/perf/engineering/run.py --output tools/perf/reports/my-engineering-run.json
python -m unittest discover -s tools/perf/engineering -p "test_*.py" -v
~~~

使用新的输出文件名。统一runner执行八类固定实验，数值门禁通过后发布JSON；不覆盖旧报告。报告synthetic_inputs=true、gpu_executed=false、model_executed=false，并保留独立SQLite崩溃目录。源码与测试集中在[工程实验目录](../../../tools/perf/engineering/README.md)。

需要逐项观察时用--lab attention；其余可选值为layout、transforms、kv、scheduler、distributed、statistics、durable。代码不建立HTTP服务、不访问集群、不调用供应商；durable子进程仅执行同一固定实验脚本。三次退出码91/92/93是故障注入的预期值，父runner须完成恢复并通过检查。

## 本卷结论的范围

CPU实验验证数学、地址模型、状态与具体本地恢复路径；GPU sector、性能、真实停止、跨rank通信和模型质量依然要在目标环境验证。已有GPU/模型计划保持关闭。Go/MySQL唯一业务真源、Higress固定来源、unknown/held和slot分离继续沿原契约。

真实系统优先复用成熟执行后端和已交付内核，按[整合地图](../integration-map.md)接线。新kernel、PD/EP策略或部署范围变更交ADR与原负责人评审。本卷的实验数据库与教学状态接口不作为生产替代品。
