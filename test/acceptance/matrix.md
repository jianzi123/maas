A01–A34 可执行验收矩阵

每项均未获得完整运行验收。局部通过不等于该 A 项通过；用例原始结果和缺陷见同目录报告。终态仍 3.0。

| 编号 | 当前需求 | 可执行入口/局部样本 | 尚缺证据 |
|---|---|---|---|
| A01 | 经 Higress 配置获准外部 GPT 类真实模型并查询列表 | `TestAuthorizerConsumerContract` | 真实 Higress/供应商路由及模型列表未运行 |
| A02 | 未登录访问管理面；登录后创建 Key；退出再访问 | `TestMySQLKernel/revocation_visible_to_other_replica` | 完整登录/创建/列表及一次秘密返回的 HTTP/UI 待装配 |
| A03 | 有效 Key 分别调用非流式和流式 | `TestMySQLControlledRelay/nonstream`<br>`TestMySQLControlledRelay/stream` | 网关 HTTP 为替身，无真实模型 |
| A04 | 缺失、伪造、撤销 Key；提交未知模型或非法消息 | `TestAuthorizerConsumerContract`<br>`TestMySQLKernel/revocation_visible_to_other_replica` | 公开 HTTP 输入与真实网关零命中待验 |
| A05 | Go 服务至少两副本，每日限额设 2，先调用 1 次，再经 Higress 同时发 10 次 | `TestQABudgetRace` | 双 Store、10 个并发尝试；进程/真实 Higress 副本待验 |
| A06 | 用受控时钟跨 UTC 00:00；将额度改到小于已用量 | 未执行；前置未就绪 | UTC 边界、调低预算及旧窗归属未运行 |
| A07 | 首响应前注入上游失败/超时；首分片后断流 | `TestMySQLControlledRelay/interrupted`<br>`TestQAUsageBeforeTransportLoss` | 真实上游故障、timeout 与已知 usage 保留需闭合 |
| A08 | 试用页停止及 API 客户端断开 | `TestMySQLControlledRelay/cancel`<br>`TestQAUsageBeforeTransportLoss/client_write_failure` | 浏览器停止、实际生成停止及后继容量各需独立证据 |
| A09 | 上游返回实际 Token；另一次不返回 Token | `TestMySQLKernel/unknown_usage_duplicate_event_late_close_does_not_refund`<br>`TestQAUsageBeforeTransportLoss` | 受控 usage；真实上游/页面与缺失汇总待验 |
| A10 | 请求结束后查询，并重复投递计量终态事件 | `TestQAConcurrentFinalAndSlotReuse` | 唯一 DB 结算可测；5 秒查询投影/页面待装配 |
| A11 | 挂起 5 个已提交请求，再发第 6 个，随后释放一个 | `TestMySQLKernel/two_replicas_one_global_slot` | 单 slot 夹具，不把历史 5 并发当已批准默认 |
| A12 | 计量存储不可用；请求在途时模拟服务重启 | `TestMySQLKernel/restart_fences_owner_and_preserves_unknown_hold`<br>`TestMySQLControlledRelay/accounting_failure` | Store 重建非进程崩溃，HA/真实容量恢复未验 |
| A13 | 从全新获准环境按文档启动并检查日志 | `TestMissingProductionDependenciesFailClosed` | 目标启动、日志/保留期和部署就绪未验 |
| A14 | Vue + TypeScript 控制台登录→模型列表→创建 Key→试用→用量→撤销→重试 | 未执行；前置未就绪 | Vue 完整用户流程未验 |
| A15 | 配置一个外部与一个受控内网端点，按不同别名调用；提交未注册别名或自定义 URL | `TestQATamperedBindingHasNoWrites`<br>`TestAuthorizerConsumerContract` | 源/发布/预留错配拒绝；真实双来源/凭证通道未验 |
| A16 | 仅内网模式关闭外部来源并阻断公网出网，执行控制台与模型闭环；再在获准混合模式调用外部接口 | 未执行；前置未就绪 | 未验证内网出网阻断、混合真实调用 |
| A17 | 在获准 K8s 测试集群按版本矩阵 Helm 安装、升级、回滚 | 未执行；前置未就绪 | 未部署 Helm/K8s，无安装/升级/回滚运行证据 |
| A18 | 经多个服务副本撤销 Key、压满全局并发；流式期间滚动升级 | `TestQABudgetRace`<br>`TestMySQLKernel/revocation_visible_to_other_replica` | 进程多副本及带流滚动升级未验 |
| A19 | 单独启用请求数、Token、金额限额及组合限额；跨副本并发仅允许可用预算覆盖的请求，未获准不命中上游；可解释各类余额及拒绝原因。 | `TestQABudgetRace`<br>`TestMySQLKernel/token_rejection_rolls_back_every_dimension` | 组合预算局部；单维/完整余额 API 待验 |
| A20 | 流式最坏上界预留与实际结算；失败、取消、缺失/部分 usage、发送未知和重复终态不产生漏计、双扣或不安全退款；无可信上界时明确能力限制。 | `TestQAConcurrentFinalAndSlotReuse`<br>`TestQAUsageBeforeTransportLoss`<br>`TestQADeadlineAfterHeaders` | 传输/证据为替身，失败反例保持开放 |
| A21 | 多 Higress/Go 副本 Redis 限流一致；Redis 不可用、重启、丢状态或主从切换时不静默扩大放行，不绕过 MySQL 业务额度。 | `TestMySQLRealRedisWitness` | 真实局部 Redis/MySQL；完整重建/故障转移协调未验 |
| A22 | MySQL 事务、撤销、跨日、全局并发及 Redis/MySQL 部分成功/断网/ACK未知/恢复；没有分布式原子承诺的空白窗口，唯一结算及 slot 回收仍正确。 | `TestMySQLKernel/real_commit_ack_loss_never_reauthorizes`<br>`TestMySQLKernel/publish_close_cannot_overtake_admission_commit` | COMMIT 后 driver 错误非真实断网；跨日/HA 未验 |
| A23 | 多模型/价格类别、价表变更、币种/精度/舍入、金额不足与未知用量；请求用固定价格快照，汇总可追溯，不把未知成本当0。 | `TestMySQLKernel/known_usage_uses_frozen_price_and_rounds_once`<br>`TestMySQLKernel/budget_bound_breach_records_actual_and_blocks` | TST 合成币种价格，无真实价表 |
| A24 | 在获准 WSL 本地路径复现单管理员→Key→Higress→DeepSeek→用量/预算→撤销闭环；Codex 按确定的渠道单列兼容证据；本地受控验证与真实付费调用、Helm 验收分别记录。 | 未执行；前置未就绪 | 无 DeepSeek/Codex 真实闭环 |
| A25 | 校验私有/外部两类 CR；来源互斥、非法参数/别名冲突/未经允许的目标或 Secret 引用被拒绝，错误可定位；示例及状态中无真实秘密。 | `TestStrictSpecValidation`<br>`TestImmutableAliasAndSource`<br>`TestWebhookFailClosedAndCleanupAllowed` | 无 API-server/CEL/webhook 实际服务端证据 |
| A26 | 提交一个私有 CR，自动协调选定 LWS/引擎、Service 和 Higress 资源；同一 CR 重复提交不产生重复组或路由，完成真实可调用验证后才 Ready。缺 GPU 时仅可记录静态或受控验证。 | `TestCompileSourcesAndDeterminism/SelfHosted` | 只编译计划；LWS/SGLang/GPU/真实 Ready 未验 |
| A27 | 提交一个外部 API CR，只建立外部来源与发布结构，不创建 LWS/推理 Pod/GPU；调用仍经过 Go 唯一准入、Redis 限流和 MySQL 三维预算/计量。 | `TestExternalAPILifecycleAndRestart`<br>`TestCompileSourcesAndDeterminism/ExternalAPI` | 控制器 fake-client、运行证据接口替身，非完整生产装配 |
| A28 | 工作负载、依赖、网关配置或业务登记任一未就绪时，不对新修订放行；status 精确反映 observedGeneration、活动修订和失败原因；配置已写入不能冒充网关已应用。 | `TestGenerationCannotInheritReadyAndValidationIsUnique`<br>`TestMissingProductionDependenciesFailClosed` | 真实 producer/receipt 及受保护 validation 待装配 |
| A29 | 控制器重启、重复/乱序协调、资源漂移及更新冲突后收敛；不重复部署、覆盖非本模型资源或使发布状态虚假成功；依赖/节点故障明确可观察。 | `TestConflictRetryAndActivationCommitACKLoss`<br>`TestMySQLRelease/idempotent_observe_restart_and_monotonic_epoch` | fake-client+局部 SQL，非真实集群重启 |
| A30 | 带在途流更新并回滚一个模型；新旧修订、可信路由、请求价格快照和计量绑定正确，无跨来源回退或重复上游尝试；资源不足时按约定明确可用性结果。 | `TestMySQLRelease/activation_CAS_exact_replay_and_closed_publication` | 带流更新/回滚、资源不足及真实绑定待验 |
| A31 | 暂停/删除一个 CR，按约定停新准入、排空、撤路由及清理专属资源；共享对象中其他模型的配置、用户 Secret/PVC/权重和历史账本均保留；中断后可恢复。 | `TestDeletionWaitsForTransportAndSlot`<br>`TestCleanupNeverDeletesUserOrSharedResources`<br>`TestMySQLKernel/pause_delete_and_stale_epoch` | fake 清理+SQL 关门；真实排空/清理与恢复待验 |
| A32 | 两个模型并发发布/删除并轮换凭证，namespace/RBAC、共享配置合并与 Secret 注入边界正确；一个模型的改动不影响另一个，也不绕过预算。 | `TestTwoModelsSharedGatewayCleanupIsolation`<br>`TestMySQLPublisherCannotWriteRealLedger` | 共享配置 fake 与 SQL 窄权限，非真实 SA/Secret 轮换 |
| A33 | Helm 安装/升级/回滚检查 CRD、Operator、LWS、Higress、GPU/存储依赖及版本；缺依赖时模型 CR 明确失败而不擅自改集群基础设施；WSL受控与真实GPU结果分开。 | 未执行；前置未就绪 | Helm/CRD/Operator/LWS/引擎/GPU 目标版本矩阵与集群运行待验 |
| A34 | SGLang 固定条件基线与一次经证据定位的优化对照可复现，质量/取消/三维预算/计量回归通过；无 GPU 或基线时只交方案与未执行项，不宣称性能提升。 | `python -m unittest discover -s tools/perf -p test_*.py` | 41 项离线回归；E1/E2/E3/GPU/收益均未验 |

SQL/relay 与 QA 测试统一入口：`bash test/acceptance/run.sh`；仅 QA：`MAAS_TEST_PATTERN=^TestQA bash test/acceptance/run.sh`。其余 Go 测试由 `bash test/acceptance/regression.sh` 覆盖，数据库默认 skip 不算 SQL 通过。

FE-R02/03 读端入口：`python test/acceptance/probe_admin.py --help`。该入口本轮只检查帮助/语法，未执行 HTTP 请求。完整 0/1 行、UTC、权限、503、409、未知写入和容量投影仍须用批准的真实受控 API 数据执行。

部署由 MAAS-8 主责，本角色独立见证 A17/A33；性能复用 MAAS-10 的 C01–C08/E1–E3 方法，41 项离线测试不代表任何真实性能收益。
