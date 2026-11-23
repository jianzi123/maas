# 当前 Chat / Agent 功能与证据范围

本表描述本次前端源码和已读Go候选，不替代MAAS-21最终组合状态。来源：前端原PR17/f939f3b及其本轮增量；后端原PR18/a4c。最终代码/镜像/迁移组合由集成负责人锁定，测试结果见本轮delivery记录；旧207项和6组不自动升级为新部署验收。

| 功能 | 当前状态 | 实际入口/源码 | 限制 |
|---|---|---|---|
| 正式静态构建与部署时公开配置 | 已实现，见本轮构建/静态产物检查 | console/src/deployment.ts、public/console-config.json；npm run build | 正式MySQL部署组合另验；不允许配置API URL/Secret |
| 同源登录/恢复/退出、CSRF | 已实现；正式服务接合待验证 | console/src/App.vue、src/api/client.ts；/api/admin/v1/session | 一个Go会话来源，非双Cookie拼装；静态夹具不证明真实权限 |
| 会话列表/新建/重命名/删除 | 已实现，旧受控Go已作者验证；新MySQL组合待验 | pages/ChatWorkspace.vue、chat/http.ts；/api/agent/v1/sessions | owner与跨用户授权由Go核验，浏览器不提供owner选择 |
| 多轮/持久历史/编辑/重新生成 | 已实现，旧受控Go已作者验证；新MySQL重启待验 | 同上；operation=send/edit/regenerate | 编辑/再生成是显式新操作，保留消息/原命令关联，不自动重放 |
| 普通Chat/Agent同页面、模型能力限制 | 已实现；新部署产物有定向验证入口 | ChatWorkspace.vue、HTTPChat.models/start | text-v1无tools能力时禁止Agent；pending来源不启用 |
| Markdown/代码/工具输出安全显示 | 已实现并有回归 | components/ChatMarkdown.vue、chat/render.ts | Markdown净化、工具结果仅文本；不是执行代码功能 |
| SSE/中文UTF8 offset/超安全整数seq | 已实现；旧Go作者证据保留，本轮静态HTTP回归 | chat/http.ts；events/stream | 原seq/offset严格校验，失败不猜成功 |
| 410/首张页ETag/有界只读恢复 | 已实现并有定向回归 | HTTPChat.read/readSnapshot/events | 整批最多3次重建；持续写入可暂停同步并人工只读重连，不保证收敛时限 |
| 停止/审批/needs_confirmation | 已实现；新Go/MySQL浏览器组合待验 | ChatWorkspace.vue、HTTPChat.cancel/approve | 停止ACK不等于终态；批准需实际策略；unknown不提供批准重跑 |
| 原命令ACK未知恢复 | 已实现，旧受控Go及单测验证 | HTTPChat.pending/recover；session-creation-commands、commands | 只存非秘密operation/hash/session，404/503不能解锁成重新生成 |
| 父run/child用量、known/unknown/held分组 | 已实现；最终SQL唯一结算另验 | chat/http.ts、ChatWorkspace.vue；pages/Usage.vue | aggregation_complete与执行完成分开，不补零、不合并币种 |
| 模型目录/平台Key预算/发布/管理用量 | 已实现，原修复保留；最终服务接线待验 | pages/Models.vue、Keys.vue、Releases.vue、Playground.vue、Usage.vue | 上游Secret不入浏览器，Key不持久化浏览器；发布可调用依实际屏障 |
| Session/Run/Message/Step/ToolCall/Event/Checkpoint | 原后端已实现；正式MySQL装配待本轮交付 | internal/agentruntime：service.go、ar_http.go、store.go及实际文件 | 前端不另建内核/账本，Checkpoint不是可编辑前端对象 |
| 工具注册/Schema/作用域/授权/幂等/超时/取消 | 原后端已实现；最终受控验证/独立QA分列 | internal/agentruntime/tools.go、service.go、AR-1契约 | 可信主体/策略由Go核验，浏览器不能批准未知结果重跑 |
| bounded_arithmetic@1 | 原Go真实工具实现，旧受控结果已交；最终安装待验 | tools.go Calculator；参数a/b/op | 仅有界整数add/subtract/multiply，不是Python/shell执行 |
| list_visible_models@1 | 原Go真实只读工具实现，旧受控结果已交；最终安装待验 | tools.go ModelDirectory；参数{} | 目录必须按可信scope过滤，不能绕过授权读取所有来源 |
| MySQL会话/事件与唯一准入计量 | 原后端实现与作者SQL证据存在；本轮正式入口/重启待验 | internal/agentruntime/store.go及安装组合；实际迁移由MAAS-20/21列版 | 不允许正式默认文件/内存/SQLite回退；UI不能证明SQL持久化 |
| 真实上游tools-v1与模型适配 | 按实际批准/适配分别确认，不能只凭UI宣称已验 | Go ModelClient/准入网关适配，capabilities | 真实端点/凭据/额度未具备时准确标未执行，不回退测试模型冒充真实 |
| 文件上传、文件读写、shell、MCP | 未实现产品能力 | 无可用前端入口 | 不列已实现；如有接口设计也不等于可用工具 |
| 检索/向量库/长期记忆 | 未实现产品能力 | 无产品入口 | 持久聊天历史不等于检索或长期记忆系统 |
| 子Agent/多Agent/外部工具市场 | 未实现产品能力 | 无产品入口 | 可替换工具边界只属于受控扩展设计 |

后端工具接口文档由MAAS-20原负责人交付；本表不另写一套协议。最终交付负责人应按实际组合更新“待验”与入口命令，并保留作者、独立QA、真实模型和部署四类证据边界。

