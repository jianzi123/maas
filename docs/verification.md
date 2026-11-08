MAAS-11 受控实现证据（2026-11-04）
===================================

本报告只描述任务目录内执行的测试。测试模型、profile、endpoint、credential handle 和发布控制器证据均为明确标注的测试数据；没有读取真实 Secret、发送模型请求、下载权重、创建 GPU 工作负载或写入目标集群。

已执行
------

Windows/amd64，Go 1.26.0：`go test ./... -json -count=1` 通过 23 个顶层测试、含子测试共 39 项，0 失败；`go vet ./...` 与 `go build -buildvcs=false ./...` 通过。自动 VCS stamping 初次因沙箱 Git ownership 失败，后续构建显式关闭该选项，未改用户全局配置。

测试包括严格 schema/来源互斥/路径与 GPU 拓扑/不可变字段、webhook 故障关闭、mTLS command 客户端/禁止重定向/不回显 body、finalizer 持久后才建资源、重复 reconcile/新 controller 实例、创建与激活 commit ACK 丢失恢复、资源版本冲突、候选 generation 不继承 Ready、唯一 validation 意图、新 publication/epoch 更新和回滚、Recreate 先排空、暂停/恢复、删除等待安全传输与 slot、同名新 UID 保护、用户/共享资源清理白名单、Secret 元数据版本变化、双模型共享项和目录过期/版本冲突。

恢复/别名/epoch/validation/排空测试使用 `_test.go` 内存 port 替身，证明协调器调用顺序及接口边界；**不证明 MySQL 持久性、并发线性化、实际 slot 回收或真实账本写集**。未知 Token/金额不属于 controller 写接口，实际 SQL/权限/恢复写集隔离留待耐久内核验证。

Ubuntu-22.04 WSL/linux-amd64：经批准下载临时 Go 与 envtest 1.36.0 二进制，`scripts/test-envtest.sh` 最终通过 `TestCRDCELAndResourceVersion`（10.156s）。覆盖实际 CRD 安装/CEL 不可变规则/RV 冲突、真实 TLS webhook 对未批准 endpoint 的拒绝，以及运行中的 controller manager 持久化 finalizer、在无生产适配时投影 Degraded 且 Callable=False。测试显式 `UseExistingCluster=false`，使用临时 etcd/API-server，cleanup 停止 manager 和临时控制面。真实可调用生命周期与账本/网关证据仍未接入。

本轮不把 fake-client 通过当 API-server 通过，也不把临时 API-server 通过当 Higress、GPU 或生产集群通过。

真实 manager 扩展测试曾揭示：未发布状态的 `activeGeneration=0` 不符合原契约（应为 null）。已改为 `*int64` 并增加以架构原始 JSON Schema 验证空活动态的回归测试，没有放宽 CRD。

契约原件哈希（源附件与仓库副本逐字节一致）：ModelRelease JSON Schema `84bb8a5d9f7a86206143ec6462d9a79277dd181487473031226f041334cebc3a`；CRD `1169272473c5fa8a484245cb82fc0a4b1c32db4a759f33e4add1fcc389ae1aa1`。

A25–A33 可追溯范围
----------------

| 项 | 本轮证据 | 未执行或未实现 |
|---|---|---|
| A25 | 两来源严格 schema、参数/拓扑/路径、不可变规则；CEL 实际 API-server；真实 TLS webhook 拒绝未批准依赖；测试 port 的跨 namespace alias 排他 | 真实批准目录/RBAC、别名 MySQL 唯一锁与并发 |
| A26 | SelfHosted 不可部署计划，LWS/SGLang/size/GPU 数量/权重与 profile 引用；确定编译与无 CR ownerReference | 工作负载模板、LWS/SGLang 安装、GPU、加载、真实 Ready |
| A27 | ExternalAPI 编译及受控生命周期不生成 LWS/推理 Pod/Service/GPU | 真实供应商调用、Go/Redis/MySQL 预算调用链、H1–H4 |
| A28 | 实际 manager 缺依赖时不可调用，当前 generation 与活动 revision 分离，fake 回执后才能激活；空活动态符合原 schema | 真实实例集合/receipt 新鲜度、数据库屏障与真实 validation |
| A29 | API-server 实际 RV 冲突；fake 重复/重启/过期 generation/ACK 丢失/漂移；inventory 意图和实际 UID 恢复 | 多 controller+MySQL 崩溃并发、真实集群漂移 |
| A30 | fake 更新、Recreate 先关准入/排空、新 publication 与更高 epoch 回滚，旧 active 单独投影 | 管理 API 的历史快照/If-Match 回滚、真实长流/价表与权重保持、GPU 容量 |
| A31 | fake 关准入→安全 drain→共享条目撤销→Retire/UID 删除→inventory 确认→finalizer；用户 Secret/PVC/共享对象禁止删除 | 真实 in_progress/HELD/QUARANTINED 安全证明、独立未知预算写集和恢复、强制清理 |
| A32 | 双模型共享项保留、未受管字段保留、共享 writer 的 RV 冲突返回、Secret resourceVersion 触发新 revision | 真实 McpBridge/Higress 多副本、Secret agent 版本快照、跨来源隔离真实请求 |
| A33 | 临时 API-server 安装 CRD，显式依赖接口和缺依赖关闭、开发脚本与版本锁定 | 正式 group、Helm/RBAC/webhook 部署包、目标版本矩阵、安装升级回滚 |

A01–A24 未做真实运行验收；票据 v3/终态事件 3.0/ObservationEnvelope 1.0 仍按 MAAS-2 契约，由后续真实调用适配实现，不新增旁路或另一份计量账本。A34 无 GPU/性能/优化结果。

后续交接
--------

Mika 协调耐久 release-control/调用内核与 H1–H4 的获准实现及接口联调；架构师继续维护共享契约。真实验证前需最小 Key/三维预算/slot/request/唯一结算内核、批准模型/版本/profile、Secret 安全渠道、专用 validation Key/额度和目标授权。完整管理 API/Vue、Helm 包、运行观测、超时进度投影与真实清理恢复仍待实现。本阶段成果可评审，整个 MAAS-11 保持 `in_progress`。
