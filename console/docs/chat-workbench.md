# Chat 工作台与 AR-1 服务接线

沿 MAAS-5 / PR #17 的现有 Vue 页面及 ChatService 接入 AR-1 / 1.0.0-draft.2。模型、Key、发布、在线试用和管理用量继续保留；不另建页面或计量账本。

## 实际接入与启动

先在后端 PR #18 固定提交 19e43ba980f1bd9f499a92dda435b74b626bf7e9 启动原受控服务：

    go run -tags agentcontrolled ./cmd/agent-headless --state-dir .cache/ar1-http --owner-id 4c421973-919f-4b8a-997f-909fc6fd010a --listen 127.0.0.1:4188

在本前端 console 目录：

    npm ci
    $env:MAAS_LOCAL_AGENT_API = "http://127.0.0.1:4188"
    npm run dev

Vite 只绑定 loopback。开发桥直接代理该 Go 服务的 /__maas/local-session 与 /api/agent/v1，先校验浏览器同源 Host/Origin，再转到 Go 配置的精确 Origin；Cookie 由原 Go LocalSession 签发，CSRF 只保存在当前页面内存。不能同时设置 MAAS_LOCAL_API 来拼接另一服务的同名 Cookie。该独立受控入口只启用 Chat 导航；完整管理导航仍保留在原统一工作台装配中。

模型目录来自 capabilities，demo 明确标为受控模型。受控启动使用后端文档的 TST / 100 Token / 100 原子金额、4步、4模型调用、8工具调用、10秒等测试上限；普通 Chat 固定一次模型调用。这些不是生产默认或批准额度。

生产构建只有显式 VITE_CHAT_AR1_ENABLED=true 且 VITE_CHAT_AR1_CONFIG 提供 JSON 对象 {limits, tools:[{name,revision}]} 时才装配 HTTPChat；限制遵循锁定 RunLimits，并由 Go 与安装策略取交集。没有有效配置或 capability 时显示具体错误、不启用生成，也不回退开发数据。生产登录沿原 api.session/login/logout；模型/来源批准、生产 Auth/Catalog/Reauthorize/Prepare/Usage/最窄 SQL 身份仍须由原后端/运维装配。生产 tools-v1 缺批准时保持拒绝。

## 行为和恢复边界

- Session 创建/重命名/删除、多轮、edit/regenerate 和消息关联消费正式 DTO。写入带原 Cookie、CSRF，修改/运行提交带快照 revision 的 If-Match。重新生成发送 operation=regenerate、text=null 及原 assistant ID。
- 首建与发送前只在 sessionStorage 记录非秘密原 operation UUID、请求规范 SHA256 和必要 session ID，不保存正文、平台 Key、Cookie 或 CSRF。响应未知后先 GET 原创建命令或会话内命令，核对 operation/hash/归属；404/503 不证明未执行，不自动 POST。刷新恢复原命令和 URL 会话，不按标题猜。
- 原 Go 快照提供 revision、event_run_id、last_event_seq、resume_cursor 一致水位。历史消息与 steps/tool-calls 按不透明 cursor 读取全部分页；有界读取超限明确报错，不把一页冒充全量。后端快照目前最多保留100个 Run 投影，前端不补造更早 Run 的账务；消息历史仍按 messages 分页读取。
- SSE 使用 /events/stream?after=原不透明cursor，不同时发送 Last-Event-ID。严格校验 AR 事件 Schema、session/run/单调连续十进制 seq、SSE id/event 与 envelope，并按 UTF-8 字节校验 delta.offset。页面更新采用服务端持久快照，避免重复拼接；410 只 GET 新快照。断流/EOF 不推断成功，不触发新 Run。
- accepted/running/waiting_approval/needs_confirmation 都阻止同会话并发发送。停止 ACK 仅表示取消已请求，UI 等待实际终止；needs_confirmation 无“批准重跑”入口。会话切换、断开和卸载隔离旧事件，旧列表完成也不能中断新会话事件连接。
- 审批从已持久事件发现 approval_id，再 GET 原 Approval；展示规范参数、摘要、工具版本、期限，决策携带新的 decision_id、原参数哈希/工具/策略版本。未知决策不自动重试；权限、期限与最终执行由 Go 重核。工具结果一律按文本显示，Markdown 净化，不执行代码。
- 父 Run 显示原 child_request_ids 及权威 usage_groups，按 currency/price_version 展示 known/inflight/held。所有数值保留十进制字符串；空分组显示未知，aggregation_complete 与执行终态分别显示，不合并币种、不补零、不重复扣量。

## 开发适配

npm run dev:fixtures 仍显式使用 DevelopmentChat；会话与历史只存在 maas.chat.development.v1 浏览器本地数据中，可以清空。它没有 Go 存储、真实工具权限或供应商调用证据。HTTP 模式不读取或写入这份开发历史。没有新增无后端能力的附件按钮。

## 可复现验证

    npm test
    npm run build
    npm run format:check
    npm run types:ar1
    npm run test:chat-ar1

test:chat-ar1 默认后端目录为 ../../ar1-backend，或显式 MAAS_AR1_BACKEND_ROOT。先验证完整 Git SHA，再构建受控入口。需本机 Go 1.26.0、Edge、已获准的本地依赖。脚本依次运行原入口和明确的浏览器测试适配，两组覆盖重叠，不相加为独立场景数：

1. official：原 agentcontrolled 入口、真实 LocalSession/HTTP/LocalStore/Host/安全工具；验证持久历史、原命令 ACK 丢失恢复、编辑/再生成、原 R 用量、匿名/错误 CSRF、窄屏和删除。
2. extended：相同固定 AR-1 核心和原安全工具，只替换测试 ModelClient（慢流、已确认失败、OutcomeUnknown），并对计算工具显式增加批准要求、为测试可信主体加入 tools.approve。验证审批刷新/决策、中文/emoji 字节流、只读重连、停止终态、未知结果屏障与未知用量。该适配不是原默认模型行为或生产授权。

结果、无凭证网络轨迹、持久快照/JSON事件/SSE、截图和自有 PID/端口清理记录在 artifacts/chat-ar1。Windows 非控制台子进程无法可移植发送 SIGINT，原未改入口仅通过自有子进程句柄结束，原状态目录保留、不抢占其锁；扩展测试入口添加 stdin stop 生命周期钩子，等待 Go Host/HTTP 正常关闭。每轮使用独有状态目录，确认4188/4189监听已关闭，不留常驻服务。

本前端作者联调使用真实 Go 文件存储，不是浏览器本地开发适配；模型/计价/上下文计数为明确受控适配，工具/HTTP/存储是真实现。未执行真实供应商、生产 Higress/Secret、目标集群、真实 SQL 浏览器组合、完整跨用户主体矩阵或独立 QA；MAAS-18 底层真实闭环和 MAAS-7 验收继续单列。后端原真实 MySQL 作者结果不计入本前端测试。

contracts/ar1-openapi.json 与 ar1-session-event.schema.json 从固定后端原字节复制，.gitattributes 禁止换行转换；类型由 generate-ar1-types.mjs 生成，校验采用原 Schema。提交按产品代码→标准 lock-unified-source.py→四锁独立提交，组合装配后的来源锁由原集成流程重算。
