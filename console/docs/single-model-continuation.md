# 单模型调用接线准备

本轮沿PR #10的aa9720f接续，保留UI16-U2代码e323c54及其10项作者定向通过记录，不将作者结果当独立QA关闭。

当前后端cmd/workbench明确inference_available=false，cmd/control-api尚无公开推理监听/完整生产证明装配。因此本轮未尝试供应商或真实模型。前端原来按local模式一律禁用发送；现在本地Vite安装适配可由安装方在既有loopback管理API环境中显式设置MAAS_LOCAL_INFERENCE_ENABLED=1，启用同一origin的/v1/chat/completions代理。省略或0保持原关闭行为，其他值拒绝启动。它只表示安装方已提供该端点，不改变服务端Callable、Key鉴权/预算、路由或验证准入；当前管理专用workbench不得设置1。编译后的workbench继续关闭，普通生产模式不采用此开发开关。

配置已有短期会话和获准后端后，在console执行npm run dev:go；没有就绪端点使用npm run dev:fixtures查看明确标注的受控演示。MAAS_LOCAL_API和原会话/CSRF/expiry沿原文档，不在VITE变量注入凭证，不新增上游URL或第二套账本。生成仍只使用页面内存平台Key且省略管理cookie；原request_id、轮次、unknown及无自动重放不变。

本轮可重放输入：

- known：流式文本正常DONE，精确原R返回非空记录/已知Token19；金额及预算按原回查投影独立展示。
- unknown：正常DONE但Token未提供；非空记录中的actual/null、held和容量继续保留。
- stop：停止浏览器传输后用同一R查询cancelled，不声称引擎停止或退款。
- error / eof：上游错误或无DONE断流，保持interrupted并只查原R，不自动再生成。
- 默认关闭时，即使目录样例callable=true也不发送POST。

复跑命令：npm ci；node node_modules/vitest/vitest.mjs run src/single-model-mode.test.ts src/single-model-replay.test.ts src/usage-exact-review.test.ts src/usage-exact-interleaving.test.ts；node scripts/single-model-browser.mjs；npm run build；npm run format:check。

结果：20项定向通过（原U2 10＋新增交互6/配置4），5组实际Vue/Edge合成HTTP/SSE浏览器回放通过、pageerror0。原始记录artifacts/single-model-replay.json及artifacts/single-model/results.json，截图按场景命名。脚本finally关闭浏览器和Vite，不留服务。

局限/下一步：待原后端提供获准的同源公开推理入口、准确ExternalAPI模型/模式/profile、Higress与Secret/validation证明及调用额度/预算/价表，再把相同输入绑定实际候选SHA、原R和后台权威非空用量作端到端复验。现有发布/Key/预算/管理用量真接口复用，不重跑原UI16/Delete闭环，不把合成非空数据当真实用量。共享字段若变化由MAAS-2协调。
