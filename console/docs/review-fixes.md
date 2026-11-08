# MAAS-5 三方评审修复验证

本轮从原 PR #4 的 6d0160419156852d7dfd8f3e044f119b777a0ad4 接续，只修改 console/。五项独有缺陷合并跟踪，不累加同一缺陷的评审编号。

| 问题 | 修复与针对性验证 |
| --- | --- |
| 后端 R1 / 架构 AR02 / QA-R01 | 回查捕获原 request_id 与生成/查询轮次；新生成独立回查。迟到结果、错误与 finally 均不能改写 B 的证据、提示或 loading；停止 A 后发送 B 亦覆盖。 |
| 架构 AR01 | 编辑从已确认 spec 初始化，草稿绑定原 UID/resourceVersion；暂停及回滚 ACK 同步基线。旧基线不能套新版本；ACK 无配置快照时必须重读。 |
| 后端 R2 / 架构 AR03 / QA-R03 | 操作查询独立轮次与 loading；新写入、选择变化和卸载使旧查询失效。旧结果、错误、finally 不覆盖新操作或其查询状态。 |
| 后端 R3 / 架构 AR04 | 采纳 ACK 前关联 namespace/name、原 UID、action、operation/resource UID 及 generation。合法但串资源/UID/action 的响应锁住写入，保留原 CR，不重放。 |
| QA-R02 | Key 写入回调检查页面存活；离页后迟到成功不重新保存 secret 或刷新。迟到异常也不更新已销毁页面；不推断服务端未创建、不自动重试。 |

本轮开发者回归：88 项通过（包含原 60 项），HTTP 专用 11 项在普通 npm test 中明确跳过，不能视为通过；实际 HTTP 结果另列。类型检查、生产构建、格式及空白检查通过。Edge 原脚本 10 组与 QA 修复回归 11 组通过，pageerror 均为 0；浏览器数据仍全部为合成夹具。

原三方测试纳入源码：backend-review.test.ts、architecture-review.test.ts、qa-review.test.ts；另有 review-regression.test.ts 覆盖错误/finally/回滚/UID/action/卸载等边界。这些是开发者复跑，不能代替原 QA 独立关闭。

两处原复现脚本适配均保留正确行为断言：后端 R1 原默认夹具让 B 自身也返回 cancelled，现为 B 提供不同终态并断言原 UUID；QA-R02 原测试无条件调用缺陷产生的离页后刷新 resolver，现允许其不存在并新增“只发生离页前一次读取”的断言。QA 浏览器脚本把复现缺陷断言改为修复安全断言，结果明确标记为开发者回归。

## 受控 HTTP 接续

固定后端提交为 2319eb62d84f278d1dd6d444ce52e532e202766e 的独立验证副本，生产 Go/DDL 未修改。运行真实 MySQL 8.4.7 与短寿命 Go Handler，调用真实前端 Api/严格 Schema/恢复适配及 Vue Key、用量组件。随机管理会话/CSRF 仅进程环境传递；不把平台 Key 原值写入证据，结束清理自有数据库/进程/socket。此路径没有推理入口或真实模型。

真实 HTTP 子集 **11/11 通过，0 跳过**：管理会话 401、CSRF 403、Key 创建/元数据、预算 CAS/409、撤销、原 UUID 的 unknown 空回查、空请求/汇总、缺历史 503，以及真实 HTTP 驱动的 Key/用量 Vue 组件。后端原 TestMySQLSessionAPI 同轮通过。未生成实际请求记录，因此这不证明非空 RequestRecord/Usage、流式响应、可信 ID 链或推理兼容；前端未宽松转换任何字段。

原始结果：artifacts/review-regression.json（88 pass/11 gated skip）、artifacts/http-continuation.json（11 pass/0 skip）、artifacts/browser-results.json（10 组）、artifacts/review-browser/results.json（11 组），以及后端控制 API 的 mysql-tests.txt。HTTP 检查由 Go 装配强制核对 11 pass/0 skip，不能因环境丢失而跳过后报绿。

公开 SSE/Usage 归一化及可信 request_id 关系仍由 MAAS-2/3 收敛；没有放宽前端消费者。FE-R02 缺权威历史按实际 503 处理。完整登录、发布历史及生命周期真实 HTTP、真实 Go/Higress/模型流式与 A01–A34 整体验收尚未闭合。本轮未调用供应商、访问上游 Secret、写目标集群或使用 GPU/权重。

## 复跑

在 console/ 执行 npm ci、npm test、npm run build、npm run format:check、npm run test:browser、npm run test:review-browser。HTTP 用例只有显式注入 MAAS_HTTP_URL、MAAS_HTTP_SESSION、MAAS_HTTP_CSRF、MAAS_HTTP_ORIGIN 才启用；仅对获准临时数据库运行。会创建并撤销测试 Key，不可指向生产。附带隔离 Go 测试装配用于同一后端提交，运行完即清理；未运行场景不能用 fixture 替代。

HTTP 装配复跑：从指定后端提交导出独立副本（不在正在实施的后端工作树写入），将 console/scripts/http-harness.go.txt 复制为 internal/controlapi/frontend_http_test.go。设置 MAAS_FE_NODE（WSL 可执行的 Node 路径）、MAAS_FE_CONSOLE_DIR（WSL 控制台目录）、MAAS_FE_CONSOLE_NODE_DIR（Node 所见的控制台目录，使用 Windows Node 时为 Windows 路径），以及原后端 scripts/test-mysql.sh 要求的自有便携依赖缓存；MAAS_TEST_PATTERN 设为 TestFrontendHTTP|TestMySQLSessionAPI，前台执行该脚本。装配沿用原临时数据库守卫与清理，并通过子进程环境发放短时随机管理会话，不打印凭证。Windows Node/WSL 使用 WSLENV 显式传递四项测试变量。该装配文件后缀为 .txt，避免被仓库 Go 包扫描纳入产品代码。
