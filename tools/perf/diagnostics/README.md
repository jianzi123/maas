# 请求到内核的离线诊断闭环

新增入口复用 analyze.py 的指标/协议/用量/分母校验，以及 runtime_metrics.py 的恢复右删失计算。诊断sidecar只补区间、实例/boot/rank/batch关联和显式依赖，不修改票据v3、终态3.0、Observation1.0或原report.schema。

## 实际受控源端消费

[消费接线说明](../../../docs/performance/d1-wiring.md)提供固定原件/manifest/hash、采集命令和消费命令：

- consume_relay.py：版本化Go D1源端export适配，消费c7e863b实际Go/临时MySQL/受控HTTP的9条摘要，报告manifest声明的9/10场景摘要覆盖、失败与缺项；不把每请求Forward局部坐标混成公共窗口，不以flush当客户端接收。
- consume.py：保留原QA faf1b64、产品d2d7869的20条耐久终态/诊断归档适配，校验usage/账本等，原oracle失败与复跑保留；不能按case名与新源request拼接。
- 两者仅生成d1-import-report-1.0局部降级报告，不补造完整diagnostic sidecar或Observation身份。原run.py严校验保持；CLI错误退出2且无报告，旧报告不覆盖。
- source_import.py / relay_import.py：封闭字段、hash、实际request/修订/boot/时钟映射与缺失规则。源码读取只允许六个固定路径；不执行manifest命令或采集。
- test_source_import.py / test_relay_import.py：42项新增合成回归；实际逐请求证据单独交付，不塞入合成fixture。

client完整sent、trace/完整binding/工件、实验身份、实际Higress/Worker/GPU、可信跨时钟校准与采样on/off开销仍缺。D1整体/E1未完成，执行计划禁用。source_revision=working-tree-d1原样保留，交付commit不是采样时commit证明。

## 最小运行

已有Python3.10+与jsonschema4.25.0，沿用tools/perf/requirements.txt；本轮不安装依赖：

~~~text
python tools/perf/diagnostics/run.py --metrics-input tools/perf/fixtures/synthetic.json --timeline-input tools/perf/diagnostics/fixtures/timeline.synthetic.json --output-dir tools/perf/reports/diagnostic-demo
python -m unittest discover -s tools/perf/diagnostics -p "test_*.py" -v
~~~

output-dir必须是新目录，成功产生report.json和无需外部资源的report.html。输入身份/版本/时间错误退出2，无新报告、不回显Schema值、SSE内容或错误哨兵。已有输出不覆盖。

真实导入使用相同入口，将两个输入换成获准的脱敏指标数据与sidecar文件；synthetic=false要求sidecar.evidence_kind=controlled_export_unverified。校验通过只说明输入内部一致，不证明导出来源可信、生产Ready或已达到SLO。

## 文件与数据契约

- collection-map.json：25项诊断采集边界/来源/原负责人，与OBS01–19相接。
- assets.json：13项已有资产、证据级别和缺口；历史结果不冒充本轮重跑。
- manifest-template.json：同模型/权重/tokenizer/模板、引擎/配置、GPU/互联/rank、CPU/网络、到达负载、SLO/质量/预算和批准引用。缺失为null，execution_enabled=false。
- fixtures/timeline.synthetic.json：16个手算区间，含跨时钟声明、重叠kernel/collective、共享batch和取消缺结束；timing-origin.json是明确的人工来源。
- validation.py：封闭工具字段，dataset原字节hash、run/cell/replicate、request/trace/活动修订、runtime工件、实例boot/rank/batch、证据hash与clock绑定校验。
- timeline.py：parent/依赖图检查、区间并集、可解释观察self区间及最长已观察活动依赖链。
- report.py：原指标、分层覆盖/缺口、协议首事件/可见内容/Go/Worker测点、恢复组和证据索引。
- next-experiments.json：按依赖顺序的单因素实验、已有命令与准确输入门槛。空commands表示真实接线未交付，不能伪造可执行模型入口。

## 区间与时钟规则

每个interval包含 request_id、trace_id、binding_sha256、runtime_metadata_ref、stage、instance/boot、rank/batch、clock、start/end、parent/predecessors、attribution及evidence_ref。未知结束用null。parent仅描述inclusive包含关系；predecessors只能连接请求独占activity，不能由span父子或时间先后推测。

当前跨域合并仅用于synthetic手算样本的零误差声明；真实controlled_export_unverified即使声称零误差，也保留原scope并阻断跨域依赖，直至可信校准适配另行实现。

时钟归属绑定实例boot。只有单跳、显式scale/offset、有效区间内、声明max_error_ms=0的映射才合并坐标；误差非0或过期时保留原clock内时长，并阻断跨域依赖。报告同时注明校准来自输入声明，工具不验证真实时钟同步。

父区间减已导出可比较直接子区间的并集，得到observed self；若子区间缺结束/时钟不可比则为null。未导出的工作可能仍存在，不能把self称为CPU/GPU忙碌或把未解释残差归到网络。

最长活动依赖链只对显式独占任务计算duration权重，不把重叠通信再加到kernel。end_to_end_critical_path_ms、unattributed_ms和model_bottleneck保持null，直到实际全链路证据能够支持相应结论。本工具不自动提升证据级别。

共享batch必须带batch成员/修订/实例/rank声明，不能标成逐请求exclusive activity。供应商external_api内部Worker/GPU不能冒充平台导出；provider.internal缺测明确输出未知。

## 合成案例的手算

原请求分母9，admitted8，成功4、失败2、取消1、拒绝1、pending1；actual known total41，unknown token held420。首个client data事件10ms、首内容100ms、Go first_chunk60ms，Worker原生首token未知。

三个父self区间分别为root5ms、Go10ms、Worker0ms；kernel80ms与collective20ms部分重叠。最长已观察活动链165ms，链跨度185ms，其中20ms是已知依赖间隙；不代表真实MaaS性能或完整端到端关键路径。

独立合成观察者在100ms截止仍未见release，保留1个unrecovered和90ms右删失；stop未知。其他失败/未完成请求缺恢复观察会单列，不以缺测推断安全释放，也不修改held。

更多盘点、跨层责任和接线顺序见[诊断体系交付](../../../docs/performance/diagnostics.md)。
