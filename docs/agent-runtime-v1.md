MAAS-20 原生 Go 运行时 · 第一段实现
=================================

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
