# 2026-11-13 消费者关联修复

原 PR #4 的 819c35e 上恢复，工作树无未提交差异。保留五个页面、既有真实 Go 管理接线、五项竞态修复及原操作查询语义。本轮对照 MAAS-12 v1.4 精简输入，优先完成两个明确消费者缺口。

| 缺口 | 当前处理 |
| --- | --- |
| 同一流跨片 created 可变化 | 第一合法 ChatChunk 绑定 created，后续内容/finish/usage 片在回调前逐片比较；合法0保留，新生成独立绑定 |
| HTTP 错误封套可串原请求 | 所有结构化 HTTP 错误先校验响应头 UUID 与 error.request_id；缺头、无效头、坏 JSON 或不一致均为 protocol_error，不采用业务错误码、重置或等待提示 |
| 原 ID 与未知结果 | 仍只从可信响应头取得原 ID。封套错误但头合法时可回查该头；无可信头时未知。写入5xx仍保留 uncertain，无自动重发 |

验证：117项测试通过（原104＋新增13），普通运行11项真实HTTP专用检查明确条件跳过。类型/生产构建、格式及git diff --check通过。定向Edge浏览器5组全部通过，pageerror 0：固定created成功、变化created中断且后片不显示、HTTP错ID不显示预算不足、匹配ID保留预算提示、缺可信ID不查询。每组只发一次生成POST，存在可信ID时仅精确回查原ID。截图和results.json在 artifacts/consumer-binding/；浏览器与Vite在finally中关闭。

复跑：npm test；npm run build；npm run format:check；node scripts/consumer-binding-browser.mjs。

本轮浏览器为明确标注的开发夹具及合成HTTP/SSE，没有Go/Higress/模型运行新证据，没有重跑或累加历史管理浏览器结果。未改共享Go/OpenAPI/DDL或业务账本。独立QA结论由原角色复验，不自行关项。

下一步：用原后端当前获准公开推理入口和真实响应复验固定created、HTTP/header/error ID及原request回查；继续原四流程的非空/未知用量与停止后状态联调。模型、凭证安全渠道、预算及运行授权仍按已有门槛，现有管理页面无需重做。
