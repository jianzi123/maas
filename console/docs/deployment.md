# 同源控制台部署与站点复验

2026-11-26接续：统一基线为4402c456a155646ee4111e5f4a1f285621c11273（PR19 Merge commit，产品树等于d27d893890146c97e91454365b081f2be7d409b2）。本轮复用正常 `maas-service`、MySQL、Nginx和既有页面；不启用文件会话、Vite代理或一次性演示UI。版本/证据边界见site-validation-20261126.md。

## 构建和同源安装

仓库根：

```powershell
npm ci --prefix console
npm run build --prefix console
```

同一份console/dist可由maas-service的static_dir托管，或由同源Nginx托管。正常服务构建不带开发tags：

```sh
GOMAXPROCS=2 go build -p=2 -buildvcs=false -o maas-service ./cmd/maas-service
maas-service migrate --config /etc/maas/product.json
maas-service serve --config /etc/maas/product.json
```

使用MAAS-21同版本安装包的README完成迁移/凭据/健康与初始化。migrate用独立迁移身份；serve只读运行凭据、不执行DDL、业务持久化只用MySQL。/healthz不是模型可调用证明；/readyz报告profile/persistence等实际状态。新FC-1门禁/正式tools桥属于原后端和集成任务，本前端结果不替代其验证。

浏览器/api/admin/v1/session、/api/agent/v1及已装配管理API必须进入同一Go，保留Host/Origin、Cookie、X-CSRF-Token、If-Match、ETag和状态码。HTTPS按实际配置启用Secure Cookie；不得拼接第二登录服务、放开CORS或回退/__maas/local-session。SSE事件入口禁缓冲/缓存，代理读超时覆盖服务端窗口；客户端取消事件GET不等于停止模型或退款。

## 公开配置白名单

静态根必须提供application/json的/console-config.json，建议Cache-Control:no-store。默认文件：

```json
{"schema_version":"maas.console/1","chat":{"enabled":false}}
```

启用Chat时为chat提供enabled=true、原严格RunLimits的limits、工具版本tools=[{name,revision}]。安装器只投影私有product.agent.limits白名单；不能把product.json、DSN、密码、平台Key、Cookie、CSRF、上游URL放到静态根。console/examples/console-config.controlled.json是TST合成限制示例，不是正式USD额度/价表批准。使用实际安装策略；Go取交集并唯一准入/结算。

Go直接托管时放入其static_dir/console-config.json；独立镜像按实际静态根挂载，原release Nginx为/usr/share/nginx/html，旧console-server为/app/dist。Compose只读文件挂载；K8s ConfigMap单文件subPath更新后须滚动Pod。更改后刷新页面。生产不消费VITE_CHAT_AR1_*或MAAS_LOCAL_*开发变量。

### R-P01：旧在线试用是显式安装能力

新增可选白名单 `playground:{enabled:boolean}`，缺失默认false。d27正常maas-service没有挂载POST /v1/chat/completions；本轮实际页面使用合成无效Key重现405/Allow GET,HEAD，无原request_id、请求和usage增量0，不能登记为供应商失败。默认页面不展示消费Key或发送表单，引导已支持的Chat。未启用Chat的提示也不再承诺旧试用和管理必然可用。

仅当安装者已装配原受保护公共处理器、固定来源和唯一准入/计量时，才显式声明playground.enabled=true。例如以下**旧公共入口专用**完整配置形状不适用于d27正常服务：

```json
{
  "schema_version":"maas.console/1",
  "chat":{"enabled":false},
  "playground":{"enabled":true}
}
```

这不是新授权或新增路由。客户端仍只请求同源/v1，不直连供应商，消费Key仅在该页面内存中，公共请求不携带管理Cookie/CSRF。旧两字段配置与新UI兼容；旧UI回滚时同步回滚公开配置，不能保留旧版本不识别的新字段。未知字段或非布尔值失败关闭。

## 会话、工具和恢复

生产Chat/Agent共用AR-1。模型提示只取服务端text_protocol/tools_protocol/approval_state，不从别名推断；未批准、无工具能力或空模型时拒绝提交。内部ToolCall.id用于审批API，不能用供应商source_call_id替换；提供商ID回填属于Go适配职责。工具参数/结果按不可信数据展示。

首建/生成未知ACK保留原operation/hash，只读原command；404/503不证明未执行。停止ACK202仅表示请求接受，等权威终态；终态不再显示“等待实际终止”，needs_confirmation显示待核验，不重新批准未知工具。拒绝批准保留failed/approval_denied及实际attempt；已结束步骤无结果时不再显示永久等待。

旧轮询被新停止/批准/打开操作淘汰后，不得再发迟到快照读取干扰前台读取。当前事件代次与读取代次分开；正常idle Abort仍允许当前快照GET，真实关联/格式错误不因超时被吞掉。页面翻页410或首页ETag不一致丢整批，最多三轮GET，间隔25/75ms；旧请求在重试前作废。持续变化仍明确暂停/只读重连，不无限循环。事件cursor按持久seq，不随Session元数据revision一概作废。

## 验证命令

console目录：

```powershell
npx vitest run src/chat-http.test.ts src/chat-workspace.test.ts src/site-entry.test.ts src/deployment.test.ts src/single-model-replay.test.ts --pool=threads --maxWorkers=1
npm run build
npm run test:deployed-build
npm run format:check
```

原217/11skip、静态HTTP夹具5项保持原范围。本轮受影响回归与实际Go/MySQL站点分列，不累加为全仓或独立QA通过。

已启动的专属站点，用安全环境注入MAAS_SMOKE_USERNAME/PASSWORD后：

```powershell
$env:MAAS_CONSOLE_URL='http://localhost:18080'
$env:MAAS_SMOKE_OUTPUT='artifacts/installed-readonly'
npm run test:deployed-site
```

默认只登录、GET和退出；可用MAAS_SMOKE_SESSION_ID查看原会话。测试截图用无敏感数据，不写storageState/Cookie/CSRF到文件。

显式正常MySQL offline-controlled站点可使用扩展流程（不支持真实供应商）：

```powershell
$env:MAAS_SMOKE_MODEL='offline-controlled'
$env:MAAS_SMOKE_SEND='1'
$env:MAAS_SMOKE_APPROVE_SAFE_TOOLS='1'
$env:MAAS_SMOKE_FLOW='workbench'
$env:MAAS_SMOKE_OUTPUT='artifacts/controlled-workbench-unique'
npm run test:deployed-site
```

flow可为workbench、approve、reject、cancel、disconnect。批准自动化仅允许两个已声明的纯计算/只读工具和精确演示参数。生成流程遇已有record拒绝运行；失败保留原命令/决定ID，不能换新目录掩盖未知结果。cancel先确认原child in_progress，控制延迟按包README显式设5000ms；自然完成不计停止成功。disconnect只中断事件GET，原child应继续完成。

原记录恢复使用只读模式，不保留FLOW/SEND开关：

```powershell
$env:MAAS_SMOKE_FLOW=$null
$env:MAAS_SMOKE_SEND=$null
$env:MAAS_SMOKE_VERIFY_RECORD='artifacts/controlled-workbench-unique/record.json'
$env:MAAS_SMOKE_OUTPUT='artifacts/verify-original-unique'
npm run test:deployed-site
```

已知拒绝流程的部分证据可用MAAS_SMOKE_RECOVER_REJECTED_RECORD读取原command/approval后写新的recovered-record.json；不覆盖失败原件、不重发。工具页410差异测试使用flow=tool-page、MAAS_SMOKE_ORIGINAL_RECORD和MAAS_SMOKE_MUTATE_TITLE=1，仅对已完成两工具记录调整真实页大小并执行一次正常标题PATCH，恢复阶段不生成模型请求，不能称自然流量。

显式重启验收另执行 `node scripts/deployed-restart.mjs`，要求MAAS_SMOKE_RESTART=1、MAAS_COMPOSE_DIRECTORY、MAAS_COMPOSE_PROJECT与实际配置/容器匹配，loopback正常MySQL离线profile，以及MAAS_SMOKE_VERIFY_RECORD。脚本保持同一浏览器Cookie/CSRF，顺序重启自有maas/mysql，查原记录/哈希并核计量总数不增。不得指向他人或正式供应商站点；不是默认smoke行为。结束只停本任务project，保留数据与原安装身份，不down -v或清库重放。
