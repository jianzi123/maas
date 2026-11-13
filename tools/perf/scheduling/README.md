# 页预算下的 Prefill Decode 调度

本轮沿MAAS-10 CPU闭环，落实MAAS-13 S1的可执行算法与同条件对照。源码锁定、页级状态、接纳/切块/饥饿规则、负载、失败分母和开销均有独立入口。实现是CPU长度/页占用实验，真实GPU或模型未运行。

## 入口

调度比较器仅需已有Python3.10+标准库。完整测试和采样反例复用离线分析器，还需已有jsonschema4.25.0（见tools/perf/requirements.txt），本轮没有安装依赖：

~~~text
python tools/perf/scheduling/compare.py --output tools/perf/reports/pd-run.json --repeats 3 --horizon 4000
python -m unittest discover -s tools/perf/scheduling -p "test_*.py" -v
~~~

输出文件名必须未存在。没有GPU、模型调用、数据库或集群接入。--horizon是逻辑轮次截止，不是毫秒；--repeats最多5次，重复确定性逻辑不形成独立模型性能样本。

源码复现需显式只读获取锁定原文，再离线执行小范围AST探针：

~~~text
python tools/perf/scheduling/prepare_sources.py --source-root tools/perf/reports/pd-source
python tools/perf/scheduling/source_probe.py --source-root tools/perf/reports/pd-source --output tools/perf/reports/pd-source-probe.json
~~~

prepare_sources仅请求source-lock内六个固定官方URL，按保存的评审hash核验，不导入SGLang。source_probe复用原方法，仅执行已校验PrefillAdder预算函数，allocator/cache/Req是明确的CPU doubles，不是完整引擎对照。

首片采样定位：

~~~text
python tools/perf/scheduling/sampling_probe.py --repo . --output tools/perf/reports/first-content-probe.json
~~~

需要本仓库已有后端e1bd502对象；工具只读git show并核对具体赋值模式，源码改变时拒绝。产品补丁由原后端负责人维护，本脚本没有编译或运行Go relay。

## 文件职责

| 文件 | 责任 |
|---|---|
| algorithm.py | 完整同步调度、最坏输出预留、页对齐chunk、activation代理、老请求屏障与轮换 |
| pages.py | 有真实ID/代次/owner的主机页池，共享cache常驻、部分尾页COW与整批前空间检查 |
| compare.py | J02固定序列、独立静态调参集、四策略/两场景/配对重复、逐请求与开销 |
| source-lock.json / source_probe.py | 两个固定版本与六份来源，原始AST预算函数核验 |
| sampling_probe.py | 5ms无内容事件与30ms首内容的采样反例和后端行号 |
| test_scheduling.py | 页公式、COW、容量、公平性、过载、缺失、CLI与指标分母回归 |

算法、伪代码、条件保证、真实运行门槛及本轮负结果见[工程卷第14章](../../../docs/performance/engineering/14-page-budget-scheduling.md)。当前年龄公平参数在固定截止下完成数较少，不能晋级为已获收益方案。

## 报告与计划

schema为cpu-page-scheduling-1.0；execution_enabled=false表示真实引擎实验尚未打开，CPU本地逻辑可按上述命令运行。规划耗时是实际host perf_counter_ns，逻辑轮次/输出位置是合成状态；都不能外推GPU吞吐、模型质量或客户端SLO。

前缀设为精确匹配的合成33个位置，每4条共享一次；缓存驻留占3个16位置页。KV容量由显式字节预算折算，实际主机页ID分配不能代替GPU地址和rank布局验证。activation使用线性占位模型，真实曲线须从目标引擎profile确定。

故障组按固定请求/轮次取消、第三次调度服务注入失败，1条缺回收保持unrecovered。不同chunk使注入时的已处理位置不同，因此故障组仅核验保守恢复和分母，不用于净性能归因。原runtime_lab另外覆盖异步在途取消、旧代次与独立停止；本调度实验的释放发生在同步轮次边界。
