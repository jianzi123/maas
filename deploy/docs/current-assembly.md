> 当前统一分支按同一仓库快照组装与锁定；见 [统一来源](source-assembly.md)。下文固定f445/30cf等版本是原交付证据范围，不代表当前统一候选或生产已验收。

# 当前装配接口与差异修复

## f445工厂/统一工作台接续（2026-11-14 UTC）

当前固定后端为f445362，前端30cf、原部署组装器e564、QA核心ac94/50354a7分别保留。新增显式publisher工厂及本地五身份已经存在，payload角色已改为maas_history_payload_reader；生产适配器仍待证据。见[工厂说明](publisher-factory.md)与[来源组装](source-assembly.md)。下面“缺工厂”等旧截点仅为历史，不能覆盖新事实；作者本地运行证据与原独立QA范围分开。

## R1–R3 独立验收后来源更新（2026-11-13 UTC）

当前来源为后端0559fa4、QA核心ac94a373、前端30cfce9与默认925d8c5；Chart0.2.2沿原#5接续4330883。完整237份上游输入和整目录替换见[固定来源组装](source-assembly.md)，publisher完成hook最窄列集及独立QA范围见[身份说明](database-identities.md)。此前选定摘要未覆盖全部Relay，且后端树的client.ts不含前端候选，旧“36/36”不代表本轮完整装配。下方旧截点和证据按历史保留。

## PR #6 候选接续（2026-11-13 UTC）

当前检查截点已更新：默认分支/前端 `925d8c5`，后端候选 `d2d7869`（PR #6 草稿未合入），部署沿原 PR #5。Chart 0.2.1 的四条独立 DSN existing Secret/env 引用、实际启动消费者及新角色模板见 [数据库身份](database-identities.md)。下文旧快照按历史保留，不能当作当前候选镜像来源。本轮只执行本地模板、预检、源码比较及空连接工厂单测，没有生产启动/实际角色或目标部署证据。

## 统一代码树更新（2026-11-08）

四个PR已经以正常merge合到同一项目。部署源码接口现固定到统一实现提交 `322bb92de05e111073c2572720e47a95efa7878d`，backend/console摘要均从该树重算，六份旧迁移摘要保持原值。专家原PR与固定SHA另见根目录 `config/integration-sources.json`。

根目录 `npm run dev` 自动构建显式workbench模式，启动私有MySQL、独立API-server/etcd、同源Go管理与Vue；不再需要按旧步骤分别导出前后端工作目录或手工注入本地会话。启动、Key/预算、发布/更新/暂停/恢复/回滚/下线、原operation查询及停止清理已实际浏览器验证，见 `docs/project-integration.md`。本地入口不使用已有KUBECONFIG，不提供真实模型推理。

`deploy/console-server`与工作台共享 `internal/webconsole`；控制台Dockerfile构建上下文现在包括根go.mod/go.sum及该共享目录。生产静态构建、8080、探针和API不回退SPA的语义保持原样。这里没有将本地启动器装进生产Chart，core/operator/生产会话的deploymentReady仍为false；Helm静态通过不表示目标部署完成。

## 原专家装配记录（2026-11-07）

本轮沿 PR #3 增量更新，不合并或改写其他负责人模块。读取 MAAS-1 本人的职责/重构评审后核对实际代码：发布 PR #1 `4d45c6f5a033783a8c1a8886f2b6e65eff7a3cf4`、后端 PR #2 `821269bd32164918443e63e66c6a7cbce45d440b`、前端 PR #4 `aef53eeb7eac16bd7a956294fefab750a3de31f8`。这些是本次固定检查截点，后续提交须重验，不能由分支名推定兼容。

`charts/maas-platform/runtime-interface.json` 记录真实编译 group、环境项名称、监听/探针、28份源码摘要、六项迁移摘要及剩余适配。它随 Chart 打包，由模板和预检读取；记录只证明检查了哪些源码，不证明镜像或目标就绪。原 52a24c0 的检查保留在 evidence/history。

| 接点 | 实际实现 | 本包处理及待交接 |
|---|---|---|
| Operator | /operator；127.0.0.1:8081 healthz/readyz、webhook 9443；nil adapters，readyz失败，metrics关闭 | 保留容器内 exec 探针，group须匹配接口快照；不以控制器存活判定Callable |
| 管理入口 | cmd/control-api，环境配置，强制127.0.0.1或::1、短期bootstrap；无health/metrics和推理监听 | 已存在，不能再写成只有库；Chart拒绝将control-api命令当生产core。正式监听/配置/会话/探针/真实适配仍由后端交付 |
| 发布管理 | models、model-releases、原operation查询、原UID revisions及Key/usage查询 | /api前缀正确；202/Unknown、UID/RV、同ID查回继续沿现有接口，不新增代理或动作端点 |
| 推理 | 公开relay库已有受控接点；control-api未装配/v1监听 | 不能把管理进程通过ClusterIP暴露后声称推理可用；/v1仍须走具备真实证据的Go入口 |
| Vue | npm ci/build产生console/dist；Vite的同源会话桥仅serve阶段启用 | 新增非root静态服务器和Dockerfile.console，8080及/healthz、/readyz对齐Chart；生产登录/会话仍待接合 |
| Redis | Store.RebuildRate已实现，有作者受控重启/见证重建记录 | 纠正旧“缺协调器”结论；缺的是生产调用/身份/目标HA证据，不另造恢复逻辑 |
| 发布迁移 | 1基础、2权威历史、3持久管理操作 | 核心与发布均按1→2→3，预检校验六项Applied+摘要；不复制DDL、不改旧checksum |

## 本地受控启动路径

以下为复用后端/前端既有入口的操作说明，本轮没有启动数据库、API-server、长期HTTP服务或模型调用。仅在已有明确授权的临时依赖上执行，结束前收集结果并清理本次实例。

1. 准备上述固定提交的独立工作副本及批准工具链；运行已有后端 `scripts/test-release-management.sh` 可复现原临时依赖流程。不要拿任意现有 kubeconfig 代替专用临时 API-server。
2. 后端以独立迁移身份显式执行 `kernel.Migrate`、`mysqlstore.Migrate`（均包含版本1/2/3）；它们是Go函数，**没有虚构的migrate CLI**。现有测试/安装方管理程序调用这些函数；control-api启动不迁移。生产迁移runner仍需后端交付。
3. 编译后端 `cmd/control-api`，只在受控进程环境注入参数。精确名称见runtime-interface：MAAS_CONTROL_LISTEN为明确loopback；DSN/pepper、会话及CSRF摘要/到期、历史cursor key/payload DSN来自安全渠道，不进Helm/ConfigMap/命令行/日志。
4. MAAS_CLUSTER_ID固定原集群身份；MAAS_ADMIN_ORIGIN与前端loopback origin一致。原历史namespace/domain/scope和至少32字节cursor key显式批准；MAAS_HISTORY_KUBECONFIG只指临时目标；MAAS_RELEASE_MANAGEMENT=1，批准metadata文件通过MAAS_RELEASE_REGISTRY_FILE加载，不把测试registry当真实批准。
5. 前端保留既有 MAAS_LOCAL_API/SESSION/CSRF/EXPIRES/PORT，在同一受控环境执行npm run dev。raw session/CSRF与后端摘要对应，有效期沿原bridge最多30分钟。原 /__maas/local-session 仅本机开发桥提供；静态产物不含该运行服务。
6. 发布控制器的安装方装配须显式启用 `publisher.WithManagementOperations()`；否则不能以UI已受理推定原operation完成。当前review Operator尚未装配，保持不可调用。

## 静态控制台打包

将前端固定提交导出到独立构建上下文，覆盖本PR的deploy目录，再用 `deploy/images/Dockerfile.console` 构建。显式传入锁定digest的 NODE_IMAGE、GO_IMAGE、RUNTIME_IMAGE；无批准版本不自动选最新版。npm ci沿package-lock；Go静态服务器及探针无第三方运行依赖。镜像构建、registry导入和目标启动本轮未执行。

新服务器固定非root8080、根目录/app/dist。已有文件正常服务，Vue历史路由回index.html且no-store；缺失assets返回404，/api、/v1、/__maas及其子路径返回404，不以SPA成功掩盖API或开发会话缺失。/healthz仅证明进程，/readyz要求index.html为非空可读文件；它只证明静态资产可用，不证明后端/会话/模型Callable。测试使用内存HTTP请求及临时文件，没有长期监听。

Ingress保留 /api→core、/v1→core、/→console，不做路径重写，适用于当前前端相对路径。生产session/Origin/CSRF与真实Go入口必须先接齐；不能用Vite开发服务器、bootstrap原值注入或mock登录替代。core和console的Secret、ConfigMap引用继续由批准安装方提供；console配置挂载可供后续批准适配使用，当前静态服务器不消费其中秘密。

## 恢复与兼容

核心 migration 1/2/3 包含Key元数据、rate_rebuilds、publication proofs、validation intents/receipts、request snapshot digest及usage diagnostics。发布 migration 1/2/3包含原七张表、权威快照/载荷/导入记录、持久管理操作。逐文件SHA和精确路径见接口记录；对照主库各自schema_migrations的版本、sha256及Applied。保留原Applying，沿原函数恢复，摘要冲突先停，不跳过或自行“修复”旧checksum。

备份恢复点同时覆盖上述状态及原request/event/command/operation身份、旧UID历史、ledger/tombstone/held/slot和证据。恢复后原operation查询及删除后历史可达，旧hash无权威来源继续503，不用当前spec补历史。独立payload只读身份及运行role/default role沿原两份config/mysql权限脚本复核；管理入口目前为受控组合装配，不能直接把高权限组合授予生产Pod。RPO/RTO/保留期必须有批准输入，预检缺项即拒绝。

RebuildRate保持 blocked→新epoch→锁外MySQL当前窗见证下界→Redis identity/nonce/epoch/window复核→ready；失败时按原durable重建记录/epoch查回，不靠Pod重启或清桶脚本。原controlled-api-verification为作者受控证据，本轮未复跑数据库/HA。恢复执行入口、角色权限及目标主从切换/跨窗/并发/单写fencing仍需后端/运维/独立QA验证。

H1/H4 Wasm、H2 Envoy reporter、H3 instance agent及Secret本地通道在锁清单分开记录source/ABI/digest/mirror/identity/evidence；源码定位复用后端最小patch说明，不视为已构建产物，也不新增跨仓写入。原排空、UID清理、LWS整组/GPU容量及财务held保留规则继续按runbook执行。
