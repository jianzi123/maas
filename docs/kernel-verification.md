# MAAS-3 受控实现验证记录

核验日期：2026-11-05 UTC。基线为 MAAS-11 `6302256`；实现和边界见 `docs/kernel-controlled.md`。这是局部实现证据，A01–A34 未完成运行验收。

## 本轮实际执行

| 验证 | 结果 |
| --- | --- |
| Windows/amd64，Go 1.26.0，`go test ./... -json -count=1` | 原始事件 50 pass、23 skip、0 fail（包含父测试事件；34 个通过的顶层测试）。23 个跳过项是未提供 Unix socket 的数据库场景；不能算数据库通过 |
| `go vet ./...` | 通过 |
| `go build -buildvcs=false ./...` | 通过 |
| Python `python -m unittest discover -s tools/perf -p 'test_*.py'` | 41 项通过，5.397s；没有改性能工具或既有契约快照 |
| WSL Ubuntu-22.04，Linux Go 1.26.0，`bash scripts/test-controlled.sh` | MySQL 8.4.7 + Redis 6.0.16，35 个数据库/受控传输场景全通过；发布组 8.891s，真实内核及 relay 组 21.236s |

最终联合组的 35 个场景构成为：原发布组 13、真实内核 14、发布者操作真实核心表的窄权限 1、受控 relay 6、真实 Redis/MySQL 耐久限流见证 1。原发布组的 13 项仍保留其历史 `_test.go` 核心夹具；**新增 22 项使用本次真实业务内核和实体核心表**，不能把两组的证据范围混为一谈。

原始输出为随交付附上的 mysql-tests.txt 和 go-tests.json。没有使用 CI 结果替代本地验证，也没有等待 GitHub CI。

## 核心场景

| 触发 | 实际断言 |
| --- | --- |
| 同票据重放 | 仅一个 request、一次三维预留和两条速率 scope 见证，不返回旧授权成功 |
| 双 Store 副本竞争一个固定 slot | 一个成功；另一方为锁竞争/容量拒绝，没有跨副本进程计数 |
| 撤销后另一副本使用旧 epoch | 主库拒绝，既不建档也不预留 |
| Token 限额不足 | 请求、Token、金额、slot、rate witness 整笔回滚 |
| 缺用量、重复/矛盾事件 | 只保留一个终态/汇总，Token 140 和金额 520000 转未知 held，实际仍为 null |
| 迟到关闭证明及 slot 复用 | 可回收旧 allocation；预算/事件不变；旧日志不能释放更高 fence 的新 slot |
| 冻结价表、分类与一次舍入 | 合成 TST 请求预算 Token=19、金额=72800 atomic；保留上游 total null，不伪称上游报告 |
| no-send 证明错配 | 错 allocation 拒绝；只有原绑定的受信测试证明在终态前才能释放预留 |
| 暂停、删除与准入竞争 | 关门禁不能越过持锁准入提交；之后新准入拒绝；tombstone 不可复活；不安全 slot 阻止排空 |
| 新 Store 恢复 | 原截止前不能回收/接管；原截止后增 owner fence 并结算 interrupted；旧 owner 拒绝，未知 held 保留 |
| 实际 commit 后注入 ACK 错误 | 原 request/event 可查；授权重放拒绝；计量同 ID 重投不重复结算 |
| 使用超过预留 | 保存实际值和 overrun，冻结 Key 及相关能力修订；同一能力不能换新 publication 再启用 |
| 最小权限身份 | 真实 publisher 能共享锁 guard、关闭门禁、读真实排空；不能改 Key/预算/request/slot/终态、不能 DDL；slot 安全释放后可排空，held 仍不变 |
| 非流式/流式、取消、断流、缺 usage、结算故障 | 成功体/DONE 等唯一终态确认；writer 取消传播到受控网关 context；未确认关闭仍 QUARANTINED；结算故障没有正常 DONE |
| 真实 Redis 重放、marker 缺失、丢桶、blocked epoch | 缺 marker 拒绝；重复 request 拒绝；丢桶后 MySQL 同窗上限仍拒绝额外准入；blocked epoch 不自动重开 |

测试中的 Token 上界、TST 币种、价表、配额、期限、模型和身份都明确为合成 profile，不代表真实配置或第三方模型价格。

## 仍是测试替身的边界

- `fixtureProofs` 只替代 Higress/validation 证明生产者；实际 xDS、生效副本集合、Secret agent 通道、H2 sealed/transport-close 和签名 registry 均未运行。用 fixture 的关闭证明不会成为生产 Ready。
- 大部分内核场景的 Redis 许可来自 `_test.go` fixture；另一个独立场景实际使用 Redis Lua/TIME 和 MySQL 耐久见证。没有验证生产 Redis HA/运行身份切换、全量下界重建协调器。
- relay 场景的 HTTP server 替代 Higress，只有 Go 内核、数据库、转发/流处理及终态代码是真实实现。它没有验证 Higress 的实际选路、供应商生成停止或 GPU 容量恢复。
- 新 Store 代表无进程内状态依赖的重新实例化，不是 OS 级进程崩溃注入。ACK 故障在真实 MySQL COMMIT 之后由测试 driver 注入，不是实际网络包丢失。
- H1 精确版本缓存、H3 签名/身份/时效及 H4 消费器/重复头/提交未知的测试是适配库测试，不能称作网关生效证据。

未执行：DB 断电/崩溃/HA/备份恢复、真实 Higress 安装与 H1–H4、目标 K8s/Helm、真实内网或供应商模型、GPU/权重、性能/负载与 race detector、完整管理 API/Vue/统计页面、受保护 validation、V01–V16 或 A01–A34 整体运行验收。本轮未重跑 envtest，控制器/CRD 实现未改。

## 依赖和清理

Go Linux 官方归档 SHA256 `aac1b08a0fb0c4e0a7c1555beb7b59180b05dfc5a3d62e40e9de90cd42f88235` 与 go.dev 下载清单一致。MySQL 使用已有获准的官方便携 8.4.7 缓存；Redis 来自 Ubuntu Jammy 包 `5:6.0.16-1ubuntu1.2`，共享库只解包到任务缓存。这些是本轮测试版本，不是已批准部署矩阵。

MySQL 使用 `--skip-networking --mysqlx=OFF` 和私有 socket/datadir，Redis TCP port=0、私有 socket、无持久化。测试随机 schema/账号在退出前删除，服务器按记录的精确子 PID 停止，自有 datadir 清除，末次进程检查未见本轮 mysqld/redis/go-test 残留。Redis 会改写进程标题；本轮修正清理脚本为核对实际 executable 与父 PID，早期两次测试的自有进程也已按精确句柄收尾。未安装系统服务或留下长期应用。

## 继续实施所需输入

| 门槛 | 当前状态 |
| --- | --- |
| MAAS-2 共享 DDL/guard/LockActive/证据接点复核 | 尚无本轮代码级差异结论；当前装配只用于受控验证 |
| Higress 候选版本和补丁仓库/交付方式 | 按 v2.2.5 抽读；H1/H2/H3/H4 外部写入须 Mika 协调，无跨仓库写入 |
| 实际模型、endpoint、capability/profile、上界、价表/币种 | 尚未登记真实获准输入，不从测试值生成默认 |
| 凭证渠道/Secret UID、版本和实例身份 registry | 尚缺安全装配；不在任务中请求或披露原值 |
| 调用额度、预算周期/数值、validation intent 与授权 | 尚缺真实输入；本轮授权仅临时依赖与受控上游 |
| 目标环境/版本、部署与真实调用授权 | 本轮没有；未创建 kind/k3d、未调用供应商、未用 GPU 或下载权重 |

上述剩余门槛与 MAAS-4/6/11 共用此内核，不重复启动后台任务。MAAS-3 保持 in_progress，待联合阶段后续装配及最终验收。
