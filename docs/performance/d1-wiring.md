# D1：把实际Go采样接到局部诊断报告

本轮以8420aaf为起点，仅修改tools/perf/diagnostics和本目录。原后端在PR #6交付了[c7e863b](https://github.com/jianzi123/maas/commit/c7e863b11fb34ee2828c947393444e1e5a9baf08)，本轮消费其已运行的Go/临时MySQL/受控HTTP产物，没有重跑Go、创建数据库或修改产品源端。

**Go局部源→校验→JSON/HTML已接通；D1整体尚未完成，E1/K1/R1/R2未执行。** 这份报告不具备完整客户端分母、真实Higress/Worker/GPU或跨进程校准，因此没有TTFT、RPS、模型瓶颈或性能提升结论。

## 实际输入、输出及证明边界

源端说明是固定提交的[go-relay-d1-export.md](https://github.com/jianzi123/maas/blob/c7e863b11fb34ee2828c947393444e1e5a9baf08/docs/go-relay-d1-export.md)。源导出是内部maas-go-relay-export-1.0 / maas-go-relay-source-1.0，**不是**完整诊断sidecar或Observation1.0，不补造票据/终态/活动工件身份。

- 原始go-relay-d1.json：SHA256 a2589061b5c39fb259397e6bdf6129cbdb16bce8579318438fe760642fb51458。
- 原始manifest：SHA256 9cf52e7a5b3338a6f115d087a621fb3f0a932bccdc07bff7ca592ad97378eb9c。
- manifest交付commit c7e863b11fb34ee2828c947393444e1e5a9baf08的六个源文件经git show逐字节hash核对通过。
- 样本source_revision原值working-tree-d1保留。事后交付commit/hash是来源索引，不能证明采样时已记录该commit；capture_commit_attested=false。
- 源端作者日志有10个场景通过，其中9条摘要和一个额外full_sampler丢样执行。作者日志不是本轮独立重跑；原QA仍需核验同SHA的error锁存和采样负例。
- 实际组件为Go Relay.Forward、临时MySQL和受控HTTP；网关proof/gate为测试适配。instance/boot是真实本地采样器ID，不能升级为生产实例registry或Worker身份。上游payload及35/60ms等待是故障/测点测试注入。

输出d1-import-report-1.0复用既有HTML/publish，不改原report.schema或完整诊断校验入口。report.json/report.html列已知与缺失；consumer-import-overhead.json记录本Python进程解析/校验/组合开销（包含可选git读取，排除渲染/发布），不称源端热路径开销。

## 复现：原始附件到报告

以下在仓库根目录执行。Python3.10+及已有jsonschema4.25.0即可，不需要GPU。先通过认证CLI获取源端原件；每次下载失败立即退出：

~~~powershell
foreach ($id in @(
  "01a1d46d-3a05-7f3a-b572-8d9449a4f2f6",
  "01a1d46d-3b48-7a02-a4d5-a7e4ce0d07da",
  "01a1d46d-3c6c-78b5-8819-35e53a805ca0",
  "01a1d46d-3dab-70db-9247-b4ef373750e6"
)) {
  & "$env:MULTICA_CLI_PATH" attachment download $id --output-dir ./inputs-d1
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
git fetch origin agent/MAAS-3-usage-authority
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python tools/perf/diagnostics/consume_relay.py --raw ./inputs-d1/go-relay-d1.json --manifest ./inputs-d1/go-relay-d1-manifest.json --expected-manifest-sha256 9cf52e7a5b3338a6f115d087a621fb3f0a932bccdc07bff7ca592ad97378eb9c --expected-source-commit c7e863b11fb34ee2828c947393444e1e5a9baf08 --source-repo . --output-dir tools/perf/reports/d1-go-import
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m unittest discover -s tools/perf/diagnostics -p "test_*import.py" -v
~~~

输出目录必须全新。hash、源commit、字段、时钟或关联错配均退出2且无成功报告；已有输出不覆盖，错误不回显输入。省略--source-repo可离线验证原始文件/manifest内部一致性，但报告source_files_verified_against_delivery_commit=false，不宣称已核对源文件。

原始采集入口是固定源提交的bash scripts/collect-relay-d1.sh，在其已有授权的Go1.26/临时MySQL受控环境运行，并调用scripts/test-controlled.sh。消费端不执行manifest中的命令，不自动运行采集或安装依赖。重新采集后hash会改变，须保存新原件、manifest、源码版本及对应日志，经核对后使用新hash，不能继续冒用本次固定hash。

## 四个测点：为什么不能混算

| 源字段 | 实际语义 | 不代表什么 |
|---|---|---|
| first_protocol_ms | 首个合法data协议事件接收，含role/空内容/usage，排除heartbeat/DONE | 不代表首非空内容，也不是写成功 |
| first_content_received_ms | 接收首个合法非空delta.content，在诊断DB及write之前 | 不是客户端接收 |
| first_content_write_ok_ms | 首内容完整Write返回且err=nil | 不保证flush/网络交付或客户端可见 |
| first_content_flush_attempt_ms | 调用Flusher.Flush尝试 | 无ACK，不保证Write成功 |
| end_ms | 本次Forward函数结束 | 不是客户端E2E或GPU实际停止 |
| clock_scope | instance/boot/request绑定的Forward=0局部单调坐标 | 不同request即使同boot也没有公共时间原点 |

原terminal.first_chunk_ms以request.Received为起点，源端已改为首非空内容接收。本导出没有该legacy值，因此report中的go_server_first_chunk_ms=null；**不得**用Forward起点的content值替填。

合法局部差值是同一request的write_ok-content_received。本次正常content样本约83.203ms收到、143.671ms完整Write返回，差值约60.468ms，含测试注入及该路径工作，不能将其命名为数据库瓶颈。write_failure的write_ok=null、flush_attempt约140.350ms是合法失败观察，不能用flush反推Write成功。

空/usage-only样本content/write/flush均null；非流式或无合法事件可以四个测点全null，只保留end。数值0是已知0，不转成null；缺测也不补0。

## 实际结果及分母

| 观察 | 数值 | 可用分母 |
|---|---:|---|
| 导出摘要 | 9 | manifest声明的10个场景执行：9/10=90%，含1次额外满队列丢样 |
| Go观察result | success3 / failed2 / interrupted1 / cancelled2 / timed_out1 | 9条已导出摘要；不是终态3.0或业务成功率 |
| 首协议片存在 | 9 | 9条摘要 |
| 非空内容接收存在 | 3 | 9条摘要，空内容本来不适用，不能把其余6条统称采集丢失 |
| 完整Write成功存在 | 2 | 9条摘要 |
| flush尝试存在 | 3 | 9条摘要，其中1条Write失败 |
| usage / held缺失 | 各9 | 原导出未含耐久账本，不借旧请求记录回填 |
| 非成功且无独立恢复观察 | 6 | 9条摘要，保留原request列表；不推断slot释放/actual_stop |

完整client sent、拒绝/pending、全局drop counter、全局丢样率、公共窗口和吞吐均null。90%仅是本组manifest已声明场景的摘要覆盖，不能外推客户端/采样器的全量覆盖率。没有终态账本/receipt的本格式也不能将Go observed result当唯一结算证明。

实例/boot/request/clock、run、publication/release和原文件hash均保留。full invocation_binding、trace、experiment/cell/replicate、权重/引擎/config等完整工件引用缺失，不生成伪值；因此不组装exclusive区间/关键依赖链、不跨时钟归因。报告完整缺项表沿用25项采集地图，eligible分母未知时覆盖率也未知。

源端10.31ns/op、0B/0alloc只测满队列offer丢弃路径，**不含**所有时间戳/summary构造、成功队列、导出、数据库或整个业务热路径。它不能替代同负载采样on/off配对；报告保留whole-path开销未知。本轮导入器实测开销单独随报告给出，不写成推理开销。

## 校验、回归及旧产物复用

本轮完整CPU工具回归276项通过：原234项、本轮旧QA适配20项、新relay适配22项。回归源码hash在运行前后固定；这只是工具作者验证，不替代独立QA或CUDA/模型/端到端验收。

新格式回归覆盖hash/commit、版本/run/request/boot/clock错配、重复或未映射request、私密额外字段、非有限/负值/boolean时间、缺前驱/倒序/越界、真实0/null、全无内容、Write失败仍flush、取消/超时/EOF、缺校准/全局分母未知、丢样场景覆盖以及失败无输出/不覆盖旧报告。源源码读取固定六个允许路径，只读git show，不执行源命令。

同时保留旧QA faf1b64（产品d2d7869）的归档适配consume.py，作为既有耐久usage/账本接线回归。其输入的20个不同request、19个case、原oracle失败及修正复跑均保留；不是本次c7e863b请求，**禁止按case名拼接**到本报告。

~~~text
python tools/perf/diagnostics/consume.py --archive ./inputs-d1/MAAS-7-usage-reader-independent-evidence.zip --expected-archive-sha256 ca6c85428ab91a675fdea163bf3a541812dff4cfc5e751e11c871c7b70d49e8c --expected-source-commit d2d7869fe16b8968d6ca5b00a63560c322b84dc1 --output-dir tools/perf/reports/d1-historical-qa
~~~

旧归档通过认证附件01a1d42c-eb2b-7b95-97ed-2a78e8019b29下载。只读主记录、修正复跑、结果摘要及测试源码见证四个白名单成员和manifest；不解压/转发环境变量、数据库日志或缓存。原terminal3.0和源diagnostic0.1-draft.1只读快照校验身份/修订/seq及账本known/held；原reserved与当前Reserved分列；diagnostic快照不求和，不替换final actual。原oracle失败不被修正复跑覆盖。源snapshot digest保留但不冒充签名验证。

## 下一步精确输入与单因素顺序

由Mika协调原后端、运维与原QA，不另开产品实现流：

1. **独立源/消费复验。** 固定c7e863b及本消费者新SHA，原QA复核error锁存（内容前/后）、首内容/写失败、队列满负例及导入报告；不拿旧Usage20/Reader12或作者10/10替代。
2. **D1补关联与分母。** 同request完整client sent/拒绝/失败/取消/pending及截止，client首协议/首内容接收，真实source/活动修订/工件、trace、experiment/cell/replicate；源端可提供的身份据实映射，新增公共字段先由架构评审。未经校准只保留各自局部时钟。
3. **D1开销对照。** 同源SHA/资源/受控负载只改变采样开关，固定并发、到达、连接冷热、预热/截止、队列容量与丢样计数；采集独立client计时和完整业务结果/耐久账本/恢复。全局drop计数与成功队列、满队列路径分别留证，报告on/off差值与分母。
4. **E1真实接线后再跑。** 获准的Higress/Redis/Go/MySQL完整受保护路径、有效adapter/Secret/validation、实际接流boot及独立恢复观察齐备后，先固定受控上游做基线，再单因素改变一个传输/采样因素。没有确认SLO不判goodput通过。
5. **K1/R1/R2仍禁用。** 必须另有具体GPU授权/型号数量/显存互联/资源cap/清理、兼容CUDA框架与Profiler、获准模型权重/tokenizer/模板/精度、固定负载、质量/SLO及调用/预算/停止阈值，才执行对应真实实验。

共享票据v3/终态3.0/Observation1.0与唯一Go/MySQL业务内核不变；unknown actual、held与slot/stop分开，固定来源且缺证据故障关闭。所有真实执行计划execution_enabled=false；MAAS-15配置及done状态不变。
