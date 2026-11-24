# 当前交付组合的功能与验证边界

本表随 MAAS-21 最终组合维护。运行入口是正常 `cmd/maas-service migrate|serve --config FILE`；持久业务数据默认 MySQL。默认 `external-api` 没有已获准模型；使用者只有显式选择 `offline-controlled` 才能运行本仓库受控模型。受控回答带标记，模型/rate/publication/closure是受限合成生产者；Token/金额仅用于验证原账本，不是供应商真实计费或性能结论。

| 能力 | 状态 | 实际入口/源码与证据 | 限制 |
| --- | --- | --- | --- |
| 正常进程、迁移/运行身份 | 已实现并验证 | cmd/maas-service；internal/app/database.go、migrations/001_product.sql、002_offline.sql；真实迁移、DML无DDL、缺迁移拒绝 | serve不执行DDL；部署单活，非多活HA |
| 管理员/Cookie/CSRF稳定身份 | 已实现并验证 | internal/app/auth.go；独立QA879a正常入口、集成真实站点；应用/MySQL重启恢复 | 单管理员试点；固定安装ID/pepper/cursor/数据库跨升级保留 |
| 会话列表/创建/改名/删除、多轮/编辑/重新生成 | 已实现，已在受控API验证；最终组合独立复验另列 | internal/agentruntime/ar_http.go、ar_commands.go；console/src/chat/http.ts、ChatWorkspace.vue | 新操作保留原消息/命令关联；空models不能创建可用会话 |
| 普通Chat中文/Markdown/代码、SSE | 已实现并完成正常MySQL离线站点验证 | same-origin /api/agent/v1；安装smoke的chat及SSE cursor检查 | 离线回答为固定受控响应，不代表真实模型质量 |
| Agent循环/两个真实工具/批准 | 已实现并完成正常MySQL离线站点验证 | offline.go复用原Service/Host/Registry；Calculator真实算42，ModelDirectory返回可信离线目录；原批准API后第二child完成 | 正常外部模型tools-v1仍未实现获准归一化/装配；没有跨源fallback |
| Session/Message/Run/Step/ToolCall/Event/Checkpoint/审批持久化 | 已实现并验证受控范围 | MySQLStore单CAS聚合文档、原AR-1事件；独立QA的存储/并发/原ID恢复 | 单会话聚合文档32MiB上限；不是长期记忆系统 |
| 工具描述/Schema/可信执行上下文 | 已实现并验证 | tools.go、tool_context.go；docs/agent-tool-interface.md；name/version/description/input/output、scope、run/step/call/child request/trace/deadline/fence/幂等 | 旧Execute的输出仍是string；目录结果为JSON数组的字符串，不能谎报通用JSON执行器 |
| 工具取消/超时/attempt/未知结果屏障 | 已实现，受控后端有独立QA | AR-R02在879a受控范围关闭；safe/read/受控write矩阵；未知写needs_confirmation、不重放 | 原QA结果不自动覆盖最终新profile；外部副作用执行器未实现 |
| 停止已实际准入child | 已实现并完成正常离线站点验证 | 原cancel API/Host与原Admit/Finalize；取消ACK和最终状态分开 | 不能把收到停止ACK说成资源已终止；unknown不自动释放/重跑 |
| 刷新/断线/410只读恢复 | 已实现，固定后端有独立QA | AR-R01在879a关闭；Step/Tool分页及中文/98/100/102边界；新站点浏览器刷新Run POST0 | 持续写入可触发有界暂停重取；不保证任意时刻分页立即收敛 |
| 父Run/child/known/inflight/held唯一计量 | 已实现并验证受控范围 | 原kernel.Admit/Finalize及usage；独立QA两child known/mixed样本；离线站点两模型child known20，重复命令原Run返回 | 合成价表与真实模型分列；unknown不补0，父Run不再扣量 |
| 消息/工具/事件/原child消费跨重启 | 已实现并完成离线应用/MySQL只读验证 | 安装smoke create记录原IDs/数据hash；verify仅GET业务记录（登录/退出除外） | 最终同版Compose/独立QA结果在交付验证清单注明 |
| 管理发布/历史/Operations/Publisher工厂 | 已实现接线，待目标装配验证 | internal/app/management.go；原history.Reader/Payload/Operations/Service/OpenPublisher；四独立DSN/单角色/Registry/kubeconfig实际消费 | management默认关闭，与离线模式互斥；缺配置拒绝，不用core回退；不能称全管理已在真实目标验收 |
| 正式ExternalAPI text-v1 | 已实现配置/原票据接线，待获准来源验证 | models.go、kernelmodel.RelayModel；原publication/Profile/平台Key/预算/固定Higress/mTLS/签票 | 不是仅填供应商Key即可调用；真实来源/发布/网关/producer与Secret仍需完整获准装配 |
| 真实供应商tools-v1 | 未实现可用的正式归一化/批准装配 | 当前正常适配准确tools_protocol_unavailable | 受控tools-v1不是该能力已验的证据 |
| Compose/原生K8s/外置MySQL/两包 | 已实现，实际验收范围见同包VALIDATION与最终主单 | deploy/release/；完整源码/四锁/Dockerfiles/配置/迁移/包生成器 | 成功路径为原生构建＋Dockerfile.native；多阶段网络失败保留；K8s仅严格schema，未安装到目标 |
| 10–15分钟演示/自动smoke | 已实现；正常离线原命令已实跑 | console/docs/demo-15min.md；deploy/release/compose/README.md；smoke.py create/verify；scripts/smoke-product-offline.py、smoke-product-cancel.py | 先选显式离线profile；真实源调用须另具批准，不自动批准扩展工具 |
| MCP/外部HTTP工具/文件/shell | 未实现产品执行器 | 只有原Tool接口可受控扩展 | 不提供任意执行/文件上传按钮冒充后端能力 |
| 检索/向量库/长期记忆/子Agent | 未实现 | 原Session/Checkpoint可持久化，但不是这些能力 | 未来实现需沿scope/预算/审批/幂等/unknown规则 |

当前代码来源：后端228bbe4（包含f990576）、前端7d7e658、安装器3f97e9b及各原依赖祖先；最终code/四锁ref由包根VERSION.json与主单记录给出。源码图和问题/回滚路线见delivery-integration-review.md。

独立QA固定879a7aa（代码07b00d8）：AR-R01/R02受控关闭；MySQL5顶层、正常DML/迁移/第二owner/旧在途needs_confirmation及同Cookie跨重启通过。QA代码00adf077→四锁66139c99，报告附件01a20919-d75b-7cfa-87ef-7edae4f1c565，证据SHA25619fc82766ea7110a51f58c5510c8c93841a7aa112995354713eeeb5e9e58aba4。后续最终profile/安装/新UI需按差异独立补验，不把历史数量相加。

发布Operator的cmd/operator仍是nil适配器的审查入口；源代码保留不等于生产装配已完成。性能/算法入口实际包括tools/perf/analyze.py、controlled_transport.py、engineering/、scheduling/、diagnostics/及tools/model_capabilities/check.py；它们属于离线/研究/评测链，与本次HTTP主调用图分开，新的SGLang研究分支未为安装而重做或清除。

真实供应商/Higress生产接流、正式tools-v1、管理目标/完整Operator装配、K8s集群安装与重启、GPU/性能及A01–A34整体均未因本次受控交付关闭。所有生产Ready/付费/目标部署和远端默认分支合入仍按原批准。

轻量获取型ZIP同样固定最终Git ref并附四锁/完整SOURCE.sha256清单：先运行包根fetch_source.py，已用真实GitHub固定b868 ref核对833个源码文件及四锁，再按原README构建。它是完整获取方式而非全离线介质；完整内嵌源码包可用package.py默认模式生成，--source-mode fetch生成可传输轻量包。验证器对两种模式分别标注覆盖范围，不将尚未获取的源码说成已在ZIP中。
