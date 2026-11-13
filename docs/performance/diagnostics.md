# 推理诊断体系的可运行起点

本轮在b4e7e27的性能资产上补齐最小诊断闭环。主产物是[可运行入口](../../tools/perf/diagnostics/README.md)、[25项采集地图](../../tools/perf/diagnostics/collection-map.json)、[13项资产台账](../../tools/perf/diagnostics/assets.json)及实际JSON/HTML报告。教材仅增加入口，不重做CPU调度对照。

## 起点与证据盘点

| 能力 | 已有证据可以说明什么 | 仍缺什么 |
|---|---|---|
| 原analyze与固定夹具 | TTFT/TPOT、共同窗口、完整sent、usage null/0/held、修订检查 | 受权真实导出、采集真实性与质量/SLO |
| runtime_metrics | 独立观察的恢复/删失与占用数学 | 实际停止/原allocation安全证据；它不执行回收 |
| controlled_transport | 有界本地回环/SSE机制 | 实际Go/Higress/存储/模型链路 |
| 算子骨架/CPU参考/finite门禁 | 数学与宿主失败路径、默认GPU拒绝、采样dry-run | 目标GPU的数值/精度、成熟baseline与真实profile |
| R1运行时/页预算调度 | host状态与CPU逻辑；静态194/200优于当前age_fair161/200 | 真实引擎/模型/多卡；原负结果不外推或重跑包装 |
| 固定源码/OBS映射/J02 | 路径与版本、采集/实验准备 | 当前部署版本、真实观测、基线与独立复验 |
| 新诊断sidecar | 关联/时钟/区间/显式依赖/缺失/证据闭环 | 生产exporter、真实校准和完整因果覆盖 |

实际远端默认分支为925d8c5，已含原PR #1–#4；当前后端候选PR #6为d2d7869。性能分支本轮仅新增自身目录，不把旧产品树覆盖到统一代码。原Go/MySQL业务真源与协议保持，MAAS-15配置和验收状态不修改。

## 请求到算子和通信的诊断地图

~~~mermaid
flowchart LR
  C[客户端 sent / SSE data / 非空content] --> G[Go 准入 / 输出 / 唯一终态]
  G --> R[Redis permit]
  G --> M[MySQL 锁 / 预留 / commit ACK]
  G --> H[Higress 固定路由 / 传输]
  H --> W[Worker queue / tokenize / batch]
  W --> P[prefill / decode / KV / detokenize]
  P --> K[GPU kernel / copy / launch]
  P --> N[rank / collective / 通信依赖]
  L[模型CR 活动修订 / 实例boot / 冷启动] --> H
  L --> W
  C --> X[获准脱敏导出]
  G --> X
  H --> X
  W --> X
  K --> X
  N --> X
  X --> D[原指标校验 + 新区间/依赖/缺口报告]
~~~

这是接线责任图，不声称这些生产采集已存在。collection-map逐项给出边界、原负责人、来源和OBS映射：客户端/Go/Redis/MySQL/Higress、Worker各阶段、KV、GPU/launch/copy/collective，以及冷启动/活动发布。外部API的供应商内部耗时不可见时不分配一个“模型残差”。

关联链为原server request/trace → experiment/run/cell/replicate → 冻结invocation binding/工件 → 实例boot → batch/rank。高基数关联保存在受控sidecar，不变成无限指标标签。原Secret/票据/Key/正文不进入常规日志。

## 报告闭环的实际实现

CLI读取原metrics文件和独立timeline sidecar，先调用原analyze完成协议/分母/usage/时钟检查，再核对原字节hash与关联身份。已知manifest工件必须和选中runtime metadata一致；缺失项留null并进入缺口清单。输入没有真实数据就输出缺口，不补零。

parent表示inclusive区间包含，predecessors表示明确导出的任务依赖；它们不互换。已导出的独占活动和可比较坐标才进入观察依赖链。区间并集处理重复/嵌套/重叠，shared batch不拆成逐请求独占。

当前跨域合并仅用于synthetic手算样本的零误差声明；真实controlled_export_unverified即使声称零误差，也保留原scope并阻断跨域依赖，直至可信校准适配另行实现。

Clock必须绑定实例/boot。映射限定为显式单跳affine关系，附来源、有效范围与误差声明；非零误差或失效时阻断跨域链，保留各自本地时长。声明本身仍是未验证输入，不能用“导入通过”证明真实同步。

本轮手算案例得到165ms的已观察活动链、185ms链跨度及20ms已知依赖间隙。kernel与collective重叠不会重复加权。父区间observed self只扣除导出的直接子区间，不能命名未观测的CPU/GPU瓶颈。全链路关键路径、残差和模型瓶颈仍为空。

原首SSE data、非空content、Go first_chunk与Worker原生token测点分列。源码只读核查显示默认925d8c5行295、PR6候选d2d7869行298仍有未检查content的first赋值模式；这是源码状态，不替代Go运行复验，产品采样修补由原后端收口。

取消/超时/未恢复数据复用原recovery_summary，按独立observer scope和截止分组。没有release则保留右删失；缺观察的请求另列。stop、safe/evidence、release、successor及财务held继续独立，不产生退款或关闭证明。

## 最小复现和真实导入约束

~~~text
python tools/perf/diagnostics/run.py --metrics-input tools/perf/fixtures/synthetic.json --timeline-input tools/perf/diagnostics/fixtures/timeline.synthetic.json --output-dir tools/perf/reports/diagnostic-demo
python -m unittest discover -s tools/perf/diagnostics -p "test_*.py" -v
~~~

新目录内同时生成report.json与独立report.html；错误输入不发布，旧报告不覆盖，错误消息不含输入内容。无需GPU/模型/服务。依赖沿用jsonschema4.25.0，不自动下载。

真实sidecar是工具侧提议，原Observation/终态不加字段。生产导出接点尚未实现：需要按已有权限导出原指标、资源身份、时钟校准、exclusive活动/依赖与证据摘要，原请求清单不能缺拒绝/失败/pending。若采用OTLP或Nsight文件，需要独立适配器与正反校验，当前没有宣称通吃生产trace。

区间不能由已有duration反向虚构起止时间，parent也不能自动推断为阻塞依赖。计数器只作相关证据，occupancy/利用率不能直接命名瓶颈。NVTX和采样机制参考[Nsight Systems官方指南](https://docs.nvidia.com/nsight-systems/UserGuide/index.html)；Span/Link语义参考[OpenTelemetry Trace API](https://opentelemetry.io/docs/specs/otel/trace/api/)，本sidecar不声称是OTLP标准实现。

## 下一批单因素实验与精确输入

机器清单在[next-experiments.json](../../tools/perf/diagnostics/next-experiments.json)，真实实验execution_enabled=false，SLO/质量/收益阈值尚未确认。

| 顺序 | 具体工作 | 需要谁提供什么 | 完成条件 |
|---|---|---|---|
| D1 当前报告与采样接线 | 冻结最小导出与测点定义，一次修一个采样/导出问题 | MAAS-2字段增量审定；原后端首内容语义/真实脱敏导出；运维clock/实例boot来源 | 原始数据与报告一致；错配/跨钟/缺失正反校验 |
| E1 实际平台＋受控上游 | 沿原链路测一次固定负载，再选传输/flush单因素 | 原后端/运维提供实际Go/Higress/存储/Secret/validation装配及获准Key/额度/price/slot | 同业务约束下client/Go/上游分层、完整分母、账本/取消/清理 |
| K1 算子 | profile支持后只改一个backend/layout参数 | 算法给实际shape/dtype/误差/质量；运维给GPU/版本/limits与Profiler | 成熟cuBLAS/native SDPA/norm对照，数值先行，正常计时与采样分开 |
| R1 引擎chunk/KV | 复用目标版本现有静态/动态机制，一次只改chunk | 模型/权重许可、tokenizer/template、引擎commit/镜像/库、GPU拓扑/rank、实际KV/Graph/activation预算与J02/SLO | 全引擎质量、长短尾延迟、G、显存、拒绝/未恢复与代价 |
| R2 Graph/通信 | 有launch或暴露通信证据后，单独改capture集合或通信组织 | 同总GPU/精度/拓扑与all-rank trace、同步/消息依赖 | 暴露关键工作减少且无质量/资源/业务回归 |

每次冻结模型权重/模板/精度、GPU/互联、版本、CPU/网络、资源cap、输入输出和到达计划、冷热/种子/截止。区分编译、预热、冷启动、稳态、采样与正常运行。代价包含显存、错误、未恢复及可获取成本；未知实际不算0。

“业界一流”以同条件成熟算子/引擎的可复核基线、已确认质量/时延约束下有效吞吐、尾延迟/显存/成本联合结果和MAAS-7独立复验衡量。公开榜单条件不同不能直接比较，当前不宣称达到该目标。

## 本阶段可验收范围

本轮交付资产/缺口台账、跨层地图、新导入校验和最小报告闭环，执行CPU/受控验证。真实采集、模型/GPU/平台基线及A01–A34整体验收继续按门槛。跨角色协作先把上述具体缺口交Mika协调，不重复派发已有负责人。
