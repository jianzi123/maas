MAAS-20 Agent Runtime v1 · 实现候选
=================================

这是可运行的原生 Go 内核与候选 HTTP 入口，待 MAAS-2 审定共享契约后与 MAAS-5/8/17 装配。它没有修改原公开 `/v1/chat/completions`，没有开放生产模型工具调用。普通 Chat 与 Agent 使用相同存储、事件和执行服务。

设计事实、选择和边界
------------------

官方参考固定到 [DeepSeek Harness 2e39e70496aa02986ca6a820c5d497e816b69d7e](https://github.com/deepseek-ai/deepseek-harness/tree/2e39e70496aa02986ca6a820c5d497e816b69d7e)，读取其 [architecture.md](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/docs/architecture.md) 和 packages 导航。官方采用 Cordis 插件服务，模型适配、会话日志、工具和循环可以替换，提供 headless/SDK/Web 组合。这里借鉴组件边界，没有复制其运行时或宣称协议兼容。

ADR-20-01 建议采用 Go 接口：`ModelClient`、`ToolRegistry`、`SessionStore`、`AgentLoop`。默认 `Service.Drive` 实现循环；`Host` 提供有界并发和停止等待。理由是可直接复用现有 Go/MySQL、Higress Relay 和权限/预算约束。DSH sidecar 可复用 TypeScript 插件，但需要新增 Node 部署、跨进程取消/身份/存储映射，并适配每一步唯一准入；本轮成本更高。保留未来由锁版 sidecar 实现 `ModelClient` 或循环的空间。此为实现建议，最终 ADR/公开路径由 MAAS-2 审定。

本候选新增依赖为零，沿 go.mod/go.sum 的 Go 1.26.0、uuid 1.6.0、MySQL driver 1.9.3、jsonschema/v5 5.3.1。未启用外部工具、MCP、shell、文件执行、子 Agent、权重下载或真实付费调用。

实体与事务
----------

Session 包含 owner、Message/Part、Run、Step、ToolCall、RunEvent 和 Checkpoint。每次变更通过 session revision 做 CAS，消息、检查点和事件一起提交。MySQL 迁移为 `internal/agentruntime/migrations/001_sessions.sql`，仅新增 `agent_sessions_v1`；不修改 `generation_requests` 或预算表。安装迁移使用迁移身份；运行身份仅需该表 SELECT/INSERT/UPDATE，不需要账本写权限。生产装配须使用独立授权连接与现有数据保留策略。

两个副本同时启动同一 queued run，只有一个 CAS 可以取得 executor 身份；所有后续写入继续验证该身份。单会话最多一个非终态 run，包含 waiting_approval 与 needs_confirmation。client_id 在会话内唯一；相同输入返回原 run，不同输入返回 409。数据库提交结果不明时只按 client_id 查询，不重发模型。模型每步 request_id 在发起前写入检查点。

编辑/重新生成以新的提交、client_id 和 user message 表示；`parent_message_id` 必须引用本会话原 user message。传入新文字表示编辑，传入原文字表示重新生成。上下文取原消息之前的成功历史，再接新分支；原消息、run、子 request 和消费记录保留。当前只允许替换 user message，不支持任意 Part 原地改写。

存储采用有界会话聚合，默认无隐含生产限值；安装方必须显式提供 Limits。最大 2048 条消息、200 个会话列表项、32 MiB 聚合是实现保护上限；事件、输入/输出、步数、请求次数、Token、金额/币种、运行时间、工具时间和审批 TTL 由配置固定在 run。大历史分页/归档尚未实现，需要时返回明确限制，不能静默裁剪。

金额为安装方批准的同币种原子单位；本候选要求各子响应匹配该币种。生产适配须将价格快照及原子精度绑定到原 Model/Profile/Plan；不得把不同计价单位的原子金额相加。父 run 只展示子请求已知值之和，任何一项未知对应聚合为 null。子请求在发起前获得剩余 Token/金额上界；真实 Prepare 必须把该上界纳入原预留计划，不能只在响应后检查。

工具与模型
----------

内置真实工具为 `integer_calculator@1`（有界整数加减乘）和 `model_directory@1`（由可信 Principal 限定可见目录）。目录 Read 必须接已有授权目录适配；headless 示例只返回明确的本地受控目录。工具声明 JSON Schema、版本、权限、pure/read/write 等级和审批要求。write 必须要求批准，首期没有内置 write 实现。

模型仅提出调用，不能提供权限。注册表只向模型展示获准 Schema；执行时再次检查 run 原权限与当前权限交集、版本、参数 Schema。重复调用 ID、未注册或未授权工具、畸形参数都失败停止。每批最多 16 个调用，串行执行；输出作为 tool result Part 加回历史，不作为 system 指令。重复无进展循环最终受步数/调用数/预算/总时间限制。

`text-v1` 与 `tools-v1` 显式协商，Agent 必须 tools-v1。`kernelmodel.RelayModel` 只支持 text-v1，复用原 `kernel.Relay.Forward`；它要求可信安装方提供原 Key/Profile/Ticket/Plan 的 Prepare 和唯一账本 Usage 读取器，缺任一项返回 dependency_unavailable。它没有独立供应商客户端、URL 配置或第二份结算。已有严格文本归一化没有放宽或丢弃 tool_calls。真实 tools-v1 adapter/profile 未批准时，生产 Agent 继续明确不可用。

取消、审批和恢复
----------------

取消先持久化 `run.cancel_requested`，执行者每 25ms 检查并取消当前模型/工具的 context；模型/工具实际返回后才写 cancelled 或失败。queued/waiting_approval 可在未执行时取消。工具适配必须响应 context；不能用脱离管理的 goroutine 伪造超时完成。本服务不释放 ledger slot、不退款、不解除 held；这些仍由原内核根据可信终止证据处理。

审批哈希绑定协议、session/run、owner/auth revision、call ID、工具版本与参数。重复、过期、权限改变、哈希不匹配均冲突；拒绝结束 run。批准后再次执行原调用；并不重新请求模型生成参数。工具版本改变使旧批准无效。

恢复必须由可信宿主先确认旧进程停止，再调用 `Recover`，不能由浏览器报告“断线”触发。ready/tools 边界可以重新排队；model_inflight/tool_inflight 进入 needs_confirmation，保留原 request/call 身份，旧 executor 被隔离，迟到写入被拒绝。不确定 write 错误也进入 needs_confirmation，不自动重放。当前没有通用的“确认未知写入成功/失败”公开 API；须由后续经过工具专用证据与原账本查询的协调器接入，不能用一个 bool 解锁未知执行。needs_confirmation 会继续占用会话活动位。

候选 HTTP 协议
--------------

`Handler` 需要宿主提供 Authenticator，写请求必须验证当前登录、Origin/CSRF；body 严格拒绝额外字段。owner、权限、币种和限值均不由浏览器设置。Host.Resolve 在执行/审批续跑前重新验证当前授权；每个真实模型子请求继续走原 Key 撤销/限额检查。工具若依赖可变外部授权，也必须在 Execute 中核验当前权限。

| 方法与路径（前缀 `/api/agent/v1`） | 行为 |
| --- | --- |
| POST /sessions `{title}` | 201 Session |
| GET /sessions | 200 `{items}`，仅当前 owner |
| GET /sessions/{sid} | Session/消息/运行持久历史 |
| PATCH /sessions/{sid} `{title}` | 重命名，204 |
| DELETE /sessions/{sid} | 无活动 run 时软删除，204 |
| POST /sessions/{sid}/runs | Submit，202 Run |
| GET /sessions/{sid}/runs/{rid} | 查询运行/步骤/子 request/用量 |
| POST /sessions/{sid}/runs/{rid}/cancel | 202 cancel_requested |
| POST /sessions/{sid}/runs/{rid}/approvals | `{call_id,sha256,allow}`，202 |
| GET /sessions/{sid}/runs/{rid}/events?after=N | JSON `{items,next_cursor}` 或 Accept: text/event-stream |

提交例子（受控能力，不能直接用作生产来源配置）：

```json
{"client_id":"send-1","text":"6乘7并列出我可见的模型","mode":"agent","model":{"alias":"demo","source_id":"controlled-local","revision":"1","protocol":"tools-v1"}}
```

事件使用会话内单调 cursor，run 过滤后允许有间隔。每次最多 200 条，先持久化后发送。SSE 为有界回放快照，读完关闭；客户端以 Last-Event-ID 或 after 继续订阅，不因断线重新 POST。所有 GET 都不执行模型/工具。事件种类为 run.queued/started/cancel_requested/completed/failed/cancelled/limit_reached/recovered/needs_confirmation、step.started/finished、message.delta/completed、tool.call/started/result、approval.needed/resolved、usage。失败文本是规范化原因，不回显上游错误或凭证。

Handler.Dispatch 接 Host.Schedule；没有 Dispatcher 的嵌入式调用只入持久队列，由宿主显式调度。宿主关闭调用 Host.Close 等待全部执行结束。新进程可枚举已授权会话并调度 queued，running 先按前述规则恢复。生产二进制暂未注册候选路径，待 MAAS-2 核定后沿已有管理身份装配，避免并发修改 MAAS-3 安装组合根。

开发和验证
----------

```powershell
./scripts/test-agent-runtime.ps1
# 或分别运行：
go test ./internal/agentruntime/... -count=1
go vet ./internal/agentruntime/...
go run -tags agentcontrolled ./cmd/agent-headless --state-dir .cache/agent-demo
```

headless 被 `agentcontrolled` build tag 隔离，普通生产构建不包含测试模型。它实际执行两个安全工具，落盘消息/检查点/完整事件并打印 JSONL；模型选择和最终回答来自可见的确定性受控模型。LocalStore 是单进程开发存储，以 fsync 后不可变版本发布，持有目录独占锁；崩溃后锁不自动抢占，必须核实 `.owner-lock` 中的 PID 已停止后才能删除该确切锁文件。操作系统掉电持久保证尚未验证，不能替代生产 MySQL。

`internal/kernel/agent_runtime_mysql_test.go` 在原 disposable MySQL fixture 上调用真实 Admit/Finalize 和 MySQLSessionStore，验证两子请求、重复终态、重复提交/事件读取、旧 revision 冲突及两次唯一消费；模型和网关证据生产者仍是替身。运行需已获准临时 MySQL，设置原 `MAAS_DISPOSABLE_MYSQL=1` 与 `MAAS_MYSQL_TEST_SOCKET`，随后 `go test ./internal/kernel -run '^TestMySQLAgentChildrenUseOneLedger$' -count=1 -v`。没有环境时该测试明确 skip，不能报告 SQL 通过。

交接：MAAS-2 审定候选协议/ADR及工具能力批准；MAAS-5 消费事件/审批/停止与编辑关联；MAAS-7 独立验收本候选差异；MAAS-8 核 MySQL 身份/迁移及宿主装配；MAAS-17 统一基线 PR 集成。真实来源调用和完整 H1–H4 仍沿 MAAS-18，生产 tools-v1、正式 HTTP 身份接线、未知结果协调器和真实 MySQL复验分别记录，不以受控模型/文件测试代替。
