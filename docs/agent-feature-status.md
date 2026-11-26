Agent功能状态（本轮正常产品接线）
=================================

本清单随本轮代码提交并由标准四锁引用；最终Compose/K8s组合由MAAS-21更新精确SHA和独立验收结果。2026-11-26增量从统一4402c456续接，保留原AR-R01/R02及879受控关闭范围，不外推本次新代码的独立QA。未更新的历史验证数字继续以各自报告截点为准。

| 功能 | 当前状态 | 入口/依据与限制 |
| --- | --- | --- |
| 同正常入口的显式离线profile | 已实现并有作者真实SQL闭环 | product.offline.example.json显式enabled；同MySQL/身份/原Admit/Finalize，合成模型/证据标controlled；2真实工具/审批/停止、3child/3usage、重启回放零新增；默认不开启，不是供应商tools-v1已验 |
| 发布/修订/操作管理装配 | 已接原工厂，待真实K8s/独立角色组合验证 | management.enabled需四独立DSN/对应单默认角色、原Registry/kubeconfig；不回退core。disabled时这些API仍不可用，不能称全管理闭环恢复 |
| 正常服务/容器监听 | 已实现并完成可构建验证 | cmd/maas-service，serve/migrate独立；监听来自明确JSON，非agentcontrolled；实际镜像/包由原运维/集成构建 |
| MySQL业务持久化 | 已实现并有作者真实SQL验证 | internal/app、agentruntime.MySQLStore；无正式文件/内存/SQLite回退，原kernel/release账本不复制 |
| 登录/稳定主体/CSRF | 已实现并有作者真实SQL验证 | 唯一/api/admin/v1/session，product_admins/product_sessions；原管理与AR-1共用 |
| 应用重启历史/事件 | 已实现并有作者真实SQL验证 | 迁移幂等、应用关闭重开、Cookie/事件保留、模型执行计数不增；最终Compose及MySQL进程重启交原组合验证 |
| Session/Run/Step/Message/Event/Checkpoint | 已实现，待最终组合独立验收 | 原AR-1 draft.2；a4c的revision410/attempt修复保留，历史不同SHA不混为本次独立通过 |
| Chat流式/停止/只读恢复 | 已实现，待正常入口同版本浏览器验证 | 正常API与原页面接点明确；旧前端207/6组为其原a4c作者范围，不外推新组合 |
| 模型配置/文本适配 | 已实现正式接线，待真实网关/来源验证 | config/product.example.json models/gateway；原Profile、平台Key、预算Plan、v3票据、Relay；缺真实输入准确失败关闭 |
| tools-v1正式模型 | 已实现受保护适配候选；真实来源仍未验 | product-tools-v1.md：显式配置＋不可变Profile能力/UsagePolicy双绑定，原签票/Higress Relay/唯一计量；缺批准仍tools_protocol_unavailable，不切受控模型 |
| 必需迁移启动/ready/调度门禁 | 已实现FC-M增量，验证见本轮报告 | kernel/release1–3、product1–2摘要/Applied；Agent原表/索引/文档版本；无运行DDL/补标或数据回退 |
| bounded_arithmetic@1 | 已实现并验证 | 原Calculator白名单整数计算；工具Scope/Schema、限值、取消和结果回填 |
| list_visible_models@1 | 已实现，正常目录接原MySQL Profile | 当前可信scope过滤配置引用的耐久Profile；测试目录适配与正式目录分开 |
| 工具接口/执行上下文 | 已实现，新增类型测试 | tool_context.go、agent-tool-interface.md；run/step/call/request/trace/deadline/fence/幂等key均由服务端生成 |
| 审批/幂等/unknown屏障 | 已实现，待最终独立QA | 原decision_id和冻结版本/参数/策略；未知副作用不重放，不新增人工标记成功捷径 |
| 业务预算/唯一计量 | 原实现已验证，正常适配接线待真实来源 | 原Go/MySQL唯一Admit/Finalize，父Run只读known/inflight/held；原两child/两usage证据按各SHA范围保留 |
| 健康/优雅停止/调度所有权 | 已实现，组合进程验证待验收 | healthz/readyz、SIGTERM、MySQL advisory锁单活跃；不声称多活调度，部署先replicas=1 |
| Compose/原生K8s包 | 原MAAS-8/21正在装配 | 后端提供实际入口/迁移/配置，包需从最终同树重打；本清单不替代实际build/up/卷重启或kubectl安装结果 |
| MCP/外部HTTP工具/文件/shell | 未实现正式执行器，仅受控扩展接口 | 不注册任意外部代码或外发能力；需后续权限/Schema/审批/幂等/恢复契约 |
| 检索/长时记忆/子Agent | 未实现 | 当前历史是会话/检查点，不等于长期记忆或多Agent功能 |

作者验证、独立QA、真实模型、生产环境分别记录。没有Secret/真实端点时仍交可构建程序和本地组件结果，不填假Callable/已知0，也不以原Helm关闭工作负载的渲染当正常产品验证。
