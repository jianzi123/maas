# 控制台与本地 Go 联调

控制台包含模型目录、平台 Key、在线试用、模型发布、请求与用量五个入口。Key 页采用列表、按需创建/编辑弹窗、预算详情和用量跳转；参考来源见 [ui-reference.md](ui-reference.md)。

## 快速预览

在 console/ 下执行：

```sh
npm ci
npm run dev:fixtures
```

此模式明确标记开发夹具，可查看模型选择、流式输出/停止、发布状态和非空请求/Token/金额样例。

## 连接本地 Go

本轮接线基于后端 PR #2 的 821269b。按后端 docs/release-management-http.md 安装已授权临时环境，并通过进程环境注入 MAAS_LOCAL_API（仅 loopback HTTP）、MAAS_LOCAL_SESSION、MAAS_LOCAL_CSRF、MAAS_LOCAL_EXPIRES（未来30分钟内）及 MAAS_LOCAL_PORT，再运行：

```sh
npm run dev:go
```

会话安装桥接先由 Go 校验短期会话，再设置 HttpOnly / SameSite=Strict cookie；CSRF 仅保留在内存。所有业务 /api 请求原样发送到 Go，严格校验共享契约，不回退夹具。生产构建不启用本地安装入口，完整生产登录仍由相应服务提供。

| 页面       | 当前 Go 管理接口范围                                                                       |
| ---------- | ------------------------------------------------------------------------------------------ |
| 模型目录   | 读取同一内核 profile 目录，展示来源、绑定修订与是否可调用，并进入试用或发布                |
| 平台 Key   | 创建/原值一次展示、预算修改、撤销、筛选和预算明细，查看用量带入原 Key ID                   |
| 在线试用   | 页面完整；本轮 Go 进程没有推理入口，禁用发送并说明原因。开发夹具模式支持流式/停止          |
| 模型发布   | 创建、详情、更新、PUT暂停/恢复、保留修订/回滚、下线与原 operation.id 查询；202不代表可调用 |
| 请求与用量 | 真实查询与筛选；本次未生成模型请求，因此本地数据库呈现真实空态                             |

发布管理使用当前 UID/resourceVersion，JSON编辑器也按 desiredState 差异校验 Pause/Resume/Update。回滚或删除 ACK 的 resource 可以为空，继续查询原 operation.id 并重读；未知写入不重放。目录的绑定修订不直接称为活动版本。缺真实 Higress / validation 时 Callable 保持 false。

## 必要检查与截图

```sh
npm test
npm run build
npm run format:check
npm run test:browser
npm run test:review-browser
```

普通测试按条件跳过11项真实HTTP专用场景。真实 Go 页面复跑使用 scripts/test-management-browser.sh：先提供独立后端源码 MAAS_GO_SOURCE、获准便携 MySQL/Go/envtest 路径和 Node 路径（变量见脚本头部）；WSL 调用 Windows Node 时另传 MAAS_FE_CONSOLE_NODE_DIR 的 Windows 路径。脚本只建立自己的短寿命 MySQL、API-server/etcd、Go/Vite 和浏览器，前台完成后清理进程、数据及注入的测试文件。

实际管理页面截图与结果位于 artifacts/management-browser/；旧 Key/HTTP 兼容验证位于 artifacts/go-browser/、artifacts/http-continuation.json。这些运行复用真实 Go 管理实现、临时 MySQL 与 API-server；批准引用和缺失网关为测试适配，未调用供应商、推理模型或部署目标集群。开发者复跑不代替原QA独立验收。

## 本轮页面验证

在保留原 PR 发布实现后，104 项前端回归通过；类型、构建、格式通过。真实临时 Go/MySQL 检查包含 Key 浏览器14组、HTTP专用11项，真实 API-server 发布浏览器18组及本次页面联动/移动端13组，均通过且页面异常0。夹具浏览器10＋11组通过。批准元数据、缺失网关和安装会话为受控测试适配，真实推理及完整生产验收仍未执行。全部临时服务和数据在脚本结束清理。
