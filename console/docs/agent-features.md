# Chat / Agent 功能与当前证据

2026-11-26，原前端在统一基线4402/d27上增量修复。表中“本轮作者”指自有正常Go/MySQL同源站点＋明确离线模型；不是独立QA或真实供应商。原217/11条件skip、静态HTTP夹具范围与独立QA4402九项通过各自保留，不累计全仓。QA-CHAT-RACE-001必须由原QA按新准确SHA签收，补抓正常不自行关项。

| 功能 | 状态和本轮范围 | 源码/入口 | 限制 |
|---|---|---|---|
| 生产静态构建/公开配置 | 已实现并作者站点验证 | src/deployment.ts，public/console-config.json；/console-config.json | 白名单无URL/Secret；可选playground.enabled默认false，生产不读Vite开发变量 |
| 同源登录/CSRF/会话 | 作者验证；首次401输入竞态已修 | App.vue、api/client.ts；/api/admin/v1/session | 输入在bootstrap期间禁用；重启同Cookie/CSRF的受控结果不等于跨用户完整矩阵 |
| 旧在线试用 R-P01 | 已实证405并修页面门禁/Chat引导 | pages/Playground.vue、App.vue | d27未挂/v1；不输入真实Key探路、不直连供应商。原受保护入口只有安装者明确声明才启用 |
| 会话/多轮/流式Markdown | 已实现，作者正常Go/MySQL受控Chat验证 | pages/ChatWorkspace.vue、chat/http.ts、ChatMarkdown.vue | 中文/emoji观察与原child关联已记录；真实供应商流/费用另验 |
| 模型能力/批准可用性 | 实际capabilities展示；空生产模型负例和本地拒绝回归 | HTTPChat.models/create/start，ModelChoice | 不根据别名猜Agent；未批准/无tools能力在写入前拒绝，准确capability_unsupported |
| 工具参数/批准/结果 | 作者站点验证两个真实安全工具 | /api/agent/v1会话/Run/ToolCall/Approval；chat/http.ts | 内部Call.id用于API；供应商SourceID回填由Go处理，不由浏览器拼装 |
| 拒绝/工具错误/未知 | 原拒绝记录纯GET恢复，终止/隔离视图回归 | ChatWorkspace.stepOutput、HTTPChat.approve | 终止无结果不永久等待；needs_confirmation不自动批准/重跑。真实上游EOF/错误/未知消费本轮未验 |
| 停止与轮询并发 | 作者验证已准入child→ACK202→cancelled；六项定向顺序/负例 | HTTPChat.eventEpoch/readEpoch，ChatWorkspace.cancel/approval | 原QA失败保留，待独立签收；不拿自然完成当停止成功 |
| 410/首张页ETag | 当前站点真实工具页410、旧102消息QA范围保留 | HTTPChat.read/readSnapshot/events | 整批作废；三轮GET＋25/75ms有界等待；事件cursor依持久seq，元数据变更不一概失效 |
| 断开/刷新/重启恢复 | 作者同源站点原ID/哈希/计数验证 | deployed-smoke/workbench/restart.mjs | 断开只停止GET观察；重启只操作自有Compose，保留卷与身份，不重发生成 |
| 原命令未知ACK | 原实现保留，相关消费者回归 | HTTPChat.pending/recover；创建命令/会话命令 | 只存非秘密operation/hash/session，不存正文/Key；404/503不证明未执行 |
| 父run/child和用量 | 作者实际Go/MySQL原ID只读核对 | ChatWorkspace计量区、pages/Usage.vue | 不把completed等同聚合完成；未知不补0，币种/价表不合并，不由前端结算 |
| Key预算/模型发布/完整管理 | 原实现保留，本轮未验真实目标 | Keys/Models/Releases/Usage页面 | 默认管理装配受限；不能据正常健康或受控目录声称完整Operator/发布目标可用 |
| Session/Run/Message/Step/ToolCall/Event/Checkpoint | 原Go已实现，当前消费正常MySQL服务 | cmd/maas-service、internal/agentruntime、internal/app | 不另建内核/账本。FC-1迁移/锁ctx及新正式tools桥仍由MAAS-20/21收口 |
| bounded_arithmetic@1 / list_visible_models@1 | 作者实际参数/必要批准/结果/attempt验证 | internal/agentruntime/tools.go | 有界整数计算与可信scope目录，不是shell或任意代码 |
| 正式供应商 tools-v1 | 新适配沿原后端推进，本前端未接固定新Go头验收 | ModelClient/Go-Higress唯一准入与计量；既有AR-1字段 | 不把离线模型或空models当作真实源通过；没有新增真实调用/付费/Secret授权 |
| 文件/shell/MCP/外部HTTP工具 | 未实现产品执行能力 | 无产品入口 | 扩展接口设计不计已实现，不添加空按钮 |
| 检索/长期记忆/子Agent/多Agent | 未实现产品执行能力 | 无产品入口 | MySQL会话历史不等于长期记忆/检索系统 |

构建/差异回归、原失败、截图与受控/未验范围按本轮准确提交交付；测试脚本不是用户业务存储。只有Go/MySQL是业务准入、计量与会话真源，前端不补造状态或账本。
