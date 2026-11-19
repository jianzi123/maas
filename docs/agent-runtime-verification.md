MAAS-20 本轮验证记录（2026-11-19 UTC）
=====================================

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
