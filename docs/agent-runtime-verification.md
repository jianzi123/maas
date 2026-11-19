MAAS-20 本轮验证记录（2026-11-19 UTC）
=====================================

AR-1 draft.2 实现验证（本轮最新）
--------------------------------

上一轮未实现AR-1/SQL跳过的范围已由本轮增量接续：现在有正式`ARHandler`、同一核心的受控loopback HTTP入口和真实临时MySQL验证。下方首段报告保留为历史，不外推旧结果。新原始证据在 `test/controlled/maas20/ar1/`，与本轮产品代码同一提交，随后标准四锁独立引用该代码提交。

| 平台/入口 | 实际结果 | 范围 |
| --- | --- | --- |
| Windows `scripts/test-agent-runtime.ps1` | 30个顶层测试/含子测试58通过，0失败；go vet及受控入口构建通过 | 原核心回归＋AR-1 HTTP/Schema/文件/宿主/真实loopback会话/SSE |
| WSL `scripts/test-agent-mysql.sh` | 16个顶层测试/含子测试28通过，0失败、0 skip | AR-1定向场景＋两个真实MySQL/原账本测试 |
| AR-1完整轨迹 | 34条持久事件 | 两次受控模型调用，真实计算6×7=42、当前scope目录查询、结果回填、最终中文/emoji答复；逐条通过原事件Schema |

两平台的AR-1场景重叠，不能将58与28相加宣称独立案例总数。Windows无Unix socket，主入口中的MySQL用例和单独kernel编译探针仍会skip；**真正SQL通过来自WSL独立原始JSONL，不能以Windows skip替代。** WSL本轮已恢复，没有重启/关闭共享WSL。便携Go1.26.0、MySQL8.4.7及libaio包只读复制到本任务缓存，摘要匹配原固定官方值；未改全局工具或他人缓存。原服务器脚本仅创建专属`/tmp/maas11-mysql.*`数据/socket，skip-networking、port0，收尾核对自有PID/数据目录后关闭并删除；附server log证明shutdown complete。

实际关闭范围：

- 创建ACK丢失仅凭原operation ID查回；同/异hash、跨principal、删除后映射、404/关闭数据库503均有真实处理路径。不会从列表猜会话或新建另一ID。
- 同Run命令先返回原身份再看旧If-Match，单会话活动屏障；Role/Schema/模型/工具能力、安装策略及wire 10000/10001/Chat=1拒绝发生在新模型发包前。完整10000子ID读取/10001数据超界拒绝是**合成保留文档容量见证**，没有执行10000次模型请求或作吞吐声明。
- JSON与SSE同Envelope，事件UUID/run seq十进制字符串、超JS安全整数seq、随机256bit映射cursor、跨Run/非法cursor、after/Last-Event-ID互斥；assistant created先于delta，中文/emoji按UTF8字节偏移；文件重开后原事件包络按字节一致，GET/刷新/重连零模型执行。
- 实际TCP loopback使用原LocalSession Cookie/Origin/CSRF，匿名/退出后401、错CSRF403；HTTP→Host→同一Service→流事件→快照经过真实http.Client/Server，临时监听器正常关闭。认证数据与模型为受控适配，不是生产账号或浏览器证据。
- 真实安全工具、有版本Schema与参数规范化、输出Schema、授权及冻结Registry；审批hash/版本/策略/期限/decision_id幂等、Host同Run调度去重与批准续跑；等待批准受原总时限约束。
- model/工具未决身份在dispatch前持久化；旧executor不能推进；缺原子子终态确认不执行工具，needs_confirmation仍占活动位；未知写入不重放。取消请求与实际返回分开，已确认失败/取消的原子权威用量继续保留，不因失败改成0。未提供的分组/金额/Token保留未知与不完整，不补造账务。
- edit/regenerate保留旧消息/消费，新assistant关联原assistant，后续只使用选定分支；列表创建时间/UUID并列稳定，删除前页对象不漏下一页。
- `TestMySQLAR1CommandsRestartAndTwoReplicaClaim`：真实MySQL文档、跨连接重建服务、原创建映射、两个Service认领竞争、事件读取及数据库关闭503。
- `TestMySQLAgentChildrenUseOneLedger`：真实原Admit/Finalize/MySQLSessionStore，两个稳定子request_id、每子一条usage_events、重复Finalize和命令/回放零重复扣量；generation_requests=2、usage_events=2、usage_daily finalized=2、Token known=38、held/reserved=0。父Run只写应用文档和派生投影，没有新增财务记录。

模型为确定性受控ModelClient，原账本测试的rate/H1–H4证据生产者及批准身份是原fixture；工具、存储、HTTP、取消/宿主和账本代码是真实实现。没有真实供应商/付费调用、生产Higress、真实tools-v1 profile、目标集群、生产Secret、GPU或吞吐验收。生产Auth/Catalog/Reauthorize/Counter/Prepare/Usage/FailureResolved须由已有获准链路提供，缺项失败关闭。原R1–R3/UI16等历史QA不复跑、不扩大关闭范围。

MAAS-5浏览器接同一Go服务、MAAS-7独立复验和MAAS-8/17组合装配/集成尚需各原角色验收；本报告是后端作者证据。受控启动命令、Cookie/CSRF、能力/测试限制及profile边界见agent-runtime-v1.md，不将真实SQL/工具闭环称为生产Callable或完整A01–A34。

<details>
<summary>上一轮第一段验证报告（历史范围）</summary>

本轮后半段已接到并校验AR-1 draft.2。先前候选HTTP不兼容其完整字段，现已撤出共享命名空间，仅保留 `/__maas/controlled-agent/v0` 的ControlledHandler；工具名对齐bounded_arithmetic/list_visible_models、接受态采用accepted、Chat强制一次调用。原件保存在docs/contracts/agent-runtime/ar1-draft2。**AR-1正式适配仍是确定的剩余实现，不能再称“待架构给契约”，也不能将本报告算作AR-1/Chat联调通过。**

本报告与实现、原始 JSONL 在同一代码提交，随后独立四锁提交引用该代码 SHA。起点为统一分支 `agent/MAAS-10-offline-metrics` 的 `8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a`；在任务隔离分支实施，没有合并既有 #14/#15 候选或覆盖其他工作树。

执行 `scripts/test-agent-runtime.ps1`：16 个顶层测试通过，连同子测试为 32 个通过，0 失败。两包 `internal/agentruntime/...` 实际运行，`go vet ./internal/agentruntime/... ./internal/kernel` 退出 0。受控 headless 实际产生 18 条事件，以 run.completed 结束。

原始证据：`test/controlled/maas20/tests.jsonl`、`headless.jsonl`、`mysql.jsonl`。模型、授权测试适配与通用 write 工具是明确测试替身；整数计算器、按 Principal 调用的目录工具、核心循环、HTTP handler、Host、文件存储及重开为真实实现。未使用真实供应商模型、付费调用、生产 Secret、目标集群或 GPU。

| 范围 | 已执行证据 |
| --- | --- |
| Chat/Agent | 普通回答、两步 Agent、真实计算 6×7=42、目录结果回填、最终回答 |
| 幂等/隔离 | 同 client_id 返回原 run、异输入冲突、单会话并发拒绝、owner 隔离、每步唯一 request_id |
| 工具 | Schema 拒绝、未授权/未知工具、重复调用 ID、缺 finish、空 tool_calls、输出上限、超时 |
| 限制 | 步数/调用限制、未知用量停止继续推理、总时长、返回用量超过上界、发送前计划上界/币种绑定 |
| 取消 | 取消先入日志、context 传播、等待实际模型返回后写 cancelled |
| 审批 | 参数哈希不匹配、授权修订变化、过期、重复批准拒绝，批准后经新 Service 继续原调用 |
| 恢复 | executor 竞争、迟到结果隔离、未决模型/工具不重放、write 结果不明进入 needs_confirmation |
| 文件持久化 | 独占目录、完成态重开、临时尾部不读取、未决检查点落盘后重开仍需确认、旧 revision 拒绝 |
| 消息/HTTP | 编辑保留原消费与消息、后续只见编辑分支、body 不允许 owner、SSE重复读取不执行、HTTP→Host→同一核心 |

未执行/边界：

- `TestMySQLAgentChildrenUseOneLedger` 编译成功但运行 SKIP（无 disposable MySQL socket）。WSL Ubuntu-22.04 启动返回 Wsl/Service/WSAETIMEDOUT，未关闭/重启共享 WSL 或修改系统环境。这个 skip 不是数据库通过；SQL 迁移、双副本 CAS、真实 Admit/Finalize 去重与金额投影仍需用原获准临时组件入口实际复验。
- LocalStore 是单进程开发实现，未测试操作系统掉电或跨主机持久性；内存恢复测试是模拟崩溃，文件测试覆盖真实写入后关闭/重开，不夸称强杀/断电故障注入。
- Relay 文本适配的缺项拒绝、事件分帧和发送前计划约束有测试；没有实际调用生产 Relay/Higress。Prepare/Usage 工厂、正式管理身份与目录、tools-v1/profile批准还需原 MAAS-3/18 链路输入。
- `/api/agent/v1` 必须采用已交AR-1 draft.2，本PR没有暴露不兼容的原候选。正式命令幂等查回/If-Match、保护cursor和严格事件DTO、UTF8 offset/快照水位、limits/usage_groups/审批DTO及regenerate关联仍需在同一核心接续；具体差异见agent-runtime-v1.md。UI联调、正式授权/迁移装配、独立QA及最终集成尚未完成。
- 测试值为 TST 币种、100 Token/100原子金额、4 步/4 次调用、5 秒总时间（headless 为10秒），工具1秒、审批1分钟、32KiB输入/8KiB输出/500事件。它们不是生产默认或资源批准。

本轮交可审代码与受控内核证据；MAAS-20 继续 in_progress，尚未达到完整 Chat 产品集成或真实模型验收。后续沿同一 PR 收敛，最终交付才转 in_review，done 由成员确认。

</details>
