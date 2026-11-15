# 本轮发布管理验证

2026-11-06 UTC，本地受控结果。开发者验证，不代替独立QA或A01–A34验收。

| 检查 | 实际结果 |
| --- | --- |
| Windows Go1.26 全仓 `go test -json ./... -count=1` | 58 pass、61 skip、0 fail（含父/子测试事件）；未提供本地socket的数据库场景明确skip |
| `go vet ./...`、`go build ./cmd/...` | 通过 |
| 本轮完整MySQL8.4.7/Redis6.0.16共享回归 | 72个数据库/受控leaf场景通过，包含此前58，不累加；终态3.0/诊断0.1-draft.1/未知held及slot边界继续通过 |
| 最终管理HTTP/envtest回归 | 15个管理场景通过；真实API-server/etcd1.36.0、真实MySQL、真实loopback Go HTTP |
| 前端 `428d44e` 原始严格Schema | 37个真实HTTP响应全部通过：ReleaseAccepted8、ReleaseModelRelease1、ReleaseList3、ReleaseOperation10、ReleaseRevisionPage1、AdminModelList1、Error13 |

37项使用Python Draft202012Validator＋FormatChecker对原前端稳定/草案JSON文件校验，没有放宽Schema；这不冒充已完成Vue/Ajv/浏览器联调。该阶段由原前端沿PR #4接续。

15项覆盖：创建/查询/原操作ID、同内核目录、namespace绑定分页、版本和UID冲突、未批准引用及未知字段、实际API-server CAS竞争不重试、registry故障时暂停、恢复/更新、原历史回滚、API-server写后丢ACK、重建HTTP/DB适配器后原IDUnknown不变、删除后精确查询、scope/query校验、会话/CSRF、窄权限完成投影、管理不触发生成或账务写入。创建Paused也可在原关闭/清理完成后成为Succeeded。

原始管理日志及响应：`artifacts/release-management-envtest.txt`、`release-management-http.json`、`release-management-consumer.json`；普通Go事件：`release-management-go.json`。共享72项是单独执行范围，不能与58/父测试事件相加。`scripts/test-release-management.sh`可重新生成完整原始输出；定向复跑通过MAAS_TEST_PATTERN筛选时，其共享数据库部分可能明确无匹配项，不能当作又一次72项通过。

官方envtest固定包SHA512：`302d6a4c3b7d79b8a6168cd9fd5f18e718048211d25012d969d320e06b39672d17338bcd008c29adf98b41048a6f7d80c90ab0165b4b861497ef74c7bc6c1531`。只下载临时测试二进制，没有模型/权重/GPU或供应商调用。网关producer和metadata批准输入是明确测试适配，网关producer返回DependencyMissing，未伪造生效回执或Callable。

本轮没有真实旧历史来源输入，未导入旧行；没有目标集群写入、真实Higress、真实validation、浏览器或DB崩溃/HA验收。自有临时MySQL/Redis/API-server/etcd、测试数据、schema/账号、socket与HTTP进程均已结束并清理，未留下长期服务。生产继续不可调用。
