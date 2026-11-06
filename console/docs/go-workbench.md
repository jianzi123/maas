# 本地 Go 工作台

已具备的页面：平台 Key 创建、原值一次展示、元数据查看、三维预算修改、撤销；请求明细和用量汇总查询。业务操作直接连接当前 Go controlapi.Handler / MySQL，浏览器仍按共享 Schema 严格校验。

## 本次实际操作

已使用后端 0f07c5d 的真实 Handler 与临时 MySQL 8.4.7 完成：

| 页面操作                              | 实际结果                                       |
| ------------------------------------- | ---------------------------------------------- |
| 创建 Key，显式设置请求/Token/金额预算 | HTTP 201；关闭原值后，刷新只返回元数据         |
| 将请求数预算从 9 改为 0               | HTTP 200；旧预算版本再次写入返回 409           |
| 撤销 Key                              | HTTP 200；页面显示已撤销                       |
| 查询请求与用量汇总                    | HTTP 200，当前数据库没有生成请求，显示真实空态 |
| 精确查询不存在的原请求 ID             | unknown；不推测未准入或过期                    |
| 未配置原 CR/可见性输入的历史查询      | HTTP 503；不返回假历史                         |

实际 Go 浏览器检查 **14 项通过，页面异常 0**；真实 HTTP/组件检查 **11 项通过、0 跳过**。前端回归 **91 项通过**（普通运行另有 11 项 HTTP 专用检查按条件跳过），类型/构建/格式通过，开发夹具浏览器 **10＋11 组通过**。夹具的模型试用/停止、发布/暂停/回滚交互没有冒充真实模型或发布运行结果。

四张 Go 页面截图在 artifacts/go-browser/。测试结束后，浏览器、Vite、Go 服务、临时 MySQL 进程与测试数据均已清理。

## 启动

查看完整开发界面和试用/发布交互：

```sh
npm ci
npm run dev:fixtures
```

连接已有的获准本地 Go 管理 API：由临时环境启动器通过进程环境注入 MAAS_LOCAL_API（仅 http://127.0.0.1:端口）、MAAS_LOCAL_SESSION、MAAS_LOCAL_CSRF、MAAS_LOCAL_EXPIRES（未来 30 分钟内）和 MAAS_LOCAL_PORT。会话由原 Go BootstrapSession 安装适配发放，原值不放在 VITE_ 变量、源码、命令参数或日志。然后执行：

```sh
npm run dev:go
```

页面自动进入“平台 Key”，顶部持续标明 Go/MySQL 模式。dev:go 不创建数据库或后台服务；没有上述配置时使用普通同源接口模式。真实部署仍需完整登录和 HTTPS，不能使用此本地安装会话代替生产鉴权。

临时 Vite 桥接仅发放本机短时 HttpOnly / SameSite=Strict 管理 cookie 与内存 CSRF，首次连接先由 Go 校验会话。只接受匹配当前本地 Origin 的 POST；退出清理该浏览器 cookie。其余 /api 请求原样代理到 Go，不模拟业务响应、不放宽字段、不回退夹具。退出不声称已撤销 Go 中尚未到期的安装会话；临时环境结束会关闭 Go 进程。生产构建不启用这个入口。

## 浏览器复跑

scripts/go-browser-harness.go.txt 复用后端真实内核和受控会话，创建单独测试 schema，调用 scripts/go-browser.mjs 后清理。它与 scripts/http-harness.go.txt 一样只用于指定后端提交的独立临时副本，不修改后端产品代码。

1. 在后端独立副本中，将两个 .go.txt 文件复制到 internal/controlapi/，后缀改为 _test.go。
2. 配置原后端 scripts/test-mysql.sh 的便携 MySQL/Go 缓存，以及 MAAS_FE_NODE、MAAS_FE_CONSOLE_DIR、MAAS_FE_CONSOLE_NODE_DIR（见 review-fixes.md）。
3. 设置 MAAS_TEST_PATTERN='TestFrontendHTTP|TestFrontendBrowser'，前台运行原 scripts/test-mysql.sh。

脚本启动自己的短寿命 Go/MySQL/Vite/浏览器，执行后全部关闭。Go 浏览器结果和截图位于 artifacts/go-browser/。HTTP 组件结果位于 artifacts/http-continuation.json。没有配置真实临时 API 的普通 npm test 明确跳过 11 项 HTTP 专用检查。

## 发布管理接续

指定后端 `821269bd32164918443e63e66c6a7cbce45d440b` 已提供目录、发布管理、权威历史和持久操作查询。Go 模式直接接这些页面，依赖缺失显示真实错误，不回退夹具。完整接口与后端安装参数见该提交的 `docs/release-management-http.md`；本轮前端实际验证范围与复跑见 [release-management.md](release-management.md)。

## 当前限制

- 生产登录和真实推理入口尚未交付。目录/发布功能取决于安装方明确配置的适配器、授权域、registry 和历史输入；Go 模式继续限制推理试用。
- 权威历史 Reader 复用原实现。发布 envtest 提供同 UID 测试历史/批准引用；旧行无可信来源或安装未配置时按实际错误处理，不猜历史与资格。
- 当前未发出模型请求，用量页的空列表是真实查询结果；不证明非空 RequestRecord/Usage、生成停止或容量恢复。
- 五项竞态修复已在原 PR 的 223d88c 保留；本轮继续在同一 PR 上补 Go 页面入口及 header/chunk/error 的原请求 ID 校验。三方复现继续作为回归用例，不代替独立 QA 验收。
