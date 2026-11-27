# 当前交付组合的功能与验证边界

本表随 MAAS-21 最终组合维护。运行入口是正常 `cmd/maas-service migrate|serve --config FILE`；持久业务数据默认 MySQL。默认 `external-api` 没有已获准模型；使用者只有显式选择 `offline-controlled` 才能运行本仓库受控模型。受控回答带标记，模型/rate/publication/closure是受限合成生产者；Token/金额仅用于验证原账本，不是供应商真实计费或性能结论。

| 能力 | 状态 | 实际入口/源码与证据 | 限制 |
| --- | --- | --- | --- |
| 正常进程、迁移/运行身份与恢复 | 物理门禁修订已纳入并构建；P1独立复验待签 | 正常migrate/serve/reconcile；原journal/owner/取消隔离，新增41对象/50原唯一键/terminal非NULL；组合46181fab | eab5d69只读检查与12 SHOW VIEW元数据，不读私有数据或DDL；旧1f8的47/3原件保留，不用作者结果关闭独立P1 |
| 管理员/Cookie/CSRF稳定身份 | 已实现并验证 | internal/app/auth.go；独立QA879a正常入口、集成真实站点；应用/MySQL重启恢复 | 单管理员试点；固定安装ID/pepper/cursor/数据库跨升级保留 |
| 会话列表/创建/改名/删除、多轮/编辑/重新生成 | 已实现，已在受控API验证；最终组合独立复验另列 | internal/agentruntime/ar_http.go、ar_commands.go；console/src/chat/http.ts、ChatWorkspace.vue | 新操作保留原消息/命令关联；空models不能创建可用会话 |
| 普通Chat中文/Markdown/代码、SSE | 已实现并完成正常MySQL离线站点验证 | same-origin /api/agent/v1；安装smoke的chat及SSE cursor检查 | 离线回答为固定受控响应，不代表真实模型质量 |
| Agent循环/两个真实工具/批准 | 已实现；正常MySQL离线站点及受保护tools桥受控验证通过 | offline.go复用原Service/Host/Registry；Calculator真实算42，ModelDirectory返回可信目录；原批准API后第二child完成；正式桥沿原Admit/Finalize | 正式桥已消费显式Profile.Tools，但真实供应商/生产Higress及批准安装来源未验；没有跨源fallback |
| Session/Message/Run/Step/ToolCall/Event/Checkpoint/审批持久化 | 已实现并验证受控范围 | MySQLStore单CAS聚合文档、原AR-1事件；独立QA的存储/并发/原ID恢复 | 单会话聚合文档32MiB上限；不是长期记忆系统 |
| 工具描述/Schema/可信执行上下文 | 已实现并验证 | tools.go、tool_context.go；docs/agent-tool-interface.md；name/version/description/input/output、scope、run/step/call/child request/trace/deadline/fence/幂等 | 旧Execute的输出仍是string；目录结果为JSON数组的字符串，不能谎报通用JSON执行器 |
| 工具取消/超时/attempt/未知结果屏障 | 已实现，受控后端有独立QA | AR-R02在879a受控范围关闭；safe/read/受控write矩阵；未知写needs_confirmation、不重放 | 原QA结果不自动覆盖最终新profile；外部副作用执行器未实现 |
| 停止已实际准入child | 后端已验证；页面竞态在393受控范围独立关闭 | 原cancel/Admit/Finalize；QA-CHAT-RACE-001四迟到顺序、idle正例及畸形负例，9页面＋4只读契约通过 | QA站点MySQL8.0.44/Chrome158；本次console/API零差异保留该范围，ACK不等于外部资源已终止，unknown不自动释放/重跑 |
| 刷新/断线/410只读恢复 | 已实现，固定后端有独立QA | AR-R01在879a关闭；Step/Tool分页及中文/98/100/102边界；新站点浏览器刷新Run POST0 | 持续写入可触发有界暂停重取；不保证任意时刻分页立即收敛 |
| 父Run/child/known/inflight/held唯一计量 | 已实现并验证受控范围 | 原kernel.Admit/Finalize及usage；独立QA两child known/mixed样本；离线站点两模型child known20，重复命令原Run返回 | 合成价表与真实模型分列；unknown不补0，父Run不再扣量 |
| 消息/工具/事件/原child消费跨重启 | 已实现并完成离线应用/MySQL只读验证 | 安装smoke create记录原IDs/数据hash；verify仅GET业务记录（登录/退出除外） | 最终同版Compose/独立QA结果在交付验证清单注明 |
| 管理发布/历史/Operations/Publisher工厂 | 已实现接线，待目标装配验证 | internal/app/management.go；原history.Reader/Payload/Operations/Service/OpenPublisher；四独立DSN/单角色/Registry/kubeconfig实际消费 | management默认关闭，与离线模式互斥；缺配置拒绝，不用core回退；不能称全管理已在真实目标验收 |
| 正式ExternalAPI text-v1 | 已实现配置/原票据接线，待获准来源验证 | models.go、kernelmodel.RelayModel；原publication/Profile/平台Key/预算/固定Higress/mTLS/签票及显式ledger.diagnostics | 不是仅填供应商Key即可调用；真实来源/发布/网关/producer与Secret仍需完整获准装配 |
| 正式tools-v1受保护桥 | 已实现并完成受控HTTP/真实MySQL组合验证，真实供应商待验 | internal/toolwire、kernelmodel/messages.go、app/models.go与原Relay；整批校验、原source call ID回填、每child唯一计量 | 必须是新批准Profile.Tools/UsagePolicy＋deepseek-chat-tools/1/non-thinking；原text-v1和财务Canonical不放宽，不把受控producer当生产事实 |
| Compose/原生K8s/外置MySQL/两包 | 已实现，实际验收范围见同包VALIDATION与最终主单 | deploy/release/；完整源码/四锁/Dockerfiles/配置/迁移/包生成器 | 成功路径为原生构建＋Dockerfile.native；多阶段网络失败保留；K8s仅严格schema，未安装到目标 |
| 10–15分钟演示/自动smoke | 已实现；正常离线原命令已实跑 | console/docs/demo-15min.md；deploy/release/compose/README.md；smoke.py create/verify；scripts/smoke-product-offline.py、smoke-product-cancel.py | 先选显式离线profile；真实源调用须另具批准，不自动批准扩展工具 |
| MCP/外部HTTP工具/文件/shell | 未实现产品执行器 | 只有原Tool接口可受控扩展 | 不提供任意执行/文件上传按钮冒充后端能力 |
| 检索/向量库/长期记忆/子Agent | 未实现 | 原Session/Checkpoint可持久化，但不是这些能力 | 未来实现需沿scope/预算/审批/幂等/unknown规则 |

当前下一版来源：统一4402（tree=d27）及原PR11/12/20/22/24/25祖先；后端物理修订eab5d69（保留532祖先）、前端eec33eb、运维7cc6b06已进入主单隔离组合，尚未远端默认分支合入。最终code/四锁ref由包根VERSION.json与主单记录给出。源码图和问题/回滚路线见next-release-integration.md；delivery-integration-review.md保留上一里程碑范围。

独立QA固定879a7aa（代码07b00d8）：AR-R01/R02受控关闭；MySQL5顶层、正常DML/迁移/第二owner/旧在途needs_confirmation及同Cookie跨重启通过。QA代码00adf077→四锁66139c99，报告附件01a20919-d75b-7cfa-87ef-7edae4f1c565，证据SHA25619fc82766ea7110a51f58c5510c8c93841a7aa112995354713eeeb5e9e58aba4。后续最终profile/安装/新UI需按差异独立补验，不把历史数量相加。

发布Operator的cmd/operator仍是nil适配器的审查入口；源代码保留不等于生产装配已完成。性能/算法入口实际包括tools/perf/analyze.py、controlled_transport.py、engineering/、scheduling/、diagnostics/及tools/model_capabilities/check.py；它们属于离线/研究/评测链，与本次HTTP主调用图分开，新的SGLang研究分支未为安装而重做或清除。

真实供应商/Higress生产接流及正式tools-v1真实来源、管理目标/完整Operator装配、K8s集群安装与重启、GPU/性能及A01–A34整体均未因本次受控交付关闭。所有生产Ready/付费/目标部署和远端默认分支合入仍按原批准。

轻量获取型ZIP同样固定最终Git ref并附四锁/完整SOURCE.sha256清单，先运行包根fetch_source.py。完整内嵌源码包可用package.py默认模式生成，--source-mode fetch生成需要GitHub网络的获取包。完整性修复在d27已独立关闭（四种包52/52、fetch守卫8/8及CLI8/8），本轮保留；新数量由最终锁与SOURCE计算。

## 2026-11-26下一版组合接续

原PR19已于11月24日Merge为统一4402，tree=d27；本轮PR21保留#11/#12/#20/#22/#24/#25祖先继续组合，最终代码/四锁以VERSION和本单交付为准。

- 独立cmd/publisher已构建并在自有MySQL/mTLS/非root进程实际验证：live204/ready503、幂等/冲突、窄权限拒绝、完成hook回滚和重开。缺生产证明仍拒Activate，不能称完整发布就绪。
- TemplatePluginCompiler与review资源已纳入，cmd/operator仍nil生产适配器；Control的durable Observe/Read/Drain、Inventory/BundleCatalog和真实producer接线仍缺。
- 正式工具桥已纳入，组合Go协议/向量/AR回归30顶层124测试子项通过；正常HTTP/Cookie/CSRF→受控mTLS→原Admit/Finalize→两个实际工具→原ID反馈与第二child的SQL组合通过。模型/Higress-H4/rate/publication/closure为测试注入，不是供应商或生产Higress。
- 正式模型要求显式ledger.diagnostics安装策略，迁移只补缺行、冲突拒绝，runtime只读；示例值需安装者核定。旧models=[]/显式offline配置兼容，缺字段的正式配置启动失败与运行期缺策略503分开。
- 工具Schema/参数使用独立有符号安全整数JSON域，原票据/计划/财务域仍非负。公共AR-1投影不增加supplier字段；内部历史从原Run/Step.Call恢复sourceID，未完成/伪造反馈拒绝。
- 原前端PR25已纳入：公开playground.enabled可选且缺省关闭、引导Chat；登录bootstrap禁输入；被新open淘汰的poll读为Abort，真实畸形关联仍拒绝。组合64项受影响测试通过，QA-CHAT-RACE-001已在393受控正常站点由原QA独立关闭；作者浏览器与QA结果仍分列。
- 旧在线试用引导Chat不关闭原M03公共消费Key API验收。历史partial/interrupted逐条标记、恢复阶段可观察性仍是前端评审提出的后续体验项，不能统称已完成。
- 原生K8s自有验证/升级脚本19fixture及旧14资源schema有证据；资源条件变化后已交原运维按锁定纯迁移ref续办，实际安装/PVC/重启结果未到，不把计划当通过。最终新头只按实际差异接续。
- 历史8db来源卡在新journal只读授权后有publisher-grants文件摘要漂移；保留历史快照/未批准值，旧检查通过不外推当前，当前真正权限以最新模板及独立验证为准。
- 失联恢复后核实原运维运行17:15 runtime_offline，其重试20:15 reconnect_timeout且未started；没有可用结果，已沿原单恢复现场检查。2026-11-27约01:00 UTC可用内存621140KiB，低于新增节点4096MiB门槛，不能沿用旧高余量结论或停止他人服务挤资源。
- 原QA的QA-MIG-SHAPE-001/P1仍开放，47/3保留原反例与CLI ready200证据。原后端正在补物理对象/唯一约束门禁，私有元数据只读可见性须维持最窄身份；尚未据作者结果签独立关闭。

真实来源/安全引用、准确模型/显式模式、全计费上界/final usage、价表/额度/预算、Higress信任/实例boot/插件digest/receipt/validation、四身份同数据域和管理目标仍须具体批准。MCP/外部HTTP工具/文件/shell/长时记忆/子Agent没有新增执行器。A01–A34整体与GPU/性能结论仍按原独立范围。

## 2026-11-27物理门禁与独立页面复验

本地保全祖先组合46181fab=393edc9＋原PR24 eab5d69（代码5fffa8b）。新SQL权限增量精确为原maas_release_reader的12对象SHOW VIEW，旧9份DDL/AR-1/console均未变；41对象/50键生成与gofmt后原件完全匹配，组合正常Linux产品构建/定向vet通过。物理三缺口、变体、最窄角色、原journal/reconcile/unknown-held及查询中取消按组合定向验证，实际结果由同版VALIDATION及主单列出；P1须原QA签回。

页面独立QA固定393/c99（console=eec33eb）关闭QA-CHAT-RACE-001：9唯一页面用例＋4只读契约，正常Go/MySQL8.0.44/Chrome158；4原Run/6child，6request/6usage/6finalized，迟到GET只延迟真实响应、无自动重发/重计。R-P01/default false与bootstrap真实401通过，公共消费Key API不销项。报告评论01a21af8-56a4，证据SHA f6ad550d83610b26419b7c073e96935e0c18aa052d28da73dddc5f9ab566e4ad；QA分支ca97证据锁不得覆盖产品锁。本组合console/API schema字节不变，保留该独立范围。

FC-M-AUTH-PRE-1（原架构01a21aed-52b6）要求自动和pre-provisioned安装/升级都在候选启动前审完整effective grants，PROVISION_ROLES=0只跳provision，不得跳audit。当前migrate.sh尚未完成该增量，原MAAS-8唯一负责，不能以4 default roles或旧10项SQL宣称完整最小授权。精确主体/角色闭包、直接/列级/角色内容、mandatory/代理/动态权限等须对最终锁定模板核验；缺合法可见元数据非零退出，不借管理DSN/授runtime mysql.*或造旁路。连续运行期full权限漂移守卫是原MAAS-20独立后续，本版本未实现，不把安装通过当持续证明。

原生K8s历史6285曾构建三镜像/建群Ready/PVC Bound，但mysql-ready exit124，未执行迁移Job/App/业务；恢复将自有MySQL缩0、节点停止，保留PVC/Secret/容器身份，Exit137不称优雅或数据恢复通过。138文件证据SHA 1f4f98576f3931eebdb246581fbba0710ef9e6a741e852125ad07a7b6fb53720；不外推本组合K8s完成。

组合46181fab实际结果：MySQL8.4.7六顶层/22测试及子项全部通过（原三反例＋变体/最窄元数据权限/原journal/reconcile/unknown-held/查询中取消）；另原正常HTTP工具闭环一顶层/3测试及子项通过，完整与非法第二工具分别保持原唯一child用量语义。两阶段均exit0、0失败/skip，专属容器/卷已精确清理。正常Linux产品构建、测试二进制与定向vet通过，九DDL、console和公共AR-1相对393零差异。以上为集成证据，不替代原QA三反例关闭或安装effective-grants验收。最终code/ref由VERSION给出；其后本次只补报告和标准四锁。
