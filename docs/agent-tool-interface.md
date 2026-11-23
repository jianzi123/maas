Agent工具接口 v1（复用AR-1／ToolRegistry）
=======================================

注册仍是原`ToolRegistry`与`Tool`：`Spec() ToolSpec`给name/version、input/output JSON Schema、required scope、effect、requires approval；`Execute(context.Context, Principal, callID, json.RawMessage) (string,error)`执行。`Definition(tool)`提供包含description的仓库类型，既有AR-1公开ToolManifest字段不改。输入规范化并校验，输出按声明Schema校验和字节上限，数据不成为system指令或HTML。

执行元数据从`ToolExecutionFrom(ctx)`取得，包含可信Principal/权限、session/run/step/tool_call、原子模型request_id、trace_id、稳定idempotency_key、fence与deadline。元数据由循环读取耐久执行事实生成，不接受arguments内owner/scope/标识覆盖；`ctx.Done/Err/Deadline`控制同一个工具调用，适配器必须合作终止，不能后台执行后假报超时。

真实例一：`bounded_arithmetic@1`，pure、scope tools.calculate；input为`{"a":6,"b":7,"op":"multiply"}`，参数Schema限制整数范围与白名单add/subtract/multiply、禁止额外字段；output string `"42"`。实现不eval，不读文件或网络。

真实例二：`list_visible_models@1`，read、scope models.read；input `{}`、禁止额外字段；output string中为当前授权目录的JSON数组，如`"[\"approved-model\"]"`（沿现有Execute string约定）。正常产品读取配置所引用的原MySQL Profile，不暴露URL/Secret；测试可提供明确受控目录。没有权限时返回规范拒绝，模型选择名称不提升权限。

工具注册与版本/schema摘要冻结到Run；提案、批准与dispatch前重核当前授权。需要批准的扩展绑定owner/授权域、run/step/call、规范args_sha256、工具/策略版本及有效期；decision_id同载荷幂等、异决策409，取消/过期/更改后不可复用。模型必须完整结束且原子终态确认后才执行工具，不从半截JSON/delta或diagnostic_only启动。

执行前原call身份/attempt/意图落MySQL，结果与消息/事件/checkpoint一起CAS。取消请求与工具实际返回分开；总时限/工具时限按原AR-R02合法ToolCall状态和实际attempt处理。错误不当成功输出；读/纯工具已实际失败是failed，非幂等副作用结果不明为unknown、Run needs_confirmation。用户确认不等于批准重跑未知操作。

默认不重试。纯/只读也只有原调用结果已查清且策略明确允许时才能用原call身份新attempt；幂等写必须有远端原key查回/去重证据。进程/MySQL重启按原身份恢复，不能新建call或换request_id补发。父Run不再扣量，原子调用仍走唯一Go/Higress准入/结算。

类型/Schema：`internal/agentruntime/types.go`、`tool_context.go`、`docs/contracts/agent-runtime/ar1-draft2/openapi.json`的ToolManifest/ToolCall/Approval和原事件Schema。执行示例为正常AR-1 RunCreate的tools清单与模型tool_calls；安装者不直接从浏览器调用Execute。`ar_http_test.go`和`ar_review_tools_test.go`有安全工具、批准、超时/取消、未知不重放轨迹，作者/独立范围分别记录。

MCP、外部HTTP工具、文件、shell、检索/长时记忆、子Agent目前是受控扩展口，未注册为正式工具；本接口不是这些能力已实现的声明。新执行器须沿同一scope/schema/审批/幂等/unknown规则，不另造循环或第二计量系统。
