# Chat 工作台：可交互开发阶段

本轮沿 MAAS-5 增加独立 Chat 工作台，原模型/Key/试用/发布/用量页保留。界面支持会话列表、新建/重命名/删除、多轮消息、模型选择、流式 Markdown/代码块、停止、错误/未知用量、刷新历史恢复、只读事件重连；编辑和重新生成会建立关联原消息的新运行，旧消息与运行保留。

## 预览与操作

在 console/ 执行 npm ci、npm run dev:fixtures，登录后的侧栏选择“Chat 工作台”。新建会话后发送消息，切换普通 Chat / Agent；Agent 演示纯计算 text_length 工具，界面显示步骤、输入、结果和批准/拒绝。发送 /error 模拟失败。浏览器刷新后按 URL 中非秘密会话 ID 恢复，断开/重连只读事件，不重新启动运行。

开发模式仅使用浏览器本地存储（maas.chat.development.v1），内容和事件可通过“清空开发会话数据”删除。没有持久化平台 Key、管理员 cookie/CSRF或上游凭证；Chat页面也不接收这些凭证。开发适配未执行真实模型或后端工具，不代表生产持久化或跨用户隔离。请勿输入敏感信息。两个浏览器/不同origin之间不共享历史；其并发/存储额度也不作真实服务保证。

普通真实服务模式当前显示“会话/运行服务正在接线”，不发出虚构的HTTP请求，不回退本地开发数据。现有在线试用及管理接口继续可用。没有新增不可用的文件上传按钮。

## 可替换接点（待MAAS-2/20批准，不是稳定HTTP协议）

src/chat/types.ts 的 ChatService 是UI内部开发port：models/list/create/rename/remove/read/start/events/cancel/approve/clear。页面接受 service 注入，开发模式显式装配 DevelopmentChat；尚未指定生产API路径。

最小需要收敛的字段：

- Session.id/title/updatedAt/messages/runs，由服务端核验当前主体所有权。客户端不能因已知ID跨用户读写。
- Message.id/role/content/runId/requestId/replaces/createdAt；消息修订与重生成保持原关联和消费记录。
- Run.id/commandId/model/mode/state/assistantId/cursor/steps/usage；commandId用于原写入恢复，不等于推理request_id或结算事件。
- events(sessionId,runId,after)返回有序seq和同session/run快照，游标去重；恢复是读取既有事件，不启动模型/工具。
- 工具批准绑定session/run/callId和原输入；真实版本还需由共享契约提供输入摘要/批准令牌/时效和权限。UI不制造授权。
- 当前内部usage.tokens=null明确为未知，不是余额或第二套账本。父run/每个子request的完整权威用量字段由真实服务契约提供，不能由前端自行累加财务结果。

本port字段是页面和开发适配的候选输入。真实Go会话/运行API、事件版本、取消ACK/停止事实、幂等查询、审批证明、消息分支与分页等以MAAS-2审定、MAAS-20实际实现为准；没有把旧严格Chat Completions纯文本消费者当作tool_calls协议。

## 安全与未知结果

Markdown使用marked解析、DOMPurify净化，禁止图片/表单/iframe/script等活动内容；工具输入/结果用Vue文本pre展示，工具结果不成为系统指令。代码块只显示，不执行。会话切换/卸载使旧事件回调失效；UI模型能力来自适配器，发送前检查运行模式。等待/运行中的同一会话拒绝并发发送，未完成运行不能删除。未知提交结果锁住重放，显式原会话重读只在匹配commandId时恢复。

开发工具批准只消费一次；真实鉴权、工具Schema、幂等与取消/账务边界仍由后端负责。停止UI不会宣称引擎停止、退款或slot释放。

## 验证与下一步

定向：node node_modules/vitest/vitest.mjs run src/chat-development.test.ts src/chat-workspace.test.ts
浏览器：node scripts/chat-browser.mjs
构建/回归：npm test；npm run build；npm run format:check。
artifacts/chat/包含结果及桌面、移动、等待批准截图；均为明确标注的浏览器本地开发适配。

下一步由MAAS-2/20收敛上述最小字段/版本和运行端点后，替换port并用同一浏览器流程验证真实受控服务的持久化、跨用户权限、取消/审批和ACK恢复。本轮不改Go/DDL/模型网关或唯一账本，不以开发模型替代MAAS-18真实调用闭环，不执行真实供应商、目标部署或付费资源。
