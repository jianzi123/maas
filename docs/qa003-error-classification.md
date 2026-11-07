# 回滚依赖与发布引用错误分类修复

2026-11-07 UTC，从发布 `4d45c6f`、后端 `821269b` 续接。读取独立QA报告（附件01a1afe0-39ea-78bb-a0ac-111436480e8d）、MAAS-1后端/架构职责评审及MAAS-2最小补充§4；保留现有唯一调用内核和发布体系。本次只纠正已有管理API的错误分类，不启动尚未收敛的生产装配或整体重构。

## QA-003

原 `history.Reader.LoadSpec` 把缺PayloadDB/Access与非法UID/revision合并为ErrInvalid。现在先校验namespace/name、canonical UID和小写64位修订摘要；非法输入仍400。缺Reader、Access、cluster或私有连接为依赖不可用503；有效授权范围拒绝仍403，未知授权适配故障为503。闭合连接的实际SQL错误也继续503。不会猜历史、回填当前spec或执行K8s写入。

真实HTTP回归保留同UID权威历史、当前If-Match和有效回滚目标：缺私有连接503、非法revision/UID各400、另一有效UID409、缺Access503、关闭私有连接503。失败前后K8s写计数、CR resourceVersion和operation行数不变；恢复原连接后原合法请求202，恰好一次K8s写入。原回滚、CAS、ACK未知及删除后查询场景保留。

## 职责评审中的发布引用分类

依据既有共享契约，不改Error字段或DDL：

| 已知原因 | HTTP/code |
| --- | --- |
| 明确未批准或过期引用 | 403 forbidden |
| 批准/价格版本变化的发布域错误 | 409 policy_changed |
| registry故障或未配置、历史连接缺失 | 503 dependency_unavailable |
| UID/RV冲突 | 409 resource_version_conflict，原行为保留 |

`ReferenceFailure`保留可识别的内部错误链；未知resolver错误不按字符串猜分类，公开响应不包含底层错误内容。`release.ErrPolicyChanged`只用于发布域，不改Key/预算的错误语义。空registry表示配置缺失503；已配置但无批准匹配的引用403。历史资格使用既有reference_unapproved原因，兼容旧内部profile_unapproved别名。

发布HTTP验证真实registry的未批准引用，另以明确的错误类型故障注入验证过期403、版本变化409、registry离线/未配置503及错误脱敏；均无operation、K8s或账务写入。暂停/删除在registry故障时仍按原流程工作。原“未批准引用503”的开发者断言已按共享契约修正；独立QA需要据同一契约复验，不能把旧断言当作兼容要求。

## 本轮验证

- 原因分类单元测试先复现旧错误，再修复；最终11个输入/依赖/权限子场景通过。
- Windows Go1.26全仓70 pass、61 skip、0 fail（父/子事件口径），vet及命令构建通过；数据库skip不冒充SQL验证。
- 临时MySQL8.4.7的历史相关8个leaf场景通过；真实API-server/etcd1.36.0＋Go HTTP管理回归20个leaf通过（17组顶层管理场景，其中引用分类含4个子场景），包含原15，不能相加。
- 48个实际响应按原前端稳定/草案Schema检查全部通过，含原37对应流程；Python Draft202012Validator＋FormatChecker，不冒充新浏览器或独立QA运行。
- 原72项共享数据库、浏览器及QA-001/002结论沿原独立记录保留，本次没有复跑整套72或浏览器。

原始结果为 `qa003-before.txt`、`qa003-after.txt`、`qa003-go.json`、`qa003-history-mysql.txt`、`release-management-envtest.txt`、`release-management-http.json`、`release-management-consumer.json`。测试使用批准metadata和明确失败的网关producer替身；所有管理场景均不触发生成、usage_events或budget_windows写入。自有临时MySQL/Redis/API-server/etcd、schema/账号/socket及HTTP已清理。

共享公开Schema、票据v3、终态3.0、ObservationEnvelope1.0和既有迁移字节未改。生产实例集合/boot代际覆盖、真实Higress/Secret/validation、生产装配及模型/GPU/目标部署仍待原角色按契约和授权接续；生产保持不可调用。QA-003是否关闭由原独立QA按新SHA决定，后端本轮只交修复与开发者回归。
