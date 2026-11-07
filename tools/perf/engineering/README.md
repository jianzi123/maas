# CPU 工程实验

八类有界实验与[工程实现卷](../../../docs/performance/engineering/README.md)逐项对应。实现用于学习数值、地址、资源不变量、调度、恢复和统计；没有GPU/模型/集群执行路径。

## 异步运行时接续

原八类算法报告保持原入口。新增闭环独立运行，仅依赖Python标准库：

~~~text
python tools/perf/engineering/runtime_lab.py --output tools/perf/reports/my-runtime.json
python -m unittest discover -s tools/perf/engineering -p "test_runtime.py" -v
~~~

实现为runtime_core.py、runtime_worker.py，复用Scheduler.preview和PagePool；固定七个场景由runtime_lab.py执行。新报告cpu-runtime-integration-1.0有明确synthetic/CPU范围，不能直接输入analyze.py或作为业务终态。原理、停止与资源边界见[第13章](../../../docs/performance/engineering/13-runtime-loop.md)。

## 运行

需要已有Python3.11+、NumPy2.3.5，沿用[依赖锁定文件](../operators/requirements-cpu.txt)。从仓库根目录：

~~~text
python tools/perf/engineering/run.py --output tools/perf/reports/my-engineering-run.json
python -m unittest discover -s tools/perf/engineering -p "test_*.py" -v
~~~

用普通Python模式运行，runner拒绝-O以保留内部不变量检查。选择未存在的输出文件。可用--lab attention选择单项，其他值为layout、transforms、kv、scheduler、distributed、statistics、durable。默认all运行八类。数值验证通过才发布结果；使用临时文件加不替换hard link，本地文件系统需支持该操作，失败不覆盖原报告。

## 实现与关键反例

| 文件 | 实际实现 | 验证重点 |
|---|---|---|
| attention_lab.py | dense/online softmax、GQA、suffix mask、分页gather | 空/全遮罩、非整块、极大score、明确头映射与finite |
| layout_lab.py | CPU tiled GEMM、sector/bank集合、寄存器上界 | strided/tail/零K、广播例外、虚构硬件参数边界 |
| transforms_lab.py | RoPE、residual/RMSNorm、groupwise W8 | 两输出、逆旋转、尾组、scale范围、误差三角上界 |
| kv_lab.py | generation lease、owner、COW、batch pin/complete | ABA、OOM不破坏原状态、提交原子性、六种回收交错 |
| scheduler_lab.py | 保守KV预留、chunked prefill、轮转decode、取消 | 半完成死锁反例、容量峰值、首输出与有限负载完成 |
| distributed_lab.py | TP行列并行、MoE dispatch/combine、投机概率质量 | 完整归约、逆路由、overflow拒绝、q=0与相同分布 |
| durable_lab.py | 两份SQLite、固定子进程真实退出/恢复 | 91/92/93三个截点、同命令/异payload、foreign资源、owner失效 |
| statistics_lab.py | run级配对bootstrap、右删失KM | estimand、risk set、tie、不可达p95和假设限制 |

durable使用独立本地SQLite文件模拟journal与外部资源服务。它不替换项目Go/MySQL；fake资源服务的幂等不能推导为供应商生成重试语义。子进程仅运行本文件，父进程前台收集退出与恢复结果，无长期服务。

正式实验输出保留crash-lab目录；单元测试只清理自己生成、且已核验位于工程测试目录内的临时子目录。

## 报告边界

schema_version=cpu-engineering-1.0，synthetic_inputs=true、gpu_executed=false、model_executed=false。该报告是本工具独立格式，不是ObservationEnvelope、业务终态或analyze.py输入。authority声明没有准入、结算、退款或关闭证明能力。

normal GPU timing、真实多卡通信、模型质量、停止证据和生产发布另行验证。已有GPU/模型plan的执行开关、共享协议、Go/MySQL/Higress职责均保持原样。
