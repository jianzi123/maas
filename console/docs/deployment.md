# 正式静态控制台部署接点

本目录复用既有 Vue 控制台和 AR-1 消费者，不包含独立业务数据库、第二登录服务或模型代理。正式 MySQL/API 由 MAAS-20 实现，Compose/原生 YAML 与最终组合由 MAAS-21/MAAS-8 交付。

## 同一构建用于两个安装包

在仓库根执行 `npm ci --prefix console`、`npm run build --prefix console`，产物是 `console/dist`。已有镜像入口是 `deploy/images/Dockerfile.console`，已有静态服务器是 `deploy/console-server` / `internal/webconsole/handler.go`（监听8080、`/healthz`/`/readyz`）；本增量不改该部署层。最终包可由同一正式 Go 进程托管 dist，也可通过同源反向代理分发静态资源/API，需以包内实际装配说明为准。无需 Vite、开发机绝对路径或另一个 agent 的 worktree。

静态根目录必须提供 `/console-config.json`，响应为 application/json；默认构建附带显式关闭 Chat 的配置：

```json
{"schema_version":"maas.console/1","chat":{"enabled":false}}
```

开启 Chat 时挂载同版本 JSON，字段为 `chat.enabled=true`、`chat.limits`（原严格 RunLimits）和 `chat.tools=[{name,revision}]`。`console/examples/console-config.controlled.json` 是 **TST合成预算的受控样例**，不是生产预算或真实模型批准；正式安装必须使用服务端安装策略对应的已确认限制/币种和获准工具版本。普通 Chat 自动请求 max_model_calls=1；Go 仍取安装策略交集并唯一准入/结算。工具版本不符合 capabilities 时不发送 Agent 请求。

Compose 可将实际配置文件只读挂载到 `/app/dist/console-config.json`；K8s 可用 ConfigMap 单文件挂载到同一路径。若使用 subPath，更新 ConfigMap 后滚动重建 Pod；配置变更后刷新浏览器。不要把配置中的预算当作可调宽服务端策略的权限。生产不再消费 `VITE_CHAT_AR1_ENABLED/CONFIG`；这些仅保留给显式 DEV 验证。`MAAS_LOCAL_AGENT_API`/`MAAS_LOCAL_API` 仅属于开发桥，不能作为容器运行配置。

公开配置不能包含 Secret、平台 Key、上游 URL、MySQL DSN、密码、Cookie 或 CSRF；额外字段被拒绝。API 路径固定为同源，不允许 JSON 选择另一来源。文件缺失、非JSON、字段错误或限制无效时显示部署配置错误，登录前也会重核，不自动回退浏览器本地/文件会话。关闭 Chat 不关闭其他管理页；开启配置不是后端健康证明。

## API、身份与 SSE

浏览器的 `/api/admin/v1/*`、`/api/agent/v1/*`、`/v1/*` 必须沿最终包路由到同一正式 Go 服务。不能把两个独立服务的同名 Cookie 拼起来。管理登录/恢复/退出为 POST/GET/DELETE `/api/admin/v1/session`；原响应的 csrf_token 仅保存在页面内存。写操作携带 X-CSRF-Token；修改/生成携带 If-Match；owner/权限由 Go 可信认证解析。

反向代理须保留浏览器 Host/Origin，正式 Go 的公开 Origin/可信代理策略与该唯一来源一致。Cookie 按 HTTPS 安装策略设置 Secure/HttpOnly/SameSite、Path=/；不放宽跨域，不在前端复制或持久化 Cookie。禁止通配 Cookie 重写、CORS 放开或自动跳到开发 bootstrap `/__maas/local-session`。API 404/401/503不得改写成 index.html/200。

`/api/agent/v1/sessions/{s}/runs/{r}/events/stream?after=...` 为 SSE：禁缓冲、禁缓存，保留 Content-Type、X-Request-ID、ETag、HTTP状态及查询参数；代理读超时建议至少覆盖服务端流窗口（最终数值由后端装配确定），客户端有界断开属于 GET 轮询恢复。普通 Chat 与 Agent 共用该路径和 Session/Run 契约，无单独推理端口。

首张步骤/工具200页也要与根快照 ETag 一致；410整批作废、三轮有界GET重建，之后显示只读重连。Run事件cursor仍按持久seq，不随每次Session revision变化废弃。未知生成ACK只查原command，404/503不表示未执行，绝不自动新建Run。平台Key不上浏览器存储；未知Token/金额显示未知，保留父run/child_request_ids与按币种价表的用量分组。

## 验证入口和边界

```powershell
npm ci
npm test
npm run build
node scripts/deployed-build-browser.mjs
npm run format:check
```

以上在 console 目录执行。`deployed-build-browser` 使用 **生产dist＋显式HTTP夹具** 验证运行时配置、单Cookie登录/CSRF、SSE、410、刷新零生成和文本模型禁止Agent；不是Go/MySQL/真实模型验收，也不启动Vite。原207/6组仅属原f939/a4c组合。

真实安装完成后，使用 `scripts/deployed-smoke.mjs` 指向本次正式 URL；同一源码/配置/迁移/镜像组合的证据由最终交付记录。应用/MySQL重启恢复及唯一计量只能由真实MySQL组合执行，不能用此静态夹具签收。受控模型/批准适配、真实工具、真实上游分别记录。

正式站点只读 smoke（不会新建会话/生成/批准/重启；登录与退出属于认证操作）：

```powershell
$env:MAAS_CONSOLE_URL = 'http://127.0.0.1:<本次安装端口>'
# 经安全环境注入 MAAS_SMOKE_USERNAME / MAAS_SMOKE_PASSWORD，勿放进命令参数或日志
npm run test:deployed-site
```

可选 MAAS_SMOKE_SESSION_ID 指定原会话。只有另行具备该模型/额度授权时才设置 MAAS_SMOKE_SEND=1、MAAS_SMOKE_MODEL；MAAS_SMOKE_MODE 默认为chat，MAAS_SMOKE_PROMPT可覆盖安全测试提示词。开关不代表付费授权；脚本不自动批准、不重新执行未知工具。输出在artifacts/deployed-site，截图可能含测试会话内容，应使用无敏感信息的演示数据。

## MAAS-20 正式入口接点（2026-11-23交接，待最终Go SHA装配验证）

已认证读取 MAAS-20 的 product.example.json / product-service.md 接点附件。原后端正在沿PR18交付 `cmd/maas-service`，构建与进程为：

```sh
GOMAXPROCS=2 go build -p=2 -buildvcs=false -o maas-service ./cmd/maas-service
maas-service migrate --config /etc/maas/product.json
maas-service serve --config /etc/maas/product.json
```

不加开发build tags。迁移命令消费独立 migration_dsn_file，serve消费runtime_dsn_file并验证迁移/权限，不在常驻进程执行DDL。JSON的listen可为0.0.0.0:8080，origin须等于浏览器入口；healthz仅存活，readyz还验证MySQL与调度所有权。该接点首期replicas=1，不宣称多活调度。实际配置/Secret/迁移与验证版本由MAAS-20/21最终源码记录，不从前端猜默认。

若由该Go进程直接托管静态文件，dist放入product配置的static_dir（附件例为/usr/share/maas/console），公开JSON随同挂在 static_dir/console-config.json；若仍由现有独立静态容器托管，则沿/app/dist挂载。二者选择一种同源路由装配，不同时启动第二登录来源。前端chat.limits应只从安装已确认的agent.limits白名单投影；**不能把整份product配置放进静态目录**。附件agent限制使用USD等安装样例，与本目录TST受控样例不同，不能未经核定直接混用。

该正式入口当前仅装配原严格text-v1 Relay；真实tools-v1尚未装配/批准时拒绝，不切换demo。空models可初始化、登录和读取持久历史，不能调用模型；页面会显示无获准模型并禁用发送。两个真实安全工具的旧受控证据不等于本次正式模型已能选择工具。正式普通模型配置引用原publication_id/platform_key_file和私有Higress/TLS/签票链，由后端/安装者管理，不能在浏览器输入上游Secret。
