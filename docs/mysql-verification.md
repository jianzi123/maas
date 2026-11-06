# MAAS-11 MySQL 受控增量验证

从 `9744fc4` 继续同一草稿 PR #1。实现说明、共享事务接点及复现步骤见 `docs/mysql-release.md`。

## 实际执行

| 环境/命令 | 结果 |
| --- | --- |
| Windows/amd64，Go 1.26.0，`go test ./... -json -count=1` | 25 个顶层测试、含子测试共 41 项通过，0 失败；MySQL 集成组因 Windows 未指定临时 socket 明确 skip 1 项 |
| `go vet ./...` | 通过 |
| `go build -buildvcs=false ./...` | 通过；未改变用户全局 Git 设置 |
| Python `unittest discover -s tools/perf -p 'test_*.py'` | 41 项通过，2.847s；原性能工具代码及契约快照未改 |
| WSL Ubuntu-22.04/linux-amd64，便携 MySQL 8.4.7 + Linux Go 1.26.0，`scripts/test-mysql.sh` | 数据库专项 13 场景全通过（suite 6.857s），另 2 项边界单元测试通过 |

真实 MySQL 来自官方 HTTPS 便携包，官方 MD5 已核对；libaio 只解包到任务缓存。测试独占随机 Unix socket/datadir，未安装系统服务、未打开 TCP、未连接已有数据库。测试创建/删除随机 schema，EXIT 停止本脚本记录的进程并删除自有 datadir；日志保留于 artifacts。

## MySQL 专项场景

| 场景 | 本轮结论 |
| --- | --- |
| 重复 Observe / 新 Store 恢复 / dependency rotation / 回滚 | 候选持久且重试复用；新意图使用新 publication，更高 epoch，旧 generation 被拒绝 |
| 激活 CAS / command hash / 旧命令重投 / 已关闭 publication | 精确匹配 fence/revision/expected-active；同 ID 同 hash 不重复切换，不恢复旧 active；关闭后的恢复分配新 publication |
| 缺失、过期、绑定不符及未就绪证据 | 不能激活，不留下已激活 publication |
| tombstone / 跨 namespace alias / 新 CR UID | 删除立即持久关闭；同 UID 不可复活，清理前不释放 alias，清理后新 UID 独立 |
| Planned→UID 补绑→Retiring→Removed | pending 意图重启可读，禁止不同实际 UID 替换、Retiring 重新绑定及错误 UID 清理 |
| 传输、HELD/QUARANTINED 和未知预算 | 非零 in_progress 或不安全 slot 时禁止 Retire；满足关闭后可清理，实际 SQL 查询确认未知占用、原 allocation_fence 和请求终态未改 |
| 唯一准入事务与关闭竞争 | 核心先持有容量排他锁、同事务 LockActive；并发关闭冲突，核心事务结束后才能关闭，后续 admission gate 拒绝 |
| 并发 generation | 主库行锁与 fence/epoch 不回退；没有增加进程内计数作为另一真源 |
| 并发激活 | 两个同候选竞争者只有一个成功，成功操作和激活记录均只有一份 |
| 迁移 checksum 与中断恢复 | checksum 冲突拒绝；Applying 阶段缺表能接续；无版本归属的同名表不接管 |
| 最小运行权限 | 实际创建低权限测试身份，能操作发布表；只授 SELECT 的核心 guard/证据见证足够取共享锁；核心占用/slot/guard 写、DDL、历史删除或修订篡改均被 MySQL 拒绝 |
| 计数耗尽 | fence 到整数上界后拒绝新意图，不回绕或生成额外 publication |
| 提交 ACK 丢失 | 仅在测试 connector 中让真实服务端 commit 成功后向客户端报错；Observe/Activate/UID Bind 恢复不重复分配、激活或替换 UID |

## 证据的实际边界

这些场景运行真实 MySQL/InnoDB SQL、锁、约束、事务提交和权限；**Kernel guard/request/slot/未知占用表、网关/validation 证据生产者仍是 `_test.go` 中的受控夹具**。没有另建生产业务账本，也没有将测试证据接入 Operator。

新 Store 实例用于验证无进程内状态依赖；ACK 故障由测试 driver 在真实 commit 后注入。没有执行真实网络包丢失、数据库断电/崩溃、binlog/HA 切换、主库故障注入或目标环境升级回滚，不能据此宣称这些通过。真实业务核心的 DDL、证据签名/版本/新鲜度机制和 slot 安全结束仍待联合实现验证。

本轮未重跑 envtest：控制器/CRD 行为未改，新存储库尚未装配。原 envtest 记录仍是 `docs/verification.md` 中的历史证据。真实 Higress H1–H4、Secret agent、validation、供应商、GPU/权重、管理 API/Vue/Helm 及 A01–A34 完整运行验收未执行。

## 评审入口

- `internal/release/mysqlstore/schema/0001_release.sql`：仅发布表和约束，迁移不触碰业务表。
- `internal/release/mysqlstore/control.go`：行锁、generation/fence、活动 CAS、fresh evidence、不可逆 tombstone、原核心事务的 LockActive。
- `internal/release/mysqlstore/inventory.go`：完整资源身份/实际 UID 和安全 retirement；拒绝共享 runtime 复用。
- `internal/release/mysqlstore/migrate.go`、`config/mysql/release-permissions.sql`：显式迁移、恢复和权限模板。
- `internal/release/mysqlstore/mysql_test.go`：全部实际数据库场景；测试专用 core/ACK 注入代码不在生产实现中。

默认 Operator 仍故障关闭。下一步由架构师/Mika 复核新增共享事务接点与具体核心 DDL/窄权限，再联合接入唯一调用内核和 H1–H4；任务保持 `in_progress`。
