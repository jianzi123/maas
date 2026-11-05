MaaS ModelRelease 受控控制器实现（MAAS-11）
============================================

本仓库同时包含 [MAAS-10 离线性能观测分析器](tools/perf/README.md) 与下述 MAAS-11 控制器。两者均为受控开发产物，真实模型发布与性能验收仍待完成。集成基线、历史保留方式、统一验证命令和后续交接见 [集成说明](docs/integration.md)。

本分支实现 v0.4 的 ExternalAPI 协调核心与受控生命周期测试。**不能作为生产发布器使用。** 二进制未装配真实发布屏障、批准 registry、Secret agent、网关 H1–H4、验证或 inventory 适配；默认 `DependencyMissing`、readiness 失败，不创建可调用发布。内存实现与伪网关插件仅位于 `_test.go`。

API group `serving.maas.example` 是保留占位域名，安装前必须经项目确认并统一替换 Go/schema/CRD/webhook/RBAC/客户端，不能只改一处。

后续 MySQL 受控增量见 [发布屏障、迁移和权限边界](docs/mysql-release.md) 与 [数据库验证报告](docs/mysql-verification.md)。存储库代码已实现，Operator 仍未装配真实内核/网关证据，不据此成为可调用服务。

开发与验证
----------

Windows PowerShell：

```powershell
./scripts/test.ps1
```

脚本将工具链及缓存放在 `.cache`，锁定 Go 1.26.0、controller-runtime v0.24.1、Kubernetes Go 库 v0.36.0，传递依赖见 `go.sum`。本机 PATH 的 Go 1.23.1 不满足依赖最低要求；Go 自动工具链下载需网络。此处是受控开发基线，目标集群版本与上线工具链补丁仍须另行批准。

```powershell
$env:GOTOOLCHAIN = 'go1.26.0'
go build -buildvcs=false ./...
go vet ./...
```

受限运行账户与目录所有者不同，Go 的自动 Git stamping 会触发 ownership 检查；本地构建显式关闭 stamping，交付提交 SHA 另记于任务评论，不修改用户全局 Git 配置。

临时 envtest 仅使用专属 API-server/etcd，不读用真实集群替代测试的配置：

```powershell
$env:KUBEBUILDER_ASSETS = '<已批准的临时二进制目录>'
./scripts/test.ps1 -Integration
```

Windows 没有可用二进制时，可在已有 Ubuntu WSL 使用 `scripts/test-envtest.sh`，预先将 Linux Go 工具链和 `setup-envtest` 下载的 1.36.0-linux-amd64 放入脚本指定的任务缓存。脚本不安装集群，测试通过 cleanup 停止临时进程。本轮已通过 CRD/CEL/resourceVersion、TLS webhook 拒绝未批准引用，以及真实 manager 在依赖缺失时写 finalizer/Degraded 状态的集成测试；完整可调用生命周期仍由 fake-port 测试覆盖。

实现边界
--------

- `api/v1alpha1`：CR 类型、不可变别名/来源、严格原始 spec 校验。嵌入架构师 schema 原文；路径正则为 RE2 做等价转换，再检查绝对路径/`..`。未知字段诊断不回显输入。K8s 的字段裁剪发生在 webhook 前，因此 kubectl 必须使用 strict fieldValidation，不能声称所有客户端未知字段都必然报错。
- `internal/release`：确定资源计划、finalizer 确认、先 inventory 后创建、UID 绑定/清理、受控发布、更新/暂停/恢复/新 epoch 回滚、共享 registry union、版本冲突和恢复。无推理接口，无预算/usage/Key 写入接口。
- ExternalAPI 仅编译 publication Ingress，并由显式 `PluginCompiler` 提供经过批准的 WasmPlugin。不会创建推理 Service/LWS/Pod/GPU；未实现 H1–H4 时没有生产插件替代品。
- SelfHosted 仅输出含 LWS/SGLang、预置权重引用与 GPU 数量的不可部署计划。没有经批准的 runtime/placement 模板时不创建真实工作负载，不下载权重。
- `BundleWriter` 是共享对象唯一写入角色，保留未受管字段/条目，使用完整目录快照和 K8s resourceVersion；不安装或删除 McpBridge。跨系统仍无原子事务，真实门禁必须验证最新 bundle 回执与新鲜度。
- `CommandClient` 只实现契约规定的 mTLS command POST，禁止重定向、不自动重放、不回显上游 body；`Observe/Read/Drain` 是内部 Go port，未擅自增加公开 HTTP API。
- 测试通过恢复相同 durable-port 替身模拟进程重启与提交 ACK 丢失；不等于数据库 crash recovery 或多副本线性化证明。详见 `docs/verification.md`。

需要实现的适配保证
------------------

`Control` 必须由 Go release-control/MySQL 实现：跨 namespace 的 gateway+alias 唯一、最新 generation/fence、不可逆 tombstone、候选/活动绑定 CAS、单调 epoch、唯一 validation intent、按 publication 固定票据 v3/终态事件 3.0。`RuntimeReady/GatewayApplied/AccountingReady/ValidationPassed` 必须来自完整、经过认证且未过期的证据，而非 K8s 对象存在。Operator 的状态不用于调用授权。

`Inventory` 必须耐久记录意图/实际 UID，Retire 在引用数为零且传输和 HELD/QUARANTINED slot 安全结束后 CAS；不能退款、释放未知金额/Token 或修改请求终态。实际 SQL 及数据库权限隔离由后续最小耐久调用内核交接实现，这里不复制账本。

`Bundle.Ensure/Remove` 必须操作所有 candidate/active/draining 引用的耐久目录，仅在安全引用撤销后移除条目。`BundleWriter.Catalog` 的所有权必须来自耐久清单，不能由前缀或用户标签推断。Secret resolver 只返回 UID/resourceVersion 等元数据，不读取或散列秘密正文；credential handle 由 H1 agent 提供。

运维与后续门槛
--------------

`config/crd` 和 `config/samples` 是未安装的契约资源。没有提供可安装 Helm chart、目标集群 RBAC、WebhookConfiguration 或 Secret；这些必须与获准 group、目标版本、mTLS 身份、故障关闭策略和 H1–H4 一起评审。仅把当前二进制打进 Helm 不构成发布功能。

首次真实验证前必须具备 MAAS-3/4/6 的 Key/三维预算/slot/request/唯一结算内核、验证 Key 授权及额度；随后由授权人员确认目标集群、Higress/模型/GPU/profile/镜像 digest/Secret 和版本矩阵。真实外部 API、GPU、MySQL 并发恢复、完整管理 API/Vue 控制台、Helm 安装升级回滚、运维观测仍在后续范围。任务保持 `in_progress`。

仓库初始化与出处
----------------

`git ls-remote --symref https://github.com/jianzi123/maas` 成功但无 refs；`multica repo checkout` 因无默认分支失败。依任务授权在任务目录建立无父提交的隔离分支 `agent/MAAS-11-controlled-release`，origin 保持已绑定仓库，不创建额外远端或强推，也不擅设 main 基线。没有独立 base 时不能形成有意义的 PR diff；以提交、分支及可下载源代码包交付。

需求附件：`01a1a610-35a1-79e8-aaa9-a30c0ea007d9`。架构契约包：`01a1a637-5727-730d-9662-60ec324daa42`；正文：`01a1a637-46e4-7513-adfa-a0630c1efc96`。`docs/contracts` 保留 v0.3 预算正文及 v0.4 架构，采用其状态和安全不变量，未把正文中的历史未启动文字覆盖本任务最新交接。

依赖依据：[controller-runtime v0.24.1 go.mod](https://github.com/kubernetes-sigs/controller-runtime/blob/v0.24.1/go.mod)、[Go 发布记录](https://go.dev/doc/devel/release)。
