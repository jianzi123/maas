# CUDA Graph 重叠执行与证据采集

运行时优化常把问题从“少做计算”变成“让CPU准备、设备执行和输出处理重叠”。这会延长中间状态和buffer寿命，必须同时设计数据依赖与资源回收。

## 两个batch的双缓冲时序

假设slot0服务batchA、slot1准备batchB。每个slot经历可写→准备→设备读取/写入→输出消费→可复用。CPU想写下一个A2时，必须确认A对应的全部设备与输出读者结束。

只等kernel末尾某个event可能不足：若结果随后被另一stream复制、采样或传输，slot仍有读者。反过来，socket写完也不证明KV不再被设备访问。应为输入、输出、KV和通信buffer分别记录生命周期，而不是用同一个done标志。

第5章的batch pin是host模型；真正接CUDA需要覆盖全部依赖stream、明确事件在哪个stream记录、等待关系及失败传播。记录event的stream没有覆盖实际工作时，计时与释放都可能过早。

## Graph 的稳定条件要落实成 guard

Capture记录执行图，replay复用该结构。通常需要固定或可控的地址、shape和执行路径；输入值改变要写入正确的缓冲。页表metadata动态变化也必须按backend支持方式更新。

固定SGLang样本中，ModelRunner先检查forward mode、graph runner与can_run；满足才replay，否则进入decode/extend等路径。replay还包含准备和输出裁剪，不能将“有graph_runner对象”当成每次命中。

建议记录shape_signature、命中/fallback原因、实际与padding batch、准备时间、捕获显存和KV余量。输出裁剪需要按真实token数，禁止将padding token发送给客户端或纳入usage。

## Graph 与 KV 的预算冲突

虚构KV预算2048MiB、页384KiB、每序列80页，上界68条。若capture多占384MiB，剩1664MiB，仅能放55条。即使每轮launch更少，队列或重算也可能增加。

扩大capture batch集合还可能增加冷启动与图池副本。比较时分开编译、初始化、capture、首请求和稳态。主baseline保留已有成熟Graph配置；eager用于消融，不能删除原优化后再以此证明收益。

## 一次采样要回答一个问题

系统时间线先看CPU gap、kernel、copy、collective和同步。确认值得深入的kernel后，再取硬件计数器研究DRAM、算力、寄存器和stall。最终吞吐使用无profiler的独立run，采样run另记开销。

已有命令生成器默认只输出argv，可直接复现：

~~~text
python tools/perf/operators/profile_operator.py --tool nsys --output-dir tools/perf/reports/engineering-v0.9/profile-plan
python tools/perf/operators/profile_operator.py --tool ncu --output-dir tools/perf/reports/engineering-v0.9/profile-plan
python tools/perf/operators/profile_operator.py --tool torch --output-dir tools/perf/reports/engineering-v0.9/profile-plan
~~~

不加execute。真实执行仍经过原plan审批和工具检查；本轮没有启动Nsight或GPU。Profiler replay、注入和缓存扰动可能改变原执行，所以输出不作正常计时。

## 读一条假设时间线

教学例：一轮有CPU准备20µs、可暴露launch gap30µs、GPU计算200µs、暴露通信50µs。若launch gap减半，其他都不变，总量从300降到285µs，约1.053倍；若通信已和计算重叠，就不能再把总通信时间重复加进关键路径。

采用overlap后，用依赖DAG求关键路径，并核对每rank时间原点。nested span或重叠kernel的duration直接相加会夸大空间；两个p95相减也不能得到网络p95。给每次解释保留可推翻它的证据，例如Graph命中提高但G下降时回查padding/KV。

作业：画出A/B两个batch各自的四类buffer与event边界，指出每一个复用点的证明来源，再对照第11章实际结果队列。采样方法依据[Nsight Systems官方指南](https://docs.nvidia.com/nsight-systems/UserGuide/index.html)，具体argv以项目工具及获准版本为准。
