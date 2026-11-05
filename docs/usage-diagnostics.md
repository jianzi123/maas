# QA-001 / QA-002：受控修复与复测说明

依据 MAAS-2 原清单 v2（2026-11-05；MAAS-7 触发线程）。当前已合入原 PR #2 的 `6dc39149a9d44b1bcca57cec59a0920f535ac1eb`（含既有控制 API/P1/恢复增量），继承原 MAAS-3 内核 `4f3eb9358f26ebab637a549b795651171d3b924f` 和发布提交 `630225697b8fcdd5e4d2f3ccd2a232e4d6b5259a`。终态 3.0、票据 v3、ObservationEnvelope 1.0 保持不变，D1 3.1 未切换。本文是实现/开发自测交付，独立 QA 与 A01–A34 验收尚待完成。

## 行为与边界

relay 解析首个有效 usage 后，先提交独立 receipt，再转发该帧；EOF、客户端写失败、显式取消、截止、解析非法或冲突另追加 termination。五项计数保留原值与 null，不累计快照，不覆盖先前快照。相同重复快照复用已保存事实。

断流前仅收到分片，不能据此证明最终计费值。这些诊断不传入失败路径的 Final.Usage。QA 合成样本保存 12/7/19/4/3，异常终态的五项权威计数仍为 null、missing_reason=not_provided；Token held=140、金额 held=520000 atomic、请求计1次。TST 价表及所有数值是夹具，不能用作真实默认。正常完整响应及原正常流完成语义沿用原实现；正常 DONE 等唯一结算成功后才发。

以原 sendCtx 保存的首个终止原因为依据，在本地清理 cancel 前读取；DeadlineExceeded（含更早父 deadline）对应 timed_out/upstream_timeout，显式 Canceled 对应 cancelled/client_cancelled。普通 EOF 保留原 interrupted/owner_lost 粗分类；精确原因在诊断中。writer 失败的诊断是 client_write_error，不能据此声称用户点击了取消。诊断提交期间到达截止会停止继续转发。HTTP 非2xx、未形成 EOF 的连接建立失败不伪造 parse_invalid/eof 诊断；仍保留原财务终态/held。

receipt 或 termination 写入失败时停止正常结果转发，用独立限时上下文尝试同一个保守终态，不发正常 DONE、不重发生成。诊断 COMMIT 的 ACK 未知只按原 ID/hash 从主库读回确认。终态 COMMIT 未知仍沿原事件 ID 查询/恢复，不能重试生成。写失败测试的通过仅说明故障关闭行为有效，不能说丢失的诊断已经保存。

## 迁移、权限和原快照

`kernel.Migrate` 依次处理原内核 v1、已发控制迁移 v2、新增诊断 v3；各阶段沿用既有安装锁。v1/v2 SQL/checksum 保留；诊断 v3 有独立的 Applying/Applied 与 SHA256，支持 DDL 中断续跑，拒绝 checksum 冲突及无版本表接管。管理员显式执行迁移；未向任何目标环境执行。

- `request_snapshot_digests`：在原 Admit 的同一个事务内，对准入时原 Snapshot 的 JSON 字节计算并保存 SHA256。没有用 MySQL 后续规范化的 JSON 或恢复后重建对象冒充原字节。历史请求缺原摘要时诊断写入故障关闭，不回填伪造摘要。
- `request_usage_diagnostics`：追加式内部记录。唯一键 request_id/owner_fence/sequence；同键同规范化内容幂等，异内容、旧 owner/fence、错误原摘要/publication/route 等绑定拒绝。已保存的旧 owner 记录仍可读；诊断不获得结算权。
- Schema 原样来自 v2 的 UsageReceiptDiagnostic 0.1-draft.1；SHA256 `d35c305ab02acae560c7a8423e672b4d1b50f837c7fc314a75b20628fcb88a4a`，内部复制件逐字节一致。记录不含响应正文、用户文本、Key 或上游秘密。
- 每请求最多64条、每条规范化 JSON 最多4096字节（JSON总量最多256 KiB，数据库/索引开销另计）；为 termination 预留1条。超限故障关闭，不静默截断。
- `config/mysql/kernel-permissions.sql` 增加核心 SELECT/INSERT，诊断无 UPDATE/DELETE。诊断 reader 仅 SELECT；publisher、Operator 和 slot worker 无新增授权。临时 MySQL 用户测试验证核心追加、reader读取及更新/删除拒绝；生产 role/default role 装配仍待运维验证。

保留期未获批准：当前没有自动删除/TTL作业，旧诊断不被清理，不自行填默认保留天数。批准的审计保留策略及相应部署证据仍是关项条件。本轮未将开发自测称为 QA-001 已独立关闭。

## 诊断读取入口

内部 Go 入口为 `Store.ReadUsageDiagnostics(ctx, originalRequestID)`；读主库、按 owner_fence/sequence 排序，重新校验 Schema 和记录 hash。Store 重建后可读，表不可用返回错误。旧请求/所有权仍按原绑定解释。

受授权的诊断只读身份也可执行：

```sql
SELECT record_json
FROM request_usage_diagnostics
WHERE request_id = ?
ORDER BY owner_fence, sequence;
```

这是内部读取入口。没有增加公开 HTTP 路由、FE-R03 字段或财务用量列；公开消费者形状/鉴权需要 Mika 协调。原控制 API 的受控 HTTP 子集沿6dc3914保留并复跑；完整 CR 历史/回滚、浏览器停止及严格消费者运行门槛仍按 v2 原清单逐项取证。

## 复现入口

既有获准便携缓存到位后，在仓库 Linux/WSL 环境执行：

```sh
MAAS_TEST_PATTERN=TestMySQL bash scripts/test-controlled.sh
```

脚本仅使用独立临时 MySQL/Redis 的私有 socket，退出按自有 PID 清理进程和数据。真实数据库参与准入、诊断、预算、事件与汇总；Higress 传输、proof producer/profile 仍是明确夹具。

新增场景位于 `diagnostics_mysql_test.go`（8）、`relay_diagnostics_mysql_test.go`（10）、`relay_failure_mysql_test.go`（12）、`relay_diagnostic_cause_mysql_test.go`（2）。另有首个 context 原因的普通 Go 单元测试。QA 原始 TestQADeadlineAfterHeaders 从原 ca9fcdd 源码附件临时复制运行，结束已删除，未修改独立 QA oracle 或测试目录。

Go 全仓回归、vet、build 的环境：Go 1.26.0 Linux/amd64，MySQL 8.4.7、Redis 6.0.16；依赖来自既有授权缓存。运行结果及精确计数见随交付的 verification.json/原始日志。

## 证据限制和工作流

所有运行是开发自测、临时真实数据库与受控 HTTP 传输，不能代替真实 Higress 选路、模型生成停止、GPU 容量、集群/Helm、OS 崩溃、DB HA/备份恢复或生产权限证据。Store 重建是数据库重读，COMMIT 后 driver 注入是 ACK 未知夹具，不是实际断网/HA。诊断同步写入的性能开销未做模型压测，需后续沿原性能计划测量。

原 MAAS-3 另一个实现运行仍活跃，负责完整管理/API/真实接点等范围。本增量在独立工作树保留原内核与历史，提供可审提交/补丁供原 PR #2 集成，不并发覆盖原分支，不新建重复 PR。MAAS-7 保持 in_progress，MAAS-3 继续原实现工作流，独立 QA 按实际交回 SHA 复验后才可关闭 QA-001/002。

早期记录保留：新增夹具一度因 Expires 晚于缩短后的 Deadline 被准入拒绝；修正合法时序后旧基线稳定复现 interrupted/timed_out 差异。扩展 HTTP 夹具未读请求体导致服务端等待断连而清理超时，已修正为消费请求体并设置有界等待，writer 覆盖 Write/WriteString。新测试的 int64 指针构造编译错误已纠正。上述失败不计入有效通过样本，原始失败记录另存。

## 早期基于4f3eb93的开发记录（最终集成结果见下节）

| 检查 | 结果 |
|---|---|
| 最终真实临时 MySQL/Redis 受控组 | 68/68：原35＋本增量32＋QA原始截止用例1；发布包7.629s、内核包49.924s |
| Linux Go 全仓普通回归 | 55个通过测试事件、55个缺省skip、0 fail；7包通过。含父/子测试事件，不能和数据库叶子场景数相加 |
| go vet ./... | exit 0 |
| go build -buildvcs=false ./... | exit 0 |
| 协议及原 v1 SQL 快照 | 与4f3eb93一致；未修改性能消费者/契约 |
| 清理和版本 | 六个记录的自有datadir消失；本任务MySQL/Redis/Go可执行路径下无存活进程；实际版本Go1.26.0 / MySQL8.4.7 / Redis6.0.16 |

此前66项全量也通过；随后补齐HTTP状态/未建立传输的两项归因边界，以本表最后68项为最终证据。全仓默认skip不算数据库通过；父测试事件不重复计为场景。性能离线工具、race detector、envtest及跨语言历史检查本轮未重跑。

最后核对时原MAAS-3工作流仍活跃，本增量不直接覆盖其PR分支。代码和证据按本次实际提交交回原负责人集成、原QA独立复验；未改MAAS-7/MAAS-2状态，未关闭两项QA或A01–A34。

## 最新集成基线和最终结果

原PR #2已前进至6dc3914。本分支通过合并保留其完整历史、控制迁移0002、API/P1、Redis/owner恢复、TLS固定和单调累计快照；诊断使用0003_usage_diagnostics.sql，避免覆盖已发迁移。早期011c465仅是4f3eb93上的独立候选；不提供其诊断v2到当前控制v2/诊断v3序列的自动迁移，checksum冲突继续拒绝，不能改账本或重写checksum。

绑定比较保留原Input字节，包括空Purpose；仅绑定投影沿用purposeOf。Core.Recover在交接owner/fence的事务内确认原receipt是否已保存，已收分片时最终usage.missing_reason=not_provided，财务仍未知且held保留。已保存的旧owner记录可读，旧fence迟到写入拒绝。

原6dc3914的合法单调累计快照继续逐次保存不同receipt，不求和；下降/矛盾快照故障关闭。原正常流cumulative与decreasing回归均通过。

| 最终检查 | 实际结果 |
|---|---|
| 数据库/受控场景 | 88/88＝原48（已含原35）＋新增32＋QA v2原8项数据库场景 |
| QA v2判因函数 | 4/4，未生成请求；包含子截止先发生、父取消后发生的确定顺序反例 |
| 本角色开发复跑QA v2原oracle | 12/12；未改断言、未skip。这是开发复跑，仍需原QA按新SHA独立复验 |
| 最终全仓Go普通回归 | 57个通过测试事件、69个数据库缺省skip、0fail，8包通过；不和SQL叶子场景数相加 |
| vet / build | 均exit 0 |
| 最终受控包耗时 | 发布7.417s、内核82.077s、控制API1.239s；不是模型延迟或吞吐 |

QA源码取自ba6dcd01801675da28cb34df59961fd7bb513abe，临时编入后已删除。实际只读适配入口：

```sh
export MAAS_QA_DIAGNOSTIC_READ_SQL='SELECT record_json FROM request_usage_diagnostics WHERE request_id=? ORDER BY owner_fence,sequence'
export MAAS_QA_SNAPSHOT_HASH_SQL='SELECT snapshot_sha256 FROM request_snapshot_digests WHERE request_id=?'
MAAS_TEST_PATTERN='TestMySQL|TestQA' bash scripts/test-controlled.sh
```

该命令还需原QA的临时测试源码和v2 Schema文件；不把QA目录复制为产品代码。两条SQL均仅一个原request_id参数，在QA的独立连接/只读事务执行。已验证receipt先于第一帧、五项计数、原owner/fence/冻结摘要/调用绑定、EOF和writer实际原因、唯一终态/汇总、原allocation释放和slot复用不退款。

集成首次验证曾因主动改写空Purpose导致state_conflict，已修正并保留失败记录。最终迁移1/2及既有协议/消费者快照与6dc3914逐文件保持；3.0/ObservationEnvelope1.0未改，D1不切换。最终SHA和清理证据见交付包verification.json；68项早期记录不再充当最新集成证据。
