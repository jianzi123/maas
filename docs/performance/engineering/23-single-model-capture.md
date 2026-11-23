# 23｜单模型采集接线与ELIT-QA-01修复

本轮按单模型ExternalAPI里程碑接续，先修原件拒绝门禁，再补性能自身目录的客户端采集/消费。旧GPU批次、plan ab0ac451、原始向量及0/18因果资格不改；没有重复1080块或新增GPU实验。

## 1. 原分析器的实际缺陷与修复

QA df4d45c发现：R01首条gate的native/mature都改成空列表，旧zip比较不执行，CLI仍成功。原件本身完整，缺陷是损坏证据可被接受。修复要求每侧恰有完整logits和KV两份角色，variant集合恰为native/mature；logits必须FP32[B,49152]，KV必须FP16[30,2,B,3,64]，对应当前固定0.22模型协议。角色/位宽/层数、finite、实际shape/dtype/raw hash、archive内容及N/M位级一致均严校；13个cell/phase身份也完整核对。

旧plan冻结了旧分析器hash。为避免改旧plan或放松producer：保留旧分析器原字节到legacy_source/analyze_kv_cadence.v0.22.py.txt，hash fdf166d738e4d85376a968ed8731aa82028f4c03f4c4c83ef73335d41c87be62。新版离线入口只允许这个已知历史分析器由新门禁替代；其他五份producer/helper源码仍须与plan逐字节一致，未知分析器hash拒绝。没有执行归档.txt。

GPU重放旧计划仍应使用原执行checkout6477d5d；新checkout不能偷偷绕过GPU侧source freeze。仅离线分析采用这条明确的兼容路径，summarizer同样消费经过该检查的plan。

~~~text
python tools/perf/operators/local_gpu/analyze_kv_cadence.py --plan ORIGINAL/plan.json --root ORIGINAL --output NEW_STRICT.json
~~~

36项元数据/完整向量回归通过（含旧16）；6份实采元数据变异经实际CLI非0退出且无成功报告：双方空、单侧空、另一侧空、不对称、缺variant、角色交换。双方相等但截断logits、错误位宽或缺KV层也在回归中拒绝。正确原件复算108cluster/1080块，clusters/triplets与全部数值未改，Full仍0/18。结果是修复拒绝门禁，不是新GPU性能验收。

## 2. 客户端实际采什么

client_capture.py使用真实HTTP read1和增量UTF8/SSE分帧，在收到字节后按完整事件记录时间。first_protocol_data_ms为第一个完整data事件，first_content_received_ms为choices[*].delta.content首个非空字符串；role、空content、usage-only、reasoning/tool字段不提前触发首内容。content_events是事件数，不是token；DONE、finish_reason、EOF和内容后error分别处理。

记录本客户端monotonic scope和相对时间；dispatch_attempted不等于服务端收到，request_write_completed只表示HTTP写阶段返回。响应X-Request-ID仅在canonical UUID时保留。正文、提示、Key、原始错误消息都不导出；collector_source_sha256标识实际采集源码。

client_stopped_after_content只表明本端停止读取并关闭连接；不能推出服务端取消ACK、退款或slot释放。business_terminal_result/actual_tokens/Worker耗时保持null，最终用量仍读Go/MySQL原requestID结果。

18项实际loopback HTTP/解析/时钟测试通过；另保存4条真实CLI记录（正常、内容后错误、本地停止、HTTP503）。流源为本工具自有Python测试服务器，未经过Go/Higress或模型，不是MaaS/模型性能基线，也未据毫秒字段宣布收益。UTF8逐字节拆分、完整事件边界、多事件合并、超时和无DONE均覆盖。

## 3. 实际入口和批准输入

~~~text
python tools/perf/diagnostics/client_capture.py --manifest PLAN.json
python tools/perf/diagnostics/client_capture.py --manifest PLAN.json --body-file PRIVATE_BODY.json --output NEW_CLIENT.json --execute --approval-ref APPROVED_REF --key-env MAAS_PERF_PLATFORM_KEY
python tools/perf/diagnostics/associate_client_relay.py --client-source CLIENT.json --go-sample GO_SAMPLE.json --expected-go-sha256 SHA256 --output NEW_ASSOCIATION.json
~~~

默认只校验，不发请求；模板single-model-client-plan.template.json因URL/批准信息未填而拒绝。真实执行需由原角色提供当前受保护Go/Higress URL、平台Key安全渠道、批准引用及运行上限，再显式execute。批准引用字符串校验不认证审批，更不授予绕过Go直连供应商的权限。本轮只对自有loopback源执行，未使用真实平台Key或供应商。

采集器是有界HTTP/1客户端，输出新文件、不重试/重定向/跨来源回退；socket/读取deadline和字节上限不替代服务端业务deadline。实际环境还应按任务规定用外层进程时限收齐运行。协议模式当前为流式Chat Completions，不能据此宣称其他模型协议已兼容。

## 4. client→Go→Worker如何关联

associate_client_relay.py核Go源原字节hash、同run/同canonical request ID、Go instance/boot/clock scope及局部时间有限性。输出仍是request_id_only_unverified：没有可信的trace/binding/运行实例证明就不提升来源等级。

两个时钟列分开展示：客户端从其HTTP尝试起点计时，Go RelaySample从每个Forward起点计时。不能相减得到网络耗时、不能把Go flush当client收到，也不能混为共同RPS窗口。当前consumer不补造trace、活动修订/引擎工件、Worker或校准。D1 overall保持false。

ExternalAPI供应商内部Worker/GPU默认不可观测；若无上游真实观测，交not-observed/unknown而非0。此前本地SGLang人工权重数据是独立实验，不能接到某次ExternalAPI请求上充当Worker。

## 5. 本轮已核的产品事实与原角色缺口

项目最新描述将产品流收敛到MAAS-18；MAAS-3为唯一后端主线，MAAS-8装配，MAAS-2/9提供批准输入，MAAS-7独立验收。读取MAAS-18完整描述的CLI多次返回Could not reach the Multica server，本轮依据项目最新描述、直接交接和实际角色线程实施，不声称读全未取回的里程碑细项。

MAAS-3最新评论明确旧4179工作台已过保留期，只证明历史管理链路，真实推理/Higress/adapter尚待接通；没有向该旧URL发请求。MAAS-8本轮[PR #13](https://github.com/jianzi123/maas/pull/13)代码6a21d85/交付84ff5a8因120项缺失/未批准输入拒绝就绪，不是120个产品缺陷。

| 原角色 | 需要交给本消费端的具体输入 |
|---|---|
| MAAS-3 | 当前获准受保护流式入口、平台Key渠道、原ID终态/用量读取；同一run的Go RelaySample原件与捕获版本；实际X-Request-ID关联 |
| MAAS-8 | 与后端一致的运行组合/来源锁、Higress/Secret/validation证明、instance/boot与日志/停止引用；不能复用过期实例在线声明 |
| MAAS-2/9，经Mika | 准确模型/mode/profile与批准引用、固定来源、额度/预算/价表、实际SLO/质量目标 |
| Go/实际Worker源负责人 | 可用trace/完整binding/时钟映射，或明确ExternalAPI内部不可观测；新增导出字段由原角色协调，不由性能工具伪造 |

本轮真实产品受保护链路、D1整体、E1和模型调用未执行。当前客户端工具与拒绝门禁已可审；已授权本地GPU研究仍有效，本轮未因平台链路缺失撤销它，也未重复旧GPU样本。下一GPU参考小窗继续遵守校准→冻结→独立holdout→主比较门槛，不把现有0/18改为支持优化。

## 交付前增量核对

最终增量线程已读到后端[PR #15](https://github.com/jianzi123/maas/pull/15)：代码d0b8b41a241a1b208516446d68fa8a6ca618c14d、四锁head ca1a173574d4ef2d20dfdc732e10476e2e035f25，依赖[PR #14](https://github.com/jianzi123/maas/pull/14)固定head00a3e62c539b726113fa21686e29096be88820e2。前者增加最小安装组合根、后者增加TLS工厂；均不是已运行的受保护模型入口。

生产binary尚未消费组合根，H1/完整H4、H2/H3真实sealed/boot、registry及validation仍缺；Wasm实际构建失败tinygo executable unavailable，批准工具链/digest也pending。没有将这些候选检查与PR #13或本性能分支相加当最终组合。Mika归并后须重新生成最终唯一四锁，消费端随后才按实际源采集。
