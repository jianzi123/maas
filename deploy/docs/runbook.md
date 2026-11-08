# 安装、观测、升级与恢复

适用范围为 MAAS-2 OPS01–OPS08，接口检查截点 MAAS-3 821269bd / 前端aef53ee；新接口、迁移矩阵与受控启动步骤见 current-assembly.md；本手册是待授权执行流程。没有已安装目标和运行结果。CPU/内存、60秒终止宽限期及探针周期是 Chart 初始配置建议，不能当作模型容量、排空完成期限或已批准 SLO。

## 所有权与装配

| 对象 | 唯一责任及保留 |
|---|---|
| 平台 Deployment/Service/RBAC/webhook/NetworkPolicy | MAAS-8 Chart；用户先关闭准入、排空后才卸载 |
| ModelRelease CRD | 架构确认 group、后端维护 schema；安装负责人独立管理；本 Chart 不带 crds/，不安装/升级/删除 CRD |
| Higress、McpBridge、共享 listener、H1–H4 插件 | 网关安装负责人或唯一 bundle writer；单模型不安装/升级基础设施、不替换共享整对象 |
| LWS controller/CRD、GPU/CNI/CSI | 集群安装负责人；独立锁版/升级，不从单模型 CR 管理 |
| core DDL | MAAS-3 的 kernel.Migrate；独立迁移身份，发布前显式执行 |
| 发布 DDL | MAAS-11 mysqlstore.Migrate；版本1基础七表、版本2权威历史、版本3管理操作，沿原迁移/校验，不另建 |
| 用户 Secret/PVC/权重/账本/tombstone/held | 归用户/数据负责人保留；不创建 Helm ownerReference、不由卸载或模型 GC 删除 |

Higress **复用**：核已有 Chart/app/Envoy/CRD/Wasm、release namespace/owner、服务拓扑、已有人工配置、插件链及真实回执。Chart 仅接受 reuse；安装策略由独立步骤负责，不能用 values 假装安装成功。**新安装**：安装负责人在目标授权后获取批准 Chart及全量依赖，私库映射、安装 CRD/controller/网关扩展并验证 H1–H4，再把 namespace/service 交给本 Chart。未提供对应工件时停在前置条件，不自动下载最新版。

Chart 不渲染 McpBridge、模型路由或模型 CR，以防与唯一 bundle writer 双写。对平台 ingress，/api 与 /v1 始终到 Go，/ 到 Vue 静态服务；现有后端与前端 main/镜像须按这组路径审核，不能直接把 /v1 送上游。集群入口仅 ClusterIP，选填内部 ingress/TLS；公网 LoadBalancer/DNS 不由本包创建。

## 镜像、配置与 Secret

每组件填实际 repository 和 sha256 digest；私库映射是把 repository 换为批准私库并校验导入后的 manifest digest、架构及签名，不能假设重打包后 digest 不变。imagePullSecrets 只传现有对象名。所有镜像须包含静态 /maas-probe；Operator 为 /operator，构建配方见 images/Dockerfile.operator。该 Dockerfile 需要完整后端源码树（本目录 PR 独立基于当前默认分支）；本轮没有构建/拉取镜像。core生产command、args、配置消费及健康端口仍由原后端提供；现有control-api仅loopback受控入口。console现提供/maas-console静态服务和Dockerfile.console，不注入Vite开发会话。

core 的非秘密 ConfigMap 挂 /etc/maas/config，运行凭证 Secret 挂 /etc/maas/credentials。引用应使用版本化不可变对象；修改已有ConfigMap/Secret不会自动产生Chart checksum滚动，须确认程序受控reload或显式更新引用，并重验publication证据。此为文件挂载约定，实际程序必须确认消费方式后启用，不设不存在的环境变量。核心、publisher、slot worker、迁移各用独立最小数据库身份；不能把迁移密码注入 core。Operator 只挂 webhook TLS 证书，无 MySQL/上游 Key、无 Secrets RBAC；其投射 volume 由 kubelet 读取，不等于 SA 获得 get Secret 权限。publisher 不写预算/Key/request/slot/终态，slot worker 不退款，原 SQL 模板保留为唯一来源。

上游凭证继续通过批准 Secret agent 的同 Pod 认证通道和 UID/resourceVersion 快照，不经 Chart/CR/ConfigMap/日志。当前 Chart 不部署尚未交付的 agent/receipt/reporter。外部代理证书或私库 CA 要以批准基础镜像/集群配置装配，不能临时关闭 TLS 校验。

Webhook Secret 包含 tls.crt/tls.key，SAN 匹配 <release>-maas-operator.<namespace>.svc，完整信任链的**公开** CA base64 放 operator.webhookCABundle。TLS key 不进 values；mount 默认路径沿当前 controller-runtime，0440 与 fsGroup 给非root访问。轮换须确认 server 热加载或批准滚动，保留新旧CA过渡及拒绝证据。失败策略 Fail；review Operator readiness=false，但 webhook Service 显式发布非Ready地址供校验拒绝，不用于业务接流。此例外只属于 webhook Service。

## 网络与仅内网/混合

每组件选择专属 Pod label，Ingress/Egress 两方向默认拒绝；端口和 namespace+pod selector/CIDR 必须显式列出。空列表会阻断服务，这比猜测 API-server、DNS 或数据库地址更可审查。需要逐项补：

- Operator → API server（真实 Service/NAT 地址、端口）；API server → webhook 9443，考虑控制面来源 CIDR。
- 所需组件 → DNS TCP/UDP 53，按真实 DNS namespace+pod selector；不以任意namespace选择器放通。
- core → 指定 MySQL/Redis/mTLS release-control/Higress，Higress → 受保护 Go 最终授权/结算；只开确切端口和身份。
- 内部 ingress → Go/console，必要监控来源 → 已实现的受保护指标端口（当前未开）。
- core 不直达模型来源。internal-only 的 Higress 出口只允许批准内网模型；hybrid 另由网关负责人限制到批准外部出口代理/固定来源，填写 externalEgressPolicyRef。不能用 Kubernetes L3/L4 NetworkPolicy 声称实现 FQDN/TLS/HTTP 路径校验。

多个 NetworkPolicy 是并集，其他宽松规则可放开本包拒绝；CNI/NAT/hostNetwork例外需目标验证。不要仅以渲染名单声称无外网。私有IP也不能独立证明可信身份，跨组件 mTLS/票据绑定仍必需。

## 探针、日志与指标

startup/liveness 检查进程 /healthz；readiness 检查真实 /readyz。当前 Operator 绑定127.0.0.1:8081，故用容器内 exec /maas-probe，2秒超时、拒绝重定向/代理、不打印响应正文。缺核心/receipt/registry/validation 时 readyz 与业务门禁继续失败；liveness 不把下游失效当成进程死锁。Controller readiness不代表单模型Callable，单模型可用性依 MySQL 活动 publication 与完整可信证据。

当前 Operator metrics=0，Chart 不创建虚构 ServiceMonitor/PrometheusRule。后端须交真实指标端点/名字/类型后，监控负责人按 signals.csv 映射并验证权限/脱敏，再开放对应网络。指标缺失不能填0；需要样本缺失数、拒绝原因、采样分母。请求/trace/UID只作受控日志关联，不作高基数指标标签；不记录 Key/凭证/提示词/完整上游错误。建议允许字段见 log-fields.json，实际日志输出待原后端接合，不宣称已采集。集中存储、访问和保留期待批准。

排障先看依赖门禁、CR desired/observed/active及conditions，再查原command/request/event ID在主库的事实；202不是Callable。禁止为“恢复绿灯”去finalizer、替换最新Secret、跨来源回退、强制空桶Ready或重发未知生成。

## 安装与正常验证（目标授权后）

1. 核锁清单、安装owner和实际版本，运行离线 preflight；审批具体 context/namespace与操作范围。
2. 备份已有 CR/配置和同一恢复点的 MySQL，独立核迁移 checksum/Applying/Applied、低权限角色/default role；迁移未完成或部分失败则保留新准入关闭，由原迁移接口恢复。
3. 分别安装/复用共享依赖，交付真实 CA/Secret 引用、ConfigMap、网络规则及不可变镜像；认证运行身份，核无迁移权限。
4. 由运维在明确 context 执行 server-side dry-run和 Helm 安装（本轮未执行任何 kubectl/helm install）。首次 review binary 不会ready，不能用 --wait 的超时当作环境故障或跳过就绪条件。
5. 测试确认缺依赖拒绝、跨模型/Secret/共享资源权限拒绝、全部可接流实例receipt、专用validation的预算/唯一intent、真实Go→Higress固定来源；批准模型/Key/额度前不做请求。
6. 与独立测试记录确切SHA/版本、目标、时间、脱敏证据及A01–A34映射，保留未执行项。

## 升级、排空与回滚

应用 Chart 默认 Recreate，避免未经容量核算暗示无停机；这不负责业务排空。升级或卸载前先以已批准管理流程关闭新准入。按原 publication 集合（含旧/Closed）确认in_progress与HELD/QUARANTINED **slots**安全结束，旧路由/后端保持到可信证据满足。DrainTimeout/CleanupBlocked 保留 finalizer；Pod消失、节点失联、preStop或60秒到期都不证明停止。财务unknown held独立保留；slot FREE不退款。

然后撤专属路由/handle、runtime引用归零CAS Retiring、按inventory UID/resourceVersion删专属对象、确认Removed后移除本finalizer。保留人工/其他模型共享条目；不能依据名称前缀接管/清理。旧worker对同名新UID的清理必须拒绝。Chart 卸载仅移除本 Chart资源；若提前停Operator可能遗留finalizer，应恢复相同受控组件接续，不能强删。CRD、用户Secret/PVC/权重和账本不在Chart卸载范围。

三种回滚必须分开：

| 变化 | 正确动作及禁区 |
|---|---|
| 应用/Chart | 确认旧程序兼容当前schema与协议后回滚镜像；重验真实门禁，不回退数据库历史 |
| CRD/controller/Wasm | 先审schema存储版本、现有CR和owner及兼容路径；独立更新/回退；回执按新启动代际/配置重新收集 |
| MySQL DDL/数据 | 沿核心和发布迁移责任分别向前修复；不自动down migration或删tombstone/held/命令去重；灾难恢复单独批准 |

Helm不自动完成CRD schema迁移，Chart rollback不恢复数据库或插件事实。LWS旧安装跨版本的CRD owner变化需按实际版本官方升级路径核验，不能force接管。终态仍3.0，D1 3.1待消费者统一（含性能analyze.py、HTTP/历史读）；不能只改版本字段。模型回滚是新publication/epoch的正常发布，不复活tombstone。

## MySQL、Redis恢复与异常处置

备份负责人需确认加密介质、访问、保留、恢复目标和RPO/RTO。备份同恢复点覆盖核心账本/Key校验依赖、request/终态去重、slot/fence/释放审计、rate见证，以及发布/命令/inventory/tombstone/真实证据登记；K8s的Secret恢复材料另走安全渠道。MySQL备份的实际工具和命令依锁版及目标权限提供，本轮不编造可执行凭证命令。

恢复顺序：关闭新准入 → 确认唯一主写与fencing → 核核心/发布迁移和持久性 → 原ID恢复P/A/S未知提交 → 核外部实例UID/启动代际/配置/Secret版本 → 协调Redis重建 → 重验receipt与validation → 才允许新准入。旧CR.status不能重建授权，未知结果不自动重放。恢复旧快照可能丢失已发生调用，必须在批准灾难恢复计划中处理幂等/外部事实，不把它当日常回滚。

Redis仅速率门禁，不是真账本。重启/丢桶/角色变化/marker或epoch异常 → 同guard短事务blocked并增epoch → 锁外从MySQL当前窗已提交见证读重建下界 → 核epoch/窗口/Redis身份不变 → 才ready。禁止持MySQL锁做Redis IO，不能空桶ready。最新Store.RebuildRate已接合原语与耐久见证下界，受控重启场景已有作者证据；生产调用入口/身份及目标HA仍待验证，缺可用依赖继续拒绝。已准入请求按原快照唯一结算，不从Redis AOF/RDB重写业务预算。

| 症状 | 查证与最小安全动作 |
|---|---|
| Ready失败/DependencyMissing | 核实际adapter/依赖版本；保留拒绝，不能改为TCP探针假绿 |
| webhook超时/x509 | 核服务、Pod回环探针、SAN/CA、证书投射/时钟、控制面到9443；保留Fail |
| publication提交ACK未知 | 按原command ID/hash查主库；不新建validation intent |
| request/结算ACK未知 | 查原request/event ID；不重复生成或扣量 |
| receipt过期/新副本无证据 | 阻断受影响新准入，重验实际可接流集合；不从证明集合剔除仍接流实例 |
| 删除超时/节点失联 | 保留旧publication/路由、隔离slot及finalizer；恢复原allocation/fence可信证据 |
| Redis恢复后仍blocked | 核epoch/当前窗见证下界/运行身份，完成协调而非清空状态 |
| LWS Pending/OOM | 核完整组拓扑与GPU、预热峰值及显存；不只减少单Pod资源或自动换引擎 |

## LWS组级与引擎容量

设每组size=S（含leader），每Pod申请g GPU，期望组G、surge组U。整组GPU至少按(G+U)×S×g核算，并加仍在排空的旧runtime组；跨模型共享不能重复计“可用”。BlueGreen可能同时保留完整新旧组、预热与保留回滚实例。另核CPU/内存/网络/RDMA拓扑、权重及缓存/PVC容量、存储吞吐。没有余量时由成员批准停机/分步策略，不承诺零停机。

单GPU显存预算单列权重、KV cache、激活、CUDA graph/编译workspace、通信缓冲及碎片余量；锁实际量化/TP/DP/上下文/并发及engine CUDA/torch/NCCL版本后由算法实测。7B推导不能外推完整DeepSeek MoE。LWS Ready只证明其控制器条件，不证明推理、预算上界、质量或性能。

## 官方参考（2026-11-05核验）

- [Helm Chart/schema](https://helm.sh/docs/topics/charts/) 与 [CRD生命周期](https://helm.sh/docs/chart_best_practices/custom_resource_definitions/)：本轮核对文档，不是目标版本测试。
- [Kubernetes probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/) 与 [NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)：探针及网络规则边界。
- LWS升级/整组rollout条件复用MAAS-12运维评审；实际锁版后再复核对应发行文档。