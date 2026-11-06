# 本轮受控接续验证

基线是 PR #2 的 `4f3eb93`。功能、接口、部署边界、C01–C16 映射和保留修订反馈见 `controlled-api-continuation.md`。本文件记录新增交付，原 `kernel-verification.md` 保留为上一轮记录。

## 运行与证据

- Go 1.26.0/Windows：`go test ./... -json -count=1`，52 个 pass、37 个 skip、0 fail（含父测试事件；skip 为未提供 Unix socket 的数据库场景及专用子进程入口）。原始 go-tests-continuation.json 附后。
- `go vet ./...`、`go build -buildvcs=false ./...` 通过，含新 `cmd/control-api`；没有启动长期服务。
- Python 离线性能工具 41 项通过（1.771s），没有切换其终态 3.0 消费版本。
- WSL Ubuntu-22.04，便携 MySQL 8.4.7 / Redis 6.0.16 / Linux Go 1.26.0：`bash scripts/test-controlled.sh`。48 个数据库/受控链路场景通过，包含此前 35 项及新增 13 项；不是把两个轮次相加。原始 mysql-tests.txt 附后。
- Schema 提取独立核对：草案中 25 个依赖定义与本仓库转换后的定义一致，只重定位 `$ref`。来源及 SHA256 见 management-provenance.json；未用无关发布正则的限制弱化这些定义。

48 项构成：发布组13＋既有内核14＋发布身份1＋relay8＋硬截止2＋真实 Redis 原见证1＋查询/CAS1＋持久候选验证/撤销竞争1＋最后预算双副本1＋完整重建1＋写后到期/跨cluster1＋管理写ACK1＋真实Redis重启1＋owner进程退出恢复1＋HTTP管理API1。普通子进程入口 TestOwnerCrashChild 在主进程明确 skip，其行为由 owner 进程恢复场景实际启动/收集，不当额外通过场景。

## 新增关键断言

| 场景 | 结论与实际限制 |
| --- | --- |
| 写后最终 gate 耗时超过票据期限 | 到达第二次 gate 后过期；新发 DB 时钟捕获，request/全部预留回滚。修复 C04 真实实现缺口 |
| 双副本最后请求额度 | 两个可用 slot、额度只剩1，一方成功，另一方锁/额度拒绝；仅1个 request/slot，不靠进程计数 |
| 发布者真实 role/default role | 新连接 CURRENT_ROLE 生效；读真实 guard/证明窄投影并关闭/排空；无法改 Key/预算/request/slot/终态或 DDL。H2 释放证明仍单独用 fixture，不扩大 publisher 权限 |
| 候选验证 | 普通 serving Key/purpose 不能调用候选；专用 intent 绑定唯一原 request_id；无 runtime/gateway proof 拒绝，同一 request 重放拒绝；真实核心终态成功同事务形成 validation_receipt 后才能 CAS 激活 |
| 证明撤销与准入竞争 | 持 guard X 的准入未提交时撤销 NOWAIT 拒绝；之后撤销成功，后续新准入拒绝。无锁外 IO 包在主库事务内 |
| Key 管理 | 真 HTTP＋主库：显式创建、无秘密元数据、401/403、预算 CAS、旧 revision409、撤销、缺 Key404、依赖503；秘密只在创建响应中返回，无自动重试 |
| 精确回查 | recorded/unknown、参数互斥、cursor绑定；同快照读取原请求及 allocation，旧slot被复用仍按原释放日志显示released，held不变 |
| Redis 完整重建/实际重启 | 真的启动/停止/重启测试自有 Redis PID，实例 run_id 改变；重建前拒绝，主库同窗下界恢复后才 ready；ready epoch 禁止重建清零 |
| Go owner 崩溃恢复 | 子进程准入 COMMIT 后 os.Exit(23)，未执行终态清理；主进程确认已建档，过原 deadline 后接管，唯一 interrupted，保留未知 held。不是 MySQL 崩溃/HA |
| 管理写 ACK 丢失 | 服务端真实 COMMIT 后 driver 注入；创建不给 secret，元数据可查；预算 CAS原revision不能重放，撤销事实可查 |
| 累计usage/硬截止 | 单调快照取最新而非相加，倒退保守失败；流中和非流式读体截止均持久 timed_out，未知用量和 QUARANTINED 保留，无正常 DONE |

## 证据范围和剩余门槛

真实部分为 MySQL/InnoDB、role/default role、Redis/Lua/TIME/run_id、HTTP server、Go owner 独立进程及实际内核代码。proof verifier 与 H2 reporter、relay 中的 Higress 是测试替身；Kubernetes SecretReader 是实际 client 实现，用 fake client 验 namespace/UID/RV，不代表目标 K8s/RBAC 实测。issuer/机制/真实 xDS/全副本及 Secret 本地通道仍需安装适配。

默认生产 Operator 仍 DependencyMissing；control-api 不注册推理路由。未写其他仓库，未部署目标集群，未请求供应商、GPU、权重或付费资源。未执行 MySQL 断电/HA、完整登录/浏览器联调、真实网关验证或 A01–A34；没有把本轮 Go owner/Redis 进程测试写成这些结果。

测试使用各自随机 schema/账号、私有 Unix socket/datadir、TCP禁用的临时 Redis/MySQL。测试进程同步退出，defer/trap 清理；仅核对/终止自己记录的子 PID，未影响 QA 在其他工作区的测试实例。原始日志只含合成 profile/数值，不含真实 Secret 或 Key 原值。依赖二进制缓存保留，私有测试数据和凭证不保留。

MAAS-4/6 的受控接口已有可复核实现；完整功能验收与前端/QA 接续独立保留，不因一次受控 API 测试通过改为 done。保留修订读取当前返回503，真实证据生产和 SelfHosted/shared runtime 沿 MAAS-11 原 PR 接续。Mika 收到一次本轮新事实通知后，无新增事实不重复唤醒。
