# MaaS 管理控制台

Vue + TypeScript 独立前端。覆盖管理员会话、模型/来源、Key 创建/撤销与预算、流式试用/停止、请求/用量、ModelRelease 创建/更新/暂停/恢复/回滚/下线和原操作查询。当前交付为 MAAS-5 **受控实现阶段**；真实后端/网关/模型联调待完成。

## 本地使用

Node 22.23.4、npm 11.7.0 为本次验证环境；依赖版本见 package-lock.json。

```sh
cd console
npm ci
npm run dev:fixtures
```

只在开发模式显式启用夹具；界面持续显示模拟数据提示，所有请求由内存夹具处理。夹具无真实凭证，不连接供应商、集群或模型。生产构建即使使用 fixtures mode 也不会启用夹具。

```sh
npm run dev
npm run types
npm test
npm run build
npm run format:check
npm run test:browser
```

默认模式使用同源真实 API，不会在失败时回退到模拟数据。前端 dev server 自身不实现 Go API。实际装配需由同源 HTTPS 入口同时提供静态文件与 Go 路由，保留 HttpOnly / Secure / SameSite 管理 cookie、Origin 校验、no-store 和 SSE 禁缓冲要求。不能把静态页面启动当成后端联调通过。

浏览器脚本使用本机 Edge，亦可用 EDGE_PATH 指定兼容 Chromium 可执行文件；临时 Vite 和浏览器在 finally 内关闭，不留下服务。脚本将截图和结果写入 artifacts/（Git 忽略）。

## 契约和边界

| 文件                                | 来源 / 用法                                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ |
| contracts/openapi-v0.4.json         | MAAS-2 原始 v0.4 快照，SHA256 fab7f71e47af03de3f956437a09e50be47b511991ca87b35bb745ba0228040f5   |
| contracts/query-recovery-draft.json | v0.4.2-draft.1 独立草案，SHA256 4c8f0a01572eb09531bdc09fd62e0ae3cac75e368b3db2b9cf31b3a7c8f5abe3 |
| contracts/j01-v04.patch.json        | 架构交付的 J01 test/replace 补丁；生成类型时仅应用于内存视图，原始快照不变                       |
| src/api/schema.ts / draft-schema.ts | 从各自契约生成，npm run types 可复现                                                             |
| src/api/recovery.ts                 | 独立草案消费者，确认旧服务不兼容时失败关闭，不猜测第一页结果                                     |
| src/fixture-data.json               | 架构草案 35 个正反样例及 v0.4 两类 CR 示例，全部为合成文档输入                                   |

来源附件：v0.4 包 01a1a637-5727-730d-9662-60ec324daa42；查询草案包 01a1ab52-be21-7667-87cf-fcee92844e9c。终态仍为 3.0；本次没有启用 D1 3.1，没有修改共享 Go / DDL / OpenAPI。

管理请求带同源 cookie 和写入 CSRF；消费请求仅带页面内存 Key，省略 cookie、管理 CSRF 和上游凭证。退出、会话 401、离开试用页或 pagehide 时清理对应敏感内容。Key 原值关闭后无法从列表找回；没有 localStorage / sessionStorage / IndexedDB 持久化。服务端鉴权、撤销和结算仍为最终权威。

预算均按原字符串显示，支持 38 位规范整数，不经过 Number 转换。表单不预设周期、价格、币种或 100/日限额；留空关闭维度，0 阻断消费。金额明确标注为原子单位，不猜测小数位/汇率。已知、在途、未知 held 和可用分开显示；汇总不跨币种/价表相加。

流使用 UTF-8 增量解码和 SSE 行解析；必须收到 finish_reason 和唯一 DONE 才表示正常传输结束。EOF、event:error、取消、结算错误均不推定成功；usage 快照覆盖而不逐片累加。停止只中止浏览器传输，不能证明引擎停止、退款或容量已恢复。精确回查仅发送原 X-Request-ID，无 ID 时明确未知，不重发生成。

发布 JSON 编辑器同时支持 ExternalAPI / SelfHosted。空引用和 0 是必须补齐的无效占位，不是批准配置。服务端负责核验批准引用；浏览器仅校验 Schema。配置提交/观测/活动代数及条件分别展示；候选失败不覆盖旧活动 Callable。更新/暂停/恢复/删除带引用版本 If-Match；回滚从服务端保留修订选择，核 UID、resourceVersion 和 eligibility，并携带 expected_cr_uid。

写入和生成均无自动重试。写入 ACK 丢失或成功响应损坏时暂停该页面写入，展示结果未知；已取得原 operation.id 时只读查询。原 ID 只保留在当前页面内存；刷新丢失 ID 后不能从当前 CR 推断原操作成功。409 保留冲突，不自动去掉版本/UID 前置重试。

## 验证与接续

测试覆盖契约正反样例、38 位/零/null、秘密一次展示、未知写入不重试、乱序读取、精确查询旧服务/串 ID/503、回滚 UID/版本、SSE 分字节 UTF-8/CRLF、取消/EOF/error/DONE、会话 401、预算重置提示和带版本暂停。浏览器覆盖桌面/390px、空态、登录退出、Key、取消回查、发布和用量。

MAAS-3/11 需提供同一真实 API 的管理、查询与发布装配；FE-R02/03 草案字段仍待 MAAS-2/3/7 收敛及真实 HTTP 样例复验。需获准模型、Secret 安全渠道、预算/价表、Higress 证据与环境后，才能验证真实 streaming、撤销、取消/迟到终态与容量恢复。当前没有真实模型调用、目标部署或 A01–A34 整体验收证据。

本轮三方评审修复、针对性回归及受控 Go/MySQL HTTP 子集范围见 [docs/review-fixes.md](docs/review-fixes.md)。npm run test:review-browser 复跑 QA 的竞态安全断言；这属于开发者复跑，不代替独立验收。
