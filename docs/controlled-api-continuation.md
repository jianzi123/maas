# MAAS-3/4/6 受控 API 与恢复接续

基线：PR #2 原 head `4f3eb9358f26ebab637a549b795651171d3b924f`，依赖 PR #1 `6302256`。本增量继续同一分支/PR；未改写发布侧分支或七表迁移。原 `docs/kernel-verification.md` 是上一轮历史证据，本轮结果以本文件及新原始附件为准，不把旧 35 项与重跑结果累加。

依据：MAAS-2 C01–C16、联合清单收口修订2、`v0.4.2-draft.1`（附件 `01a1ab52-be21-7667-87cf-fcee92844e9c`）。票据 v3、终态 3.0、预算计划 1.0 不变。查询草案的 Key/请求/汇总 Schema 按依赖闭包提取并仅重定位 `$ref`；无关的发布正则不混入 Go 校验器，原契约保留。版本/哈希记录在 management-provenance.json。

## 本轮实现与 P1 接点

| 接点 | 本轮结果与实际边界 |
| --- | --- |
| C02/C03 | 沿用同主库/cluster 的 guard X→release S→Key→budget→rate→request→slot。新增最后预算的双副本竞争、跨 cluster 拒绝；没有重建调用内核 |
| C04 | 修复实际缺口：最后一次 gate/证据查询也可能耗时，现于其返回后再发独立 DB 时钟，重验票据和预算/速率窗口。测试明确到达第二次 gate、在写后过期，整笔回滚无 request/预留 |
| C05/C11 | 增加持久 publication_proofs：验证器先在锁外核验，持同一 guard X 后核对完整 profile hash、时间并登记；撤销同 guard 同步。publisher 只读元数据和 validation_receipts，不读 Key verifier 或完整预算/事件。实际 role/default-role 测试验证允许/拒绝 |
| C07 | Key 创建/预算 CAS/撤销的真实 commit 后 ACK 注入：创建失败不返回原值，CAS 旧 revision 不重放，撤销可读回。Go owner 子进程准入提交后直接退出，后继进程按原 deadline/fence 恢复；不是仅 new Store，也不是 DB 断电/HA |
| C08/C12 | 精确查询用原 request/终态和原 allocation 的一致主库只读快照；优先查 release_log，slot 复用不串读。已释放容量与未知预算 held 分开。完整来源/价格/调用快照保持原值 |
| C13 | 唯一 `(publication_id, validation_policy_revision)` intent 固定原 request_id/专用 Key/profile hash。内部 validation candidate 分支不要求预先 ValidationPassed，但仍走相同 Key/三维预算/slot/唯一结算。成功 receipt 与终态同事务写入，激活只读此投影。serving/validation 两种私有消费者分别固定 purpose，公开入口不能选择 validation |
| C14 | 增加实际 Kubernetes client SecretReader，批准 namespace 与 UID/RV/key 精确匹配；只读，不创建 RBAC。原 H1 内存代理/回执校验库复用；没有 stock Higress 补丁或真实集群生效证据 |
| Redis | 完成 blocked epoch→主库同窗 grants 下界→Redis 原子 seed/marker→实例 run_id/nonce/窗口复验→同事务 ready。Redis 网络操作全在 MySQL 锁外。测试真的停掉并重启本测试创建的 Redis 子进程，先拒绝，重建后才恢复；ready epoch 禁止再 seed/reset |
| relay | 累计 usage 用最新单调快照替换，不逐块累加，倒退则保守失败。修复流中/非流式读体硬截止分类为 timed_out；取消仍为 cancelled，终态前不发正常 DONE，slot 无 H2 证明仍隔离。TLS 配置克隆，防调用方事后修改 |

`0001_kernel.sql` 与原发布迁移字节保持不变。新 `0002_control.sql` 由独立 migration 身份显式执行，仍使用 Applying/Applied＋checksum 恢复；增加 Key 元数据、Redis 重建记录、proof/intent/validation 成功窄投影。运行身份不迁移，不删除未知占用或历史。旧代码产生的无元数据 Key 不虚构创建时间：查询故障关闭，须有权威来源后显式修复，不能静默隐藏或编造历史。

production proof verifier、真实 H2 reporter、有效 xDS/全副本/凭证链仍未具备。CaptureWitness 的来源校验器是安装适配 port，测试使用明确 fixture；持久化/验签库本身不证明实际配置生效。默认 Operator 依赖/readiness 仍失败，默认 control-api 无推理入口，均不能成为真实 Callable。

## 给前端/QA 的管理与查询 API

| HTTP | 行为 |
| --- | --- |
| POST `/api/admin/v1/keys` | 必须给 name 和完整 budget_policy；仅此响应返回 secret，无隐含 100/日，创建 ACK 未知不重试 |
| GET `/api/admin/v1/keys` | Key 元数据＋当前 UTC 预算 known/inflight/held/available；分页，不返回 secret/verifier/pepper；nullable 停用维度保持语义 |
| PATCH `/api/admin/v1/keys/{id}` | expected_revision CAS＋完整 limits；不重置已有使用/预留/held，调低后 available 最低为 0；旧 revision 409 |
| POST `/api/admin/v1/keys/{id}/revoke` | 主库同 Key 锁、不可逆撤销；成功后其他副本拒绝新请求 |
| GET `/api/admin/v1/usage/requests` | 原日期/Key/模型/来源/状态过滤和稳定分页，UTC 最长 31 天；微秒时间用 DATETIME(6) 排序，不按 RFC3339 字符串错误比较 |
| GET `/api/admin/v1/usage/requests?request_id={原ID}` | 与所有其他参数互斥；返回 0/1 行＋lookup。当前只提供 recorded/unknown，不虚构未准入或保留期证据。GET 的新 X-Request-ID 不替换原生成 ID |
| GET `/api/admin/v1/usage/summary` | 从同一主库快照按日期/Key/模型/来源/币种/价表分组，只读统计。实际未知与 held 分开，不跨币种相加。试点扫描最多 10000 条，超出返回 503，未做大数据性能承诺 |
| GET `/api/admin/v1/model-releases/{ns}/{name}/revisions` | 保留草案 RevisionReader 接点。当前发布七表只有 revision hash，缺权威 spec/创建时间/引用资格与当前 K8s 可见性，因此默认 503；不返回假空历史或 eligible，不猜回滚目标。该持久历史需沿 MAAS-11 原 PR 接续 |

管理 API 只接受管理会话；Key/Bearer 不能当管理员。写入须精确 Origin、CSRF；重复参数/JSON 键、未知字段与不完整策略拒绝。错误统一脱敏、无原始 SQL/上游 body。查询不可用为 503，不能伪装成成功空记录。

`cmd/control-api` 是可构建的受控接入进程：仅允许显式 loopback 地址，显式过期时间、已批准 Origin、随机会话/CSRF 的 SHA256 摘要、已有主库配置与受保护 pepper。BootstrapSession 是有时限的本地安装适配，不是完整登录/会话提供者。没有默认管理员密码、没有平台 Key 管理授权、没有凭证上传接口。

前端/QA 可用真实 HTTP 测试复现：`TestMySQLSessionAPI` 启动短寿命 loopback HTTP server，调用真实 MySQL 内核，验证创建、元数据不泄密、CSRF、CAS 409、撤销、精确回查/参数冲突、汇总、缺历史 503、数据库关闭 503；结束即清理。没有留下长期服务。

需自行运行受控进程时，在已授权环境设置：`MAAS_CONTROL_LISTEN`、`MAAS_MYSQL_DSN`（ParseTime/UTC/超时）、`MAAS_CLUSTER_ID`、`MAAS_KEY_PEPPER`、`MAAS_ADMIN_SESSION_SHA256`、`MAAS_ADMIN_CSRF_SHA256`、`MAAS_ADMIN_ORIGIN`、`MAAS_ADMIN_EXPIRES`。然后构建/运行 `cmd/control-api`，用本地安全渠道已发放的随机会话 Cookie `maas_session` 和 CSRF 发请求。原值不写源码/命令示例/日志；此说明不授权目标环境部署。

创建示意（TST/数值仅测试输入，禁止用作真实默认）：

```json
{"name":"controlled","budget_policy":{"window_kind":"utc_day","limits":{"requests":"2","tokens":null,"money":null}}}
```

## 验证与未执行

运行：`go test ./...`、`go vet ./...`、`go build -buildvcs=false ./...`；真实依赖使用 `bash scripts/test-controlled.sh`。数据库原始输出 `mysql-tests.txt`、Go 原始事件另附；普通 Windows 测试未提供 socket 的场景明确 skip，不冒充数据库通过。

测试覆盖原 35 项、真实 role/default-role、持久证据/候选激活/撤销竞争、最后预算竞争、微秒排序与原 allocation 回查、HTTP API/401/403/409/503、累计 usage/硬截止、管理写 ACK、Redis 重启和 Go owner 进程退出。Witness/H2 证明生产者、relay 内的 Higress 仍有测试替身，Kubernetes SecretReader 用 fake client 检查 UID/RV/namespace，未连接目标集群。

未执行：真实 Higress H1–H4 producer/补丁、本地通道权限、production signer/issuer registry、受批准真实模型 validation、目标 K8s/Helm、GPU/权重、MySQL 崩溃/HA、浏览器联调和 A01–A34 整体验收。没有改另一个仓库；有待 Mika 协调 Higress 补丁及真实输入。MAAS-3 保持 in_progress，不以受控阶段代替整单验收。

给架构/QA 的反馈：FE-R03 implemented 子集只返回 recorded/unknown；缺证明时不推断 not_admitted/expired。FE-R02 需先补持久的保留 spec/来源与可见性接口，不能从现有 release_revisions 的 hash 推断 created_at/rollback eligibility。请按本次实际 SHA 复核 C02–C04/C11 与这些草案接点，C05/C13/C14 的真实生产者门槛继续保留。
