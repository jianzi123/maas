# Chat与Agent Runtime最小共享契约 AR-1

状态：供MAAS-20/5立即实施的1.0.0-draft.1；原后端实现核心、原前端接Chat、MAAS-7独立验收。架构交付不代替这些产品实现。基线8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a，统一PR目标agent/MAAS-10-offline-metrics；后续增量跟随最新基线，保全现有工作。

## ADR与锁版依据

参考官方DeepSeek Harness提交2e39e70496aa02986ca6a820c5d497e816b69d7e，根package版本0.2.2-rc.5。本包reference保存架构、包索引、package.json及MIT LICENSE的原件/摘要。官方设计以Cordis服务/事件/可撤销注册组合session、tools、model adapter与loop；这是可替换边界的参考，不是本平台已接入或稳定兼容结论。[固定官方架构](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/docs/architecture.md)

| 选择 | 可直接复用与本项目新增工作 | 本轮决定 |
|---|---|---|
| 原生Go接口与显式Registry | 复用现有身份/事务/Key/模型网关；新增小型Loop、会话事件和检查点；进程内可替换接口，注册随版本冻结，无动态代码安装 | 采用；最少部署组件，成本尚未计时，不宣称性能更优 |
| 锁版DSH适配/sidecar | 可复用其循环/工具组合思路及实现；仍需MaaS ModelClient、会话授权/审批、持久幂等与预算对接；新增Node、profile/IPC/生命周期和供应链维护 | 保留adapter边界，首期不引入。锁版package声明Node>=24.9.0、pnpm11.28.5，不把本机环境当满足；未安装/执行DSH或测适配成本 |

不照搬第二份会话/计量真源。未来DSH仅实现下列接口，模型出口仍只能调用MaaS私有ModelClient，禁直接持有供应商凭证绕过Go/Higress。无跨网关/引擎重选依赖。

## 版本与最小接口

新增应用命名空间 /api/agent/v1，事件ar.session.event/1.0；使用现有受保护登录会话与CSRF/Origin约束。平台推理Key不自动取得会话/审批权限；运行凭证在后端受限存储/句柄，客户端不写Secret。公开路径/字段统一sessions/session_id；领域Conversation就是持久Session，两个命名不得产生两套实体。新端点未装配时UI显示不可用，不能静默退回夹具。

OpenAPI文件单独提供，不覆盖原/api/admin/v1/session（登录）或/v1/chat/completions。原严格ChatChunk/Message仅role/content且finish=stop/length；internal/kernel/public_response.go:normalizeChunk/normalizeResponse明确拒绝未知delta字段、tool_calls和工具finish。**旧接口继续拒绝工具协议，不能删除tool_calls后假装成功。**

ModelClient有两条显式路径：TextV1使用现有text-v1；ToolsV1要求批准tools-v1能力和adapter修订，支持assistant tool_calls、tool role结果及finish=tool_calls。二者使用同一私有网关、准入/预算/slot/请求/唯一结算。ToolsV1需后端在原relay中加独立版本化归一化分支/validator，不放宽旧分支，不用供应商SDK旁路。每个子请求冻结protocol_revision、capability_revision、源/模型/模式、profile/price/publication/epoch和入参/工具schema摘要；公开用户不能自报这些可信字段。真实工具模型能力未批准返回422 capability_unsupported且零模型调用；受控模型明确标source=controlled。

新应用API的工具提案事件不是旧ChatChunk；UI只显示后端验证后的结构化提案，不消费碎片化参数。首期n=1，text-only，不引入文件上传、MCP、shell、子Agent可执行按钮。JSON工具参数必须由固定Schema验证，来源发出结束及完整参数、子请求唯一终态得到确认后才可执行工具；半截JSON、流式片段或diagnostic_only不能成为工具执行授权。

## 领域与存储不变量

| 实体 | 最小事实与约束 |
|---|---|
| Conversation | UUID、owner、title、revision、model_alias、created/updated、deleted_at；所有读写先验证当前principal/owner。单管理员不是免授权理由 |
| Message | UUID、conversation、单调position、role、typed parts、status、run关联、supersedes_message_id；partial不是完成答复。消息/事件不存秘密，保留策略单独批准 |
| Run | UUID、conversation、client_operation_id、请求hash、mode(chat/agent)、状态、输入head、冻结context/policy/模型选择、累计限制和cancel_requested、lease/fence。父run的用量仅派生，不重复扣业务额度 |
| Step | run+递增index、唯一model_call_id、child request_id、协议/来源快照、输入/输出摘要、状态。一个Step一个模型子请求，之后可有多个工具；首期工具按提案顺序串行 |
| ToolCall | run/step/call_id、tool名/版本/schema摘要、规范参数/摘要、effect、授权scope、批准状态、执行状态、幂等键、attempt、结果/错误摘要；同一source call ID异参数拒绝，不改旧记录 |
| Event | run内全序seq十进制字符串、event UUID、version、time、run关联、严格type/data；消息/状态/检查点和事件在同一MySQL事务提交，提交后才广播 |
| Checkpoint | run、revision、last_event_seq、last_completed_step、message head、冻结context/tool registry/policy引用、未决child/call身份、fence；不能只存一个“下一步index”就重启执行 |

建议新应用域迁移独立编号/目录，由MAAS-20维护，不修改旧迁移。不将CR或Redis作为会话日志真源。checkpoint不复制Secret/供应商原body。日志归档/删除不改核心请求/账务记录，未知调用证据的保留按原安全门槛。

## 同会话并发、编辑与HTTP未知

每conversation最多一个非终态Run，包含waiting_approval和needs_confirmation。通过锁conversation行+active_run_id CAS/唯一约束实现；首期不排队，竞争提交409 conversation_busy；不同会话并行仍受全局预算/slot限制。运行中可保存本地草稿，不能改/删服务端上下文；rename可带If-Match，模型选择变更只对下个Run生效。

提交消息并建Run是一个事务，必带client_operation_id UUID和If-Match conversation revision。命令幂等按(principal,conversation,operation_id)唯一，保存规范请求hash；完全相同重试返回原Run，异hash409 operation_conflict。已有命令匹配先返回原结果，再处理过时If-Match，不因此新建第二个Run；权限仍先核验。创建conversation同样必带操作ID。幂等记录/墓碑覆盖会话命令可恢复期，未批准保留策略不自动清理；ID已回收不能默默作为新命令复用。

新接口允许只重发同一已定义幂等命令以找原Run，UI自动策略优先GET /sessions/{id}/commands/{operation_id}，未知显示待确认，不换ID生成。查询无记录/404不证明从未执行，冲突/保留期不触发重放。旧管理写入、Key创建和模型生成接口不因此获得重试授权。

编辑/重新生成通过提交Run的operation=edit/regenerate，referenced_message_id与当前revision绑定：edit追加新user消息并supersedes原消息；regenerate从原assistant之前的历史head创建新Run/新消息，保留原消息与原消费。旧事件不可覆盖。若引用属于其他会话、不是当前可分支head或有活跃Run，409/404。首期线性可见分支，不新增分支编辑器；原账务不退款。Run接受时冻结选定历史与工具清单，禁止运行中把编辑插入已有context。

## 可替换核心与执行规则

接口由MAAS-20在同一产品内实现：ModelClient.TextV1/ToolsV1；AgentLoop.Run/Cancel/Recover；ToolRegistry.Resolve(name,revision,scope)；SessionStore.AcceptCommand/AppendEvents/Checkpoint/ClaimLease；Policy.Authorize/Approve。接口参数必须含caller scope、run/step/call身份、fence和context cancellation。ModelClient返回流事件和原child request_id，失败必须保留该ID及是否结果未知；不能只返回一串文本丢失账务关联。

循环：事务接受消息/Run → 认领lease/fence → 检查策略/remaining cap → 创建Step与稳定model_call_id → 单次模型请求 → 持久partial消息事件 → 核对完整结束与子终态 → Chat直接结束/Agent生成工具提案 → 校验/授权/必要批准 → 持久dispatch意图 → 真实工具 → 结果/checkpoint同事务 → 下一模型步或最终答复。工具空转/连续同参数同结果达到显式no_progress_limit时limit_reached；禁止隐藏无限循环。受控模型可选择工具但标签不代表真实来源批准。

每次认领都递增fence。所有事件/状态/工具dispatch CAS当前fence，旧owner不能写入或发送新的模型/工具调用。lease过期后不能立即重复dispatch未知在途操作；先按原身份核对。

## 限额、预算、上下文

Run提交必须显式max_steps、max_model_calls、max_tool_calls、max_duration_ms、max_tokens、max_money_atomic+currency、tool_timeout_ms、max_tool_output_bytes、max_context_tokens、no_progress_limit。应用cap不是平台Key预算替代；用户要求只能缩小服务端批准上限，无隐式生产默认。纯Chat也按一次模型调用限制，不能借agent模式绕过。

父Run只读聚合子请求的known/inflight/held，Token/金额与币种/价表分组，不加总不同币种。下一子请求前必须用可信上界检查run剩余cap，再经原Key三维预算唯一预留/结算；未知held算占用不能用available/actual=0绕过。首期单Run模型串行，调度侧以run行锁序列化已分配的子请求上界，作为执行cap台账而非第二财务账本；和child request_id强关联，COMMIT未知先回查，不能再扣一次。parent完成/取消只聚合，不产生新的usage debit/refund。

上下文首期采用明确拒绝策略：固定system+选定线性消息+工具结果在批准context cap内才发送；不偷偷截断原历史、丢tool/result或自动摘要调用。超界返回context_limit/limit_reached，无新子请求。摘要/压缩以后需版本化并计费，checkpoint记context strategy revision。

工具Schema、规范参数/结果、system模板和工具role包装均纳入该子请求的计费输入上界；不能只数用户可见text。新增protocol_revision保存在不可变批准profile/子请求快照，通过现有body摘要及能力/配置绑定被覆盖，不向封闭票据v3或终态3.0擅自加字段。若现有绑定不能覆盖新ToolsV1语义，则该来源保持不支持，先给最小版本差异再实施。

## 工具与批准

首期至少两个真实安全实现：bounded_arithmetic（只处理白名单数值运算，有限长度/精度/耗时，不eval代码）；list_visible_models（用调用者当前scope读取已批准目录，不读取凭证、不扩大namespace）。可替换只读用量工具须保留当前用户范围。注册Manifest固定name/revision、JSON Schema、effect(pure/read_only/idempotent_write/non_idempotent)、required_scope、requires_approval、超时/输出上限及幂等保证；参数和结果都Schema校验，模型给的tool名只是请求。

授权在提案、批准及dispatch前重新核验；工具输出视为不可信数据，不拼进system role；错误经脱敏成为tool result或按批准策略终止，不能把错误字符串当成功。首期纯/只读可由预批准策略放行；超出注册清单拒绝，不自动安装工具或执行shell。

approval绑定run/step/call、tool revision、canonical args SHA256、policy revision、scope/principal、expiry；不能用“同意任意工具”替代。只有具备approve scope的同授权域用户可提交allow/deny，decision_id幂等；异decision冲突409。运行取消、参数/策略/工具变化或过期后旧批准无效。批准事务+pending→dispatching CAS需重新检查有效期和fence，审批不直接执行。deny使run failed(approval_denied)，过期保持waiting_approval/要求新批准或到总时限limit_reached，不自动允许。

副作用工具是扩展口，首期不注册。先提交稳定call_id/幂等键/dispatch意图再发请求；返回丢失→unknown，Run needs_confirmation，不自动重放非幂等操作。纯/只读仅在原调用确认无外部副作用且策略准许时，用同call_id、新attempt恢复；幂等写必须有适配器服务端原键查回/去重证据。人工核对不新增默认“标记成功”API；确认来源经原受控管理员流程给审计证据。

## 状态、取消与重启

Run: accepted→running→waiting_approval→running；需要查证时needs_confirmation；唯一终态completed/failed/cancelled/limit_reached。cancel_requested是独立事实，POST cancel返回202仅受理。取消幂等，即使UI断开也持续持久记录，停止当前child/工具并禁止新步骤，失效pending批准。模型停止沿原A08动作要求，slot/未知held独立；总Run期限覆盖等待批准/恢复时间，不因重启延长。

lease接管从checkpoint重建并对未决child查原request_id、未决工具查原call_id。无child/dispatch意图才可按稳定新step身份继续；建档/发送ACK未知进入needs_confirmation，不能换ID调用。completed step/tool结果重放仅重建投影，不重复执行。父run cancelled须已确认各child原终态/工具结果或明确安全可结束，未知副作用仍保持needs_confirmation；已有模型cancelled终态且财务held的Run可结束，held继续核心管理。不能等价声称外部引擎已停止或费用已停止。

Conversation DELETE要求无活跃/未决Run，返回204逻辑删除；不删除核心账务。Run完成后消息/usage/terminal event和checkpoint原子可见；之后流写失败仅影响传输不重写终态。服务重启不自动恢复过期审批/注册失效工具。

## 事件、cursor与恢复

按run分配十进制seq（不转JS Number），事件id为UUID，type/data严格版本化。Envelope包含seq和不透明cursor；SSE event=type、id=Envelope.cursor、data=Envelope；GET只读取已提交事件，不执行模型/工具。会话鉴权每次重连/分页核验。cursor绑定owner scope、session_id、run_id、事件版本、seq及保留代际，完整性保护；篡改/跨会话400，权限变化403/不可见404。

Last-Event-ID和after只能提供一种，冲突400。每次订阅先恢复after之后的持久事件再跟随；至少一次传送，UI按event UUID/seq去重，乱序先回查缺口，不能再次提交消息。每条delta有message_id/offset/text，offset是UTF-8字节偏移、文本按完整Unicode持久分批，重复offset不得重新追加。partial来源不可伪装committed完成；message.committed给完整文本/摘要和revision。

保留期缺口返回410 cursor_expired和snapshot_required=true。GET session snapshot返回revision、event_run_id、last_event_seq和同事务消息/Run快照（默认活跃Run，否则最近Run；无Run则水位0、cursor=null）；GET Run也返回该Run的last_event_seq/resume_cursor，随后从该水位订阅，避免snapshot/重连丢事件；不能凭空把snapshot水位当cursor，服务器返回对应恢复cursor。慢客户端达到输出界限关闭流，可GET恢复，不能用删事件/重新运行生成解决。heartbeat无持久seq、不作业务完成/用量证据。未知事件主版本停止消费、读快照并显示升级需求。

## API与错误实施表

本包OpenAPI具体列出conversation创建/列表/读取/改名/删除，messages分页，Run接受/读取/cancel、原operation查回、事件重放及SSE、approval决策、checkpoint只读、capabilities查询。GET响应带固定协议版本；写要求会话+CSRF、client_operation_id或decision_id及适用If-Match，返回ETag。list按created_at/UUID稳定游标，max100；messages按position升序，events按seq升序。

400结构/Schema/cursor；401无会话；403越权/审批；404不可见实体；409 revision/active_run/幂等冲突；410 cursor/命令保留期；422模式/工具能力不支持；429平台预算/并发/速率按原维度错误；503存储/原终态/批准依赖不可确认。Error包含code/message/http_request_id、可空run_id/child_request_id及retryable；HTTP request_id是本次读写Q，child ID是原模型R，不互换。retryable不授权自动重放模型/工具。新应用错误不塞进旧终态3.0枚举。

## 同版本验收与分工

| 原角色 | 立即实施切面 | 本轮关闭需证据 |
|---|---|---|
| MAAS-20后端 | 新应用迁移/接口/Loop、两个真实工具、受控ModelClient；ToolsV1能力分支复用原网关内核 | headless多步与HTTP/SQL：每child仅一条核心终态，父聚合0新扣量；并发/崩溃/未知不重放 |
| MAAS-5前端 | Chat列表/历史/Markdown代码、模型/多轮/编辑regenerate/停止、Agent步骤/审批/工具/错误与恢复 | 刷新/重连/跨会话迟到、审批重复/取消、非空/未知usage，Markdown消毒且代码只显示不执行 |
| MAAS-7/8/17 | 独立协议/权限/恢复测试、同版本部署/来源锁、集成审查 | 明确controlled/真实来源和组件；MAAS-18真实底层闭环仍单独验收 |

契约样例包含普通Chat、工具循环、审批、取消、进程恢复、重复/错会话事件、旧文本tool_calls拒绝和错误；静态校验只证明形状/约束，不声称产品运行通过。原后端已有活动运行，沿同一任务接续，不新建重复内核。若实现字段已有草案差异，按本版版本/不变量合并回MAAS-2，不让互等整单。


## 与本轮前后端反馈的最终对齐

本版已读取MAAS-20评论01a1f1dc-439a-7380-899d-21e70f901f12及前端01a1f1df-abe0-7986-8958-f95b2549d41d。采用原后端建议的/api/agent/v1/sessions、text-v1/tools-v1、needs_confirmation及单Run单调cursor；普通Chat与Agent仍共用此Session核心。事件JSON字段统一session_id/run_id/seq/cursor，GET /sessions/{session_id}/runs/{run_id}/events及/events/stream共用Envelope。会话历史按Message.position排序，不把不同Run的seq相加。

Run.aggregation_complete只说明usage聚合输入是否完整；为false时已知数是小计。Run完成不意味着所有金额已知，null/held沿子账本保留。权限冲突409 conversation_busy可在Error.run_id返回当前主体可见的活跃Run，不能泄露其他主体。client_operation_id放body；规范请求hash使用服务端固定JSON canonical版本、拒绝重复键，绑定mode/操作/选定消息/模型/限制/工具清单；规范化不改写用户文本。重复同key从持久command映射原Run，HTTP未知恢复优先只读GET。

命令/审批/模型子请求/工具call/事件UUID是不同域，互不充当授权证明。未知工具执行的needs_confirmation与等待人工批准waiting_approval不同；本版没有允许“批准重跑未知副作用”的API。用户当前scope每次复查，首次两个工具不要求开放外部执行能力。

RunAccepted.input_message是本次执行的有效输入消息；regenerate可引用既有输入，新assistant消息通过本Run的消息事件/快照产生，不复制旧消费。Run GET用于状态与恢复水位；steps及tool-calls另有同Run只读分页，刷新后能读取完整提案/结果与状态，不能仅靠浏览器缓存。Approval展示规范参数与其真实摘要，不用摘要占位代替可审核输入。RunLimits.max_tool_calls可显式为0（Chat自然不执行工具），其他生产限制仍由安装策略批准。

message.created必须先于该assistant消息首个delta持久提交，初态partial，不能向既有committed user消息追加模型输出。offset按原message独立累计；message.committed提供完整投影，不由delta齐全自行推断模型或账务完成。

本轮复现：在交付包解压根目录、已有Python和jsonschema 4.26.0/openapi-spec-validator 0.7.2依赖时，执行python build_agent_contract.py和python validate_agent_contract.py；验证器沿原工作区.contract-tools-v04优先读依赖。需将准确产品基线仓库放在maas子目录（源文件摘要随verification.json），或在原工作区直接执行。align_agent_contract.py是本次编辑迁移记录，复现不需重跑。reference文件从固定commit只读获取，无DSH依赖安装/执行。

静态输出计数以verification.json为准：其中SSE与JSON包络一致性和旧纯文本拒绝工具有直接断言。另12项semantic_negative_cases是供MAAS-20/7落地的语义/故障矩阵，未当作HTTP、数据库或循环运行证据。原有产品源码保持干净、共享Schema不覆盖；当前真实工具能力批准/受保护模型闭环仍按MAAS-18门槛。
