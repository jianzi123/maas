# 发布管理页面接续与受控验证

以原前端 PR #4 `428d44e0b4f64ec628e6a945fd4b63a0e45c260b` 接续，固定后端为 `821269bd32164918443e63e66c6a7cbce45d440b`。仅修改 `console/`，复用原 Go/MySQL/发布 Reader/管理适配，不改共享 OpenAPI、Go 产品代码或迁移。

本地 Go 模式现在可进入模型目录和发布管理页，使用原管理 cookie/CSRF。推理试用继续说明尚未提供；未配置的旧服务显示实际错误，不回退夹具。目录为空、发布未观测、202、持久操作与 Callable 独立显示。

暂停/恢复继续 PUT。包括 JSON 编辑器“保存”在内，ACK action 按已确认原 desiredState 与提交值差异关联：不变为 Update，改为 Paused 为 Pause，改为 Published 为 Resume。namespace/name、UID、operation/resource/generation 的原校验保留；错误 action 仍按未知写入锁定，未放宽消费者。

回滚/删除可返回 resource=null，保留原 operation.id 精确查询，重读配置后才能继续编辑。202 Unknown 单独显示并锁住写入；即使响应附带 resource，或当前 CR 随后可读，也不将它当作原写成功依据。查询 404/503 不触发重放，不从列表找其他操作替换。

## 实际验证范围

- 前端 `npm test`：100 pass，11 个显式 HTTP 环境专用用例 skip，0 fail。包含原 91 项及 9 项本轮 action/空 resource/Unknown 组件回归。
- 类型检查、生产构建、格式检查通过。原开发夹具浏览器 10＋11 组通过，pageerror 0；这些与实际服务证据分开。
- 实际 Go 浏览器 14 组通过；新增真实 API-server/etcd＋MySQL＋Go＋Edge 发布页面 18 组通过，pageerror 0。覆盖真实空目录/发布列表、创建/原ID查询、同UID权威历史、暂停/恢复、暂停后编辑、JSON保存切换状态、批准配置更新、空resource回滚/删除及原ID查询、回滚后编辑、真实CAS 409、写后ACK丢失 Unknown、390px、HttpOnly/零存储和退出。仅显式测试步骤协调，无真实网关 Ready 证明。

本轮没有重复跑原后端 72 项共享回归或把其旧结果累加。原 15 项后端管理场景、37 个响应 Schema 检查仍属于后端交付，本轮页面结果另列。前端夹具及原评审复现中的 Pause/Resume ACK 改用已经公布的 action；原竞态安全断言保留，没有接受 Update 来冒充 Pause。

## 复跑与装配

在 `console/` 执行 `npm ci`、`npm test`、`npm run build`、`npm run format:check`、`npm run test:browser` 和 `npm run test:review-browser`。上述普通运行不会创建真实模型或启动后端。

实际发布浏览器：从指定后端提交导出独立临时副本，保留其 `test/integration/management_test.go` 受控 helper。将 `console/scripts/release-browser-harness.go.txt` 复制为该副本 `test/integration/frontend_browser_test.go`。设置原后端临时 MySQL/Go 缓存、官方 envtest 1.36.0 的 `KUBEBUILDER_ASSETS`，以及 `MAAS_FE_NODE`、`MAAS_FE_CONSOLE_DIR`、`MAAS_FE_CONSOLE_NODE_DIR`；WSL 调用 Windows Node 时分别提供两种路径视图。

在原 `scripts/test-mysql.sh` 所创建的同一前台临时 MySQL 生命周期内，执行 `go test -tags envtest ./test/integration -run '^TestManagementFrontendBrowser$' -count=1 -v -timeout=150s`。harness 创建并最终删除自己的 schema，关闭临时 API-server/etcd、HTTP、Vite 和浏览器。共享控制台通过原 `MAAS_LOCAL_*` 本地桥接连接，不安装正式登录；会话原值仅短期进程环境传递。JSON 输入是明确合成的测试批准引用，临时文件结束删除，不含真实 Secret。

harness 在真实 API-server 更新后注入 ACK 丢失/版本竞争；它没有伪造业务 HTTP 成功体。协调使用原 Reconciler 代码及显式测试步骤，网关 producer 故意 DependencyMissing；批准 metadata resolver 为测试替身。没有真实 Higress、供应商、模型、Pod/GPU/权重或目标集群写入。

旧历史无新的可信来源输入，未导入旧行。生产登录、真实网关/Secret/validation 和真实推理仍待原角色交付，A01–A34 未完成整体验收；浏览器管理可操作不代表生产 Callable。独立 QA 待原角色验收，本轮均为开发者验证。
