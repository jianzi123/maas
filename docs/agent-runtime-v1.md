MAAS-20 原生 Go 运行时 · 第一段实现
=================================

本轮更新：AR-1 draft.2 已实现
--------------------------

`NewARHandler` 现在提供原架构的19个操作，包括稳定principal域的原子创建命令、创建结果只读查回、Session内命令幂等/If-Match、消息与运行查询、分页、取消、审批决策、检查点及独立JSON/SSE事件入口。下方“第一段实现”的差异表保留为历史，**不再代表当前未实现范围**。唯一协议仍是目录中的原版AR-1 1.0.0-draft.2，入参和成功出参均用该Schema校验，没有增加第二套公开协议。

新增事实与约束：

- 创建映射与Session是同一条CAS文档提交；ID按稳定owner和原operation域确定，重复同hash返回原对象，异hash409。删除保留原映射；创建ACK丢失可只GET `/api/agent/v1/session-creation-commands/{operation_id}`。没有保留策略就不清理或复用ID。
- Run同命令匹配先于旧If-Match和当前较小策略；新命令要求原revision和空闲会话，完整RunLimits/工具清单只能缩小安装策略。wire调用数上限10000、Chat恰为1，超过wire范围400、超过安装策略422；金额/Token保持十进制字符串，超出原内核支持范围拒绝，不裁剪。
- 事件完整包络在状态/消息/检查点相同的CAS提交中保存。单Run seq为十进制字符串，事件UUID独立；256bit随机cursor是受保护的服务端映射，绑定其owner文档、session/run、版本和seq，跨Run或未知值400。重开存储按字节回放原包络，不重新投影历史。未启用事件清理，因此没有虚构cursor过期；未来清理必须保留代际/墓碑并返回410。
- assistant先持久message.created，再提交UTF-8字节offset的delta，最后committed完整投影；失败保留interrupted消息。快照与Run给相同提交水位。JSON与SSE用同一包络，SSE `id=cursor`、`event=type`；after与Last-Event-ID同时传即400。SSE跟随期间也复查会话权限，断线只GET恢复。
- 工具UUID与上游source_call_id分开，参数规范化并保存args_sha256；注册Schema/版本冻结到Registry摘要，提案、审批和dispatch前重核。工具输出Schema校验；重复相同参数/结果受no_progress_limit限制。工具Schema/结果/role包装纳入批准的上下文上界计数，缺Counter在发包前拒绝。
- 宿主按稳定主体重核当前授权，等待审批仍受原Run总期限约束；同Run调度去重，批准后原宿主继续原调用。取消先记请求，实际返回才结束；模型或副作用结果不明保留needs_confirmation屏障。生产Relay失败无原账本终态证明时也保守进入该状态。
- 父Run按每个子请求的权威投影分currency/price_version汇总known/inflight/held，使用大整数相加；来源未给分组则不补造零。aggregation_complete来自子投影完整性，不把完成态当费用全已知。真实MySQL测试验证原Admit/Finalize两次子调用、重复终态去重、两条唯一usage_events、Token known=38；父Run没有另写扣量。
- edit/regenerate保留原消息与消费。regenerate引用当前可见assistant，按原输入重建分支；新assistant保留supersedes关联。messages/steps/tool-calls分页只读；会话列表用创建时间/UUID锚点和HMAC保护，删除上一页对象不会漏读下一页。

应用接线：构造`NewARHandler(service, auth, catalog, explicitPolicy, paginationKey, originalOpenAPIBytes, streamWindow)`；Auth复用原Cookie/CSRF/Origin，Catalog从可信上下文解析模型/能力，不能从浏览器接收source/profile/凭证。`Service.Reauthorize`与`CountContext`必须是当前授权和获准来源的实现；真实模型出口用原Relay/Prepare/Usage/FailureResolved。生产tools-v1真实网关归一化/profile尚未批准/装配，保持拒绝；受控模型并不证明生产tools能力。

可供MAAS-5直接启动的受控AR-1服务（不含UI，不调用真实来源）：

```powershell
go run -tags agentcontrolled ./cmd/agent-headless --state-dir .cache/ar1-http --owner-id 4c421973-919f-4b8a-997f-909fc6fd010a --listen 127.0.0.1:4188
```

只能绑定127.0.0.1；使用原工作台 `POST /__maas/local-session`，Origin必须是`http://127.0.0.1:4188`，响应的csrf_token仅保存在客户端当前会话，后续写带X-CSRF-Token和同源Cookie。模型别名`demo`，capabilities明确标controlled，平台推理Key不能充当应用登录。服务不持有供应商凭证，两个工具是真实本地实现，目录只列当前测试用户的demo。Ctrl+C停止并等待自身Host/HTTP退出，文档保留于state-dir；独占锁不自动抢占。已完成Run只读恢复，已接受但未派发的Run可继续，旧在途进入待确认。开发分页key仅保存在state-dir，不能输出日志或加入源码。

可接受的测试请求限制示例：

```json
{"client_operation_id":"8be35f48-b66f-4d5c-ad44-9014a2d0053d","mode":"agent","operation":"send","text":"6乘7并读取可见模型","referenced_message_id":null,"model_alias":"demo","limits":{"max_steps":4,"max_model_calls":4,"max_tool_calls":8,"max_duration_ms":10000,"tool_timeout_ms":1000,"max_tool_output_bytes":8192,"max_context_tokens":32768,"no_progress_limit":3,"max_tokens":"100","max_money_atomic":"100","currency":"TST"},"tools":[{"name":"bounded_arithmetic","revision":"1"},{"name":"list_visible_models","revision":"1"}]}
```

先创建Session `{client_operation_id,title,model_alias:"demo"}`，Run提交带其返回ETag/If-Match；刷新只GET原创建/Run命令和快照。请求示例全部是测试配置，不是生产默认、真实计价或批准额度。宿主容量不足时原命令仍可查回；显式重投同一accepted命令可以调度原Run，不创建第二份；GET永不调度。

验证入口：`scripts/test-agent-runtime.ps1`（Windows及原始AR轨迹）；`scripts/test-agent-mysql.sh`（沿原test-mysql.sh创建专属临时MySQL，结束核对自身PID并清理）。真实数据库所需的固定工具路径由原脚本环境变量提供，不能用生产实例替代。最新结果见验证报告；原R1–R3/UI16等不在本轮复跑范围。

<details>
<summary>上一轮第一段内核说明和当时差异（历史）</summary>

已实现可替换核心、持久存储、受控 HTTP/headless 和真实安全工具。**共享协议唯一依据是 MAAS-2 的 AR-1 `1.0.0-draft.2`，本提交尚未提供其完整 HTTP 适配，不是完整 Chat 联调交付。** 先前提出的数字 cursor/client_id/同路径 SSE 候选已撤回为内部测试格式；`ControlledHandler` 只识别 `/__maas/controlled-agent/v0/`，没有占用 `/api/agent/v1`，不得接入正式前端或生产二进制。

架构原件在 [AR-1目录](contracts/agent-runtime/ar1-draft2/source.json)：OpenAPI、事件Schema、原ADR及B01/B02补充按字节保留，下载使用认证attachment CLI，两个ZIP SHA256均与架构公布值一致。API实施必须直接采用这些字段，不能另起协议。本任务继续 in_progress。

已实现的核心
------------

`ModelClient`、`ToolRegistry`、`SessionStore`、`AgentLoop` 是可替换边界；`Service.Drive` 是首个循环，`Host` 提供有界并发、执行前身份重核和停止等待。原生Go/Registry沿MAAS-2 ADR决定，不引入第二控制面或DSH运行时。官方参考固定 [Harness 2e39e704](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/docs/architecture.md)，无DSH兼容/性能声明。

Session聚合包含owner、Message/Part、Run、Step、ToolCall、Event与Checkpoint。所有变更使用revision CAS，消息/检查点/事件一起提交；一个会话一个非终态run，waiting_approval/needs_confirmation继续占执行屏障。接受态已采用accepted，Chat运行强制一次模型调用。内部client ID同载荷返回原run，异载荷冲突；公开client_operation_id/If-Match及原命令查回仍需AR-1适配。

MySQL迁移是 `internal/agentruntime/migrations/001_sessions.sql`，只新增 `agent_sessions_v1`，不复制财务账本。生产迁移使用单独迁移身份，运行连接仅需该表SELECT/INSERT/UPDATE。聚合保护上限为32MiB/2048条消息，会话列表最多200条；生产所需分页/归档沿AR-1后续实现，不能静默截断。

首期真实工具名已对齐 `bounded_arithmetic@1`（有界整数加减乘，不eval）和 `list_visible_models@1`（调用可信Principal范围的目录函数）。两者分别是pure/read，不内置write、shell、MCP、文件或外发工具。注册工具有Schema/版本/权限，执行校验当前权限与run原权限交集、版本和参数；工具输出以tool role数据回填。副作用接口只供受控测试验证未知结果不重放。正式ToolManifest输出Schema/effect/scope等DTO仍需对齐AR-1。

每步模型request_id在发送前持久化，父run只保存引用和已知/未知投影，不扣量。`kernelmodel.RelayModel`复用原 `kernel.Relay.Forward`，只支持text-v1；Prepare/Usage工厂缺失或tools-v1时拒绝。Prepare必须使用原获准Key/Profile/Ticket/Plan，发送前校验剩余Token/金额预留和币种，不允许直接供应商URL或回退。旧文本归一化继续拒tool_calls，生产tools-v1分支/profile未实现或未批准时不能启用Agent。

步数、模型调用数、Token、同币种原子金额、总时间、工具时间/输出、输入字节与事件数量采用显式Limits并冻结到run；测试值不是生产默认。任一子用量未知时不继续下一模型调用，对应累计值保留null。真实price_version/known/inflight/held/aggregation_complete投影尚需接原账本，当前内部Usage不是AR-1公开usage_groups。

取消先落cancel_requested，再取消当前执行context；实际模型/工具返回后才写终态，不释放slot、不退款、不清除held。工具提供者必须合作响应context。审批绑定owner/auth revision、run/call、工具版本与参数哈希，拒绝重复/过期/修改后批准；公开decision_id幂等和完整审批DTO仍待接。未知write结果进入needs_confirmation。

恢复由可信宿主先确认旧执行进程停止，再调用Recover隔离旧executor。ready/tools边界可恢复；model_inflight/tool_inflight进入needs_confirmation并保留原身份，不自动重发。没有通用“确认未知写入成功”的公开API。LocalStore是单进程开发实现，fsync后发布不可变版本并持有目录锁；崩溃锁不自动抢占，须核实`.owner-lock`的PID停止后再删除准确锁文件，不能作为生产MySQL或掉电保证。

编辑保留原消息和消费，以新输入关联原user消息；后续历史投影沿编辑分支。AR-1 regenerate引用原assistant/head的完整规则仍待适配，内部parent_message_id不能直接当共享referenced_message_id。

下一段公开适配清单
------------------

| AR-1固定接点 | 当前差异/下一步 |
| --- | --- |
| ConversationCreate/RunCreate | body.client_operation_id UUID，稳定principal域原子创建命令；Run If-Match同命令优先匹配；完整RunLimits与tools白名单 |
| B01 | 实现 `/session-creation-commands/{operation_id}`，原Session删除后映射仍保留；404/503均不证明未执行 |
| B02 | wire 1..10000/Chat=1；超过较小安装cap为422，不能裁剪。内部cap目前≤256，不宣称已验证10000完整恢复 |
| 消息/事件 | 严格AR envelope与事件data，UUID、run seq字符串、绑定scope/session/run/版本/seq的保护cursor；message.created→UTF8 offset delta→message.committed，同事务快照水位 |
| 事件入口 | `/events` JSON、`/events/stream` SSE；after与Last-Event-ID二选一，410后只GET快照；当前受控快照回放不是该协议 |
| DTO与命令 | RunAccepted.input_message、Command查回、accepted/fence、steps/tool-calls/checkpoint分页、原message关联及审批decision_id |
| 限额与账本 | max_tool_calls/context_tokens/no_progress、工具Schema和包装输入上界、price_version分组known/inflight/held与完整性，不能伪造0 |
| 身份与运行 | 原Cookie/CSRF/Origin，正式目录/Prepare/Usage工厂、真实MySQL与每child唯一结算；tools-v1批准和真实来源仍沿MAAS-18 |

这些都是本任务剩余实现，不以“架构待定”概括：draft.2现已给出确定规则。PR保持draft，不将受控Handler交MAAS-5冒充AR-1服务；正式接线在同一核心/PR增量完成。

复现
----

```powershell
./scripts/test-agent-runtime.ps1
go run -tags agentcontrolled ./cmd/agent-headless --state-dir .cache/agent-demo
```

headless的确定性模型被agentcontrolled build tag隔离，实际选择并执行两个真实安全工具、回填结果并落盘完整轨迹。测试数值为TST、100 Token/100原子金额、4步/4次调用、5秒（headless10秒）、工具1秒/审批1分钟、32KiB输入/8KiB输出/500事件；Chat内部仍强制单次。文件重开与未知状态验证是真实文件读写，模拟崩溃/受控模型和真实组件范围见验证报告。

MySQL唯一结算测试在 `internal/kernel/agent_runtime_mysql_test.go`。需原授权的disposable socket与MAAS_DISPOSABLE_MYSQL=1，执行 `go test ./internal/kernel -run '^TestMySQLAgentChildrenUseOneLedger$' -count=1 -v`；缺环境时明确skip。WSL启动失败记录保留，没有重启共享环境或调用真实模型。

</details>
