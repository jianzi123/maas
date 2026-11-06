# 发布管理 HTTP 接续

本轮起点为原发布PR #1 `aba38f5`、后端PR #2 `0f07c5d`；原前端PR #4实际读回为 `428d44e0b4f64ec628e6a945fd4b63a0e45c260b`。复用其v0.4/v0.4.2-draft.1严格消费者，Schema只增加原定义的可达子集，不另改共享字段。暂不提供真实推理入口或把测试模型放行。

## 接口

全部通过现有管理cookie会话，写请求要求精确Origin和CSRF，平台Key不能部署。JSON响应保留可信X-Request-ID和no-store。

| 方法与路径（前缀 `/api/admin/v1`） | 行为与严格响应 |
| --- | --- |
| GET `/models` | 同一内核不可变profile目录，AdminModelList；没有profile返回真实空集，缺明确capability目录元数据则503；Callable复用原发布门禁，缺真实证明为false |
| GET `/model-releases[?namespace=&page_size=&cursor=]` | ReleaseList；namespace可省略，给出时必须非空且已授权；默认20、上限100，游标不可跨scope/query复用 |
| GET `/model-releases/{ns}/{name}` | ReleaseModelRelease，ETag为带双引号的当前RV；未观测CR省略可选status，不伪造observedGeneration |
| POST `/model-releases` | 原ReleaseReleaseInput（仅apiVersion/kind/metadata.namespace+name/spec），202 ReleaseAccepted |
| PUT `/model-releases/{ns}/{name}` | 同一输入＋`If-Match: "RV"`，一次UID/RV受保护更新；desiredState改变时action为Pause/Resume，否则Update |
| POST `/model-releases/{ns}/{name}/rollback` | 原ReleaseRollbackInput，target_revision、expected_cr_uid及If-Match；重用同UID权威历史和内部回滚服务，202 ReleaseAccepted |
| DELETE `/model-releases/{ns}/{name}` | If-Match，使用K8s UID＋resourceVersion双前置删除，202 ReleaseAccepted；资源清理仍由原控制器执行 |
| GET `/release-operations/{operation.id}` | 原ReleaseOperation；精确查询，无其他筛选参数，资源删除后保留操作结果，越scope不泄露 |
| GET `/model-releases/{ns}/{name}/revisions?cr_uid=UUID` | 原FE-R02 Reader不变，ReleaseRevisionPage |

写入409的code为 `resource_version_conflict`，刷新后由用户明确决策，不force、不自动重试。缺批准引用、历史载荷或其他依赖503，缺权限403，不可见/不存在404。未知写入返回202、原operation.state=Unknown、resource=null；知道原operation.id后只能查询，查404/503也不能推定原写失败。

前端暂停/恢复继续PUT，不新增动作端点。发布JSON编辑器如果通过“保存”直接改了desiredState，也应按实际状态差异校验返回action，不能始终预期Update。回滚与删除的resource可为null；以原operation.id关联并明确重读当前CR。202/Running和资源status均不充当调用准入证据。

## 启动与本地复现

在现有任务缓存具有固定MySQL 8.4.7、Redis 6.0.16、Go1.26.0 Linux和官方envtest1.36.0二进制时：

```sh
# WSL / 当前仓库根目录；前台执行，退出会清理自己的实例与数据
bash scripts/test-release-management.sh
```

该命令运行原共享数据库回归，再起真正临时API-server/etcd、CRD和Go HTTP，执行管理生命周期。网关producer有意返回DependencyMissing；Published保持不可调用。原始结果写入 `artifacts/release-management-mysql.txt`、`release-management-envtest.txt`、`release-management-http.json`。它不是长期服务，测试结束后URL失效。

管理进程沿用 `cmd/control-api`，不内置迁移或集群创建。在安装方明确提供的临时数据库/schema、临时KUBECONFIG和短期会话上启动：

```sh
go build -o .cache/control-api ./cmd/control-api
# 先在受控进程环境设置下面表格中的值；秘密只从原安全渠道注入
.cache/control-api
```

| 环境项 | 值的来源 |
| --- | --- |
| MAAS_CONTROL_LISTEN | 明确loopback端口，例如127.0.0.1:18082 |
| MAAS_MYSQL_DSN / MAAS_CLUSTER_ID / MAAS_KEY_PEPPER | 已初始化临时主库、固定cluster和受保护pepper；DSN启用parseTime及UTC；不会启动时建表 |
| MAAS_ADMIN_SESSION_SHA256 / MAAS_ADMIN_CSRF_SHA256 / MAAS_ADMIN_EXPIRES | 原短期随机session/CSRF的SHA256及明确UTC有效期 |
| MAAS_ADMIN_ORIGIN | 原前端同源origin，例如http://127.0.0.1:4179 |
| MAAS_HISTORY_NAMESPACES / DOMAINS / SCOPE / CURSOR_KEY | 显式允许的namespace列表、原授权域列表、scope和至少32字节游标签名key，变量分别带MAAS_HISTORY_前缀 |
| MAAS_HISTORY_KUBECONFIG | 仅安装方获准的临时API-server配置；缺此项不启用管理写入口 |
| MAAS_RELEASE_MANAGEMENT | 显式设为1 |
| MAAS_RELEASE_REGISTRY_FILE | 安装方批准的metadata JSON文件；缺文件或无匹配项时不接受Published意图，暂停/删除仍可工作 |
| MAAS_HISTORY_PAYLOAD_DSN | 可选的独立只读原历史payload连接；缺此项回滚故障关闭，公开历史读取不获私有载荷权限 |

批准registry文件形状为 `{"entries":[{"namespace":"...","spec":原完整批准Spec,"resolution":原release.Resolution元数据}]}`。匹配namespace及全部非生命周期Spec字段，authorization_domain须在显式允许域中。不能把界面模板、测试fixture或任意URL视为批准输入；本轮未生成真实模型配置。

原前端dev桥接继续使用 MAAS_LOCAL_API、MAAS_LOCAL_SESSION、MAAS_LOCAL_CSRF、MAAS_LOCAL_EXPIRES；它们与上述管理会话为同一组原秘密/expiry，API只保存摘要。MAAS_ADMIN_ORIGIN应与MAAS_LOCAL_PORT对应origin一致。执行 `cd console && npm run dev`，经已有本地入口设置HttpOnly cookie；不启用前端fixtures。生产登录/会话体系不在本次短期bootstrap范围。

发布控制器需沿原装配使用真实publisher，并显式调用 `publisher.WithManagementOperations()`，详见 `docs/release-management.md`。批准metadata resolver仅表示引用批准，不表示Higress生效或验证成功。

## 验证范围

新增测试在 `test/integration/management_test.go`：真实HTTP/API-server/etcd/MySQL管理流程、同内核目录、真实分页、409及UID冲突、暂停时registry故障、回滚、实际API-server写后ACK丢失、重建HTTP/DB适配器后原ID查询、删除后查询、权限和无生成/账务副作用。独立QA结论仍归原QA。

旧历史没有新的可信来源输入，未导入。真实H1–H4/Secret本地通道/validation生产者、Higress跨仓补丁、真实模型/目标部署/GPU及A01–A34整体验收仍未完成。原跨仓精确版本和最小补丁包沿用 `docs/higress-minimal-patch-scope.md`，未另写一个旁路调用内核。
