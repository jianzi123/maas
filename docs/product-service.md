正常产品服务接线（MAAS-20／MAAS-21）
====================================

2026-11-26增量：`product-migration-readiness.md`定义全部必需迁移的启动/ready/派发门禁；`product-tools-v1.md`定义新增正式工具适配候选。下文早期“Relay只支持文本”的记录限其旧验证截点。新适配不自动批准来源，缺不可变tools能力和真实安装前置仍准确拒绝。

后续接线补充以`product-management-and-offline.md`为准：新增同一正常进程的显式MySQL offline_controlled profile，以及可选management四独立DSN/原工厂挂载。默认生产行为仍不启用demo，任何失败不切换来源；下文“agentcontrolled测试入口”是旧测试程序，不是新增可部署离线profile。`docs/product-offline-verification.md`给出新profile实际作者SQL范围和未验边界。

构建：`GOMAXPROCS=2 go build -p=2 -buildvcs=false -o maas-service ./cmd/maas-service`，不加agentcontrolled/localworkbench标签。配置入口是`config/product.example.json`的严格JSON；所有数值都是安装样例，使用者必须明确选择运行/预算/速率值，不代表已有生产批准。

进程与迁移：

```sh
maas-service migrate --config /etc/maas/product.json
maas-service serve --config /etc/maas/product.json
```

`migrate`消费migration_dsn_file，执行已有kernel/release/agent迁移与独立product身份迁移，初始化稳定admin、密码派生验证值与首次ledger guard/slots。已有guard、预算、slot、管理员密码不会被每次启动重置；首次rate_ready仍为false，必须沿原Redis可信重建流程开启。DDL中断/版本冲突失败关闭，不用清库掩盖。

`serve`只消费runtime_dsn_file，不读迁移凭证或执行DDL。要求迁移完成、当前schema和权限有效；数据库不可用、迁移记录不符、Secret缺失直接失败，不选择文件/内存/SQLite。MySQL运行连接需要product_admins SELECT、product_sessions SELECT/INSERT/UPDATE、product_login_attempts SELECT/INSERT/UPDATE、agent_sessions_v1 SELECT/INSERT/UPDATE以及原管理/计量所需最窄权限；迁移身份另配，不能以运行时root通过替代最窄角色复验。

Secret文件：DSN文件是MySQL驱动DSN（如`user:password@tcp(mysql:3306)/maas?parseTime=true`），禁止multiStatements/allowAllFiles；bootstrap_password至少12字节，只在首次迁移使用；key_pepper/cursor_key至少32字节，应由安装者随机生成，跨重启保持原值，不能提交源码或打印。产品配置、静态资源、Schema是安装输入，业务状态落MySQL；Secret本身由Compose/K8s文件挂载管理。

监听可为0.0.0.0:8080，`origin`是浏览器实际同源入口，反向代理必须保留Host/Origin、Cookie、X-CSRF-Token、If-Match、ETag。HTTPS origin要求secure_cookie=true。`/healthz`为存活；`/readyz`验证MySQL及运行所有权，模型未就绪不伪装Callable。SSE `/api/agent/v1/.../events/stream`禁缓冲。静态服务器可分开代理所有/api/至同一Go进程，公开console-config.json由原前端放静态根，不能含Secret或上游URL。

唯一登录：`POST /api/admin/v1/session` body `{username,password}`，要求同源Origin及application/json；返回原Session `{admin_id,expires_at,csrf_token}`和HttpOnly SameSite=Strict maas_session Cookie。GET恢复该Session，DELETE带同一CSRF撤销。原管理和AR-1复用这一个MySQL身份，不再使用`/__maas/local-session`，平台推理Key不能登录应用。会话/撤销/登录节流均落MySQL，重启后相同Cookie和稳定principal仍可读取原会话。

运行恢复使用MySQL专属advisory所有权锁；第二个活跃调度进程拒绝启动。数据库连接/锁丢失后取消自身执行并退出，由Compose restart/K8s重新启动。新owner对旧在途执行仅恢复为needs_confirmation，不换ID重调；accepted/等待批准保留原截止时间。保留卷/数据库的重启不清历史、不重扣量。当前策略是单活跃scheduler，Deployment首期replicas=1；不能声称已完成多活调度。

正式模型配置：models元素为`{alias,publication_id,platform_key_file,protocol,timeout_ms}`；publication_id引用原发布链已耐久记录的Profile/活动修订，不从浏览器接受可信源或新造发布记录。platform_key_file为安装方选择的原平台Key，必须有对应Token/金额预算。gateway消费`endpoint`（固定私有HTTPS Higress根）、`ca_file/client_cert_file/client_key_file`、`admission_key_file/signer_kid/signer_owner/rate_revision`、dial/header/ticket超时与响应/事件字节上限。原票据v3绑定Body、Plan、原request_id及Profile，仍由原Higress Authorizer执行唯一Admit，Relay执行原结算；不直接访问供应商SDK、不自动跨源回退。

Profile未发布/不可调用、平台Key/价表/可信上界/TLS/签票输入缺失会给准确不可用原因；空models允许先初始化/登录/查询持久历史，不能产生演示模型或假用量。text-v1与tools-v1独立：当前正式Relay只支持原严格文本，tools-v1未批准/未装配返回tools_protocol_unavailable，不删除tool_calls或切到demo。真实供应商凭证由原Higress Secret链消费，本服务只持有安装平台Key及签票/TLS材料，不能把供应商Secret当平台Key。

离线受控测试入口仍是显式agentcontrolled程序/测试适配，不是正常serve默认，也不计为正式供应商验证。两套部署包若附离线演示，需要单独明确profile和原MySQL/唯一计量证据；不能把旧文件会话入口放入正常服务。尚缺实际批准H1–H4/真实来源等输入时只声明正式配置接线和本地组件验证，不声明已完成生产模型调用。
