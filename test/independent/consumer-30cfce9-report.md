# MAAS-7：30cfce9 消费者定向复验

结论：原五项独立消费者用例 **5 通过 / 0 失败 / 0 skip**。原 STREAM-CREATED 与 ERROR-ID 两项缺口在本次合成消费者范围修复，原三个正例保留。另做原 R 回查的两个页面观察，两项通过，单独计数。

## 实际版本与证据层级

- 前端目标：30cfce951df8a858810a035efe51846a75a4ade6；父版本819c35ef9771cca8b8559de4c4e70bcc47436b80。
- 原独立入口：7089cebbfda9ef53d98ea695a1dcf69a256baba0 的 test/independent/stream-20261113.test.ts.in。入口 SHA-256 为13e879f315bf1297ccdd0173915975427cffbe43a483eadb2fbec560265df1a2；临时执行副本完全一致，未改断言或skip。
- 从原QA提交创建隔离分支qa/maas-7-consumer-30cfce9，合入目标前端后的QA基线9c8303c54acd3b54216b6899ec5da10e3c631605。消费者api、fixture、contracts、Playground、锁文件与目标提交逐项一致；保留原QA已有App/Releases的本地工作台集成差异，不涉及此次执行路径。未修改产品代码。
- 继承后端e1bd5020887d092feb892992476bb810512a274e，本轮没有运行后端，不把继承版本当新验证。
- Windows / Node v22.23.4、Vitest5.1.0、jsdom30.1.3、Vite8.3.6、TypeScript5.9.3、Vue3.5.45、Ajv8.20.0。现成依赖复用，package-lock SHA-256 bd1680ee8b9e56eff80bc9bee3f8b49738ba44dbe04da230318a9b2c3201215e，与提供依赖的前端目录锁文件一致；未安装依赖。
- 默认分支快照925d8c55be9ce823d100bf90a5c78cf19ea66d58不包含30cfce9。结论限上述隔离修复版本，不能写成默认分支已修复。
- 证据为合成Response/jsdom；不属于真实HTTP、真实浏览器或模型/Higress端到端验收。

## 原五项唯一结果

| 原用例 | 旧819c35e记录 | 本轮30cfce9 |
|---|---|---|
| 稳定created跨片接受 | 通过 | 通过 |
| created由1变2拒绝 | 失败 | 通过，protocol_error |
| 非2xx错误body的R与可信响应头不符 | 失败 | 通过，protocol_error；不发布内容 |
| SSE错误的R错配拒绝 | 通过 | 通过 |
| diagnostic_only冒充公开Usage.source拒绝 | 通过 | 通过，不触发usage展示 |

原五项单次执行13.27s，退出0。原始JSON保留每项唯一名称、状态、耗时及执行时刻，不把作者117项或Edge五组计入独立结果。测试时刻以原始JSON startTime为准，本地时区America/Tijuana，日期2026-11-13。

## 原 R 恢复的补充观察

调用真实Playground.vue组件、生产Api/stream/recovery消费者，底层仍使用标记清楚的合成fetch和只读查询夹具；不将夹具返回当作主库财务证据。

| 条件 | 页面及调用轨迹 |
|---|---|
| 503错误body R=...0099，可信头R=...0001 | 不采用body的Token预算错误；只按可信头原R发一次精确GET；无查询...0099；生成POST仅一次 |
| 同样的503错误body，缺可信响应头 | 页面显示未收到可信原请求ID、结果未知；没有历史GET；生成POST仅一次，不从body推断R |

本轮合成原R完整值为00000000-0000-4000-8000-000000000001，错误body的R为00000000-0000-4000-8000-000000000099；均是固定测试数据。轨迹不包含消费Key或提示词正文。两项补充观察不与原五项合并计数。

补充观察首轮fork worker启动超时，退出1、0个测试执行，属环境执行失败；原始worker-timeout JSON保留，不计产品失败或通过。改为单threads worker后两项通过，9.81s，退出0。

## 复现与清理

在console目录临时复制两个.in文件到src下对应测试文件，复用匹配锁文件的依赖：

    node ./node_modules/vitest/vitest.mjs run src/qa-independent-20261113.test.ts --configLoader runner --no-cache --no-fsModuleCache --reporter verbose --reporter json --outputFile.json ../test/independent/consumer-30cfce9-results.json
    node ./node_modules/vitest/vitest.mjs run src/qa-independent-recovery-30cfce9.test.ts --pool threads --maxWorkers 1 --configLoader runner --no-cache --no-fsModuleCache --reporter verbose --reporter json --outputFile.json ../test/independent/consumer-30cfce9-recovery-results.json

执行临时副本在结束后删除，保留.in源码、版本与原始结果；测试进程已前台退出。未启动DB、Go、Vite服务、浏览器、模型或长期进程。

## 既有范围与限制

QA-001/002/003按原SHA和受控范围保留，本轮不重跑、重开或扩张其结论。矩阵在原34项基础上增加本次差异字段，所有整体验收状态继续NOT_ACCEPTED。A03/A07/A08/A14新增的只是上述消费者及页面观察证据；Usage Schema拒绝diagnostic_only不能关闭主库最终性、真实非空usage或计量权威来源问题。

Reader实际DSN/窄权限装配、最终Usage、历史409/依赖503、首非空内容测点继续沿MAAS-2及原后端最新SHA收口；本轮没有相应SQL/响应测试。真实Higress/Secret/validation、生产登录、模型/GPU/集群/Helm与A01–A34完整验收仍待原门槛。

本轮只建议关闭STREAM-CREATED/ERROR-ID的隔离合成消费者缺口。MAAS-7保持in_progress；MAAS-12保持in_review，研究成果待成员验收，研究不阻塞MVP。