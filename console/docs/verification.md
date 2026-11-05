# MAAS-5 受控前端验证记录

本次交付是前端受控实现，供评审验收；真实 Go/Higress/模型集成与 A01–A34 整体运行验收均未完成。

| 检查 | 实际结果 | 范围 |
| --- | --- | --- |
| npm test | 60/60 通过，2 个测试文件 | 35 个原契约正反样例的消费者验证 + 25 个客户端/组件行为检查 |
| npm run build | vue-tsc 和 Vite 生产构建通过 | Node 22.23.4 / TS 5.9.3 / Vue 3.5.45 / Vite 8.3.6 |
| npm run format:check | 通过 | 前端源码、生成类型及脚本 |
| npm run test:browser | 10 组检查通过，pageerror 0 | 本机 Edge headless + 临时 Vite + 明确标记的内存夹具 |
| 生产包检查 | 无 fixture_only_not_a_credential、synthetic_document_examples_not_runtime_results | 夹具数据未进入生产 bundle；默认真实 API 失败不降级 mock |
| J01 | 表单无臆定默认，零/null/38位均检查 | 原始契约字节保留；生成类型仅应用架构交付的 J01 文案补丁 |
| git diff --check | 通过 | 待提交文件空白检查 |

浏览器实际检查：桌面模型目录/两类来源；Key 显式 0 和 38 位金额/原值一次展示并关闭；流式停止及原 request_id 回查/未知 Token/隔离容量；候选失败但旧活动可调用/保留修订；202 仅为 Accepted；请求明细和币种/价格分列汇总；无 localStorage/sessionStorage 写入；390px 无页面水平溢出；空目录；管理员登录/退出。桌面、移动、发布、Key 和停止后回查截图已产生，并逐张检查关键布局。

边界处理验证：写入和生成不自动重试；ACK 丢失/损坏响应不猜成功；管理 CSRF/cookie 与消费 Key 分离；错误预算重置时间/Retry-After；SSE UTF-8 和 CRLF 分片、error、EOF、DONE；旧服务忽略精确查询参数或返回其他 ID 时失败关闭；回滚同时核 UID/版本/资格，暂停带 quoted If-Match；乱序只读结果不能覆盖新结果。

证据包包含 tests.log、build.log、browser-results.json 和五张截图。全部业务数据是模拟/架构文档样例；没有真实模型/网关/数据库联调、目标部署、Secret 访问、GPU 或供应商调用。既有后端 35 个数据库场景未在本次重跑。

后续由原后端和架构提供同一真实管理/统计/发布 API，并与 QA 收敛 FE-R02/03 草案后接通；本前端保留草案隔离。真实试用、撤销可见性、取消/迟到终态/容量恢复与 A01–A34 需相应环境、模型、预算/价表、凭证安全渠道和授权后再取证。
