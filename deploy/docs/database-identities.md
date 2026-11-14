# 数据库身份与候选装配（2026-11-14 UTC）

本轮沿 PR #5 的 `e5647a2f2b44f53d39a80041be94b619f07c29d6` 接续，只改部署目录。默认仍为925d8c55be9ce823d100bf90a5c78cf19ea66d58；固定后端候选为 `f445362a94c18807d0059608a0c4c47968916983`，前端为30cfce951df8a858810a035efe51846a75a4ade6。原独立QA仍只覆盖ac94a373/50354a7的R1–R3；f445新增工厂/五身份与浏览器结果属于作者证据。原工作台组装器来源e564、后端基底0559分别保留，不能扩张为生产装配成功。

| 连接/环境名 | 候选实际消费 | 安装角色模板与边界 |
|---|---|---|
| core / MAAS_MYSQL_DSN | kernel.New；管理目录 ModelGate 的 mysqlstore.New 仍接同一 db | maas_kernel_runtime + maas_release_reader；不因此授予 publisher 写角色 |
| historyReader / MAAS_HISTORY_READER_DSN | openProjectionDB → history.Reader.DB | maas_release_history_reader；5 个 metadata 表/视图 SELECT，不读原 spec |
| operationReader / MAAS_OPERATIONS_DSN | openProjectionDB → management.Operations.DB | maas_release_operations_runtime；SELECT、operation INSERT 及指定列 UPDATE |
| payloadReader / MAAS_HISTORY_PAYLOAD_DSN | 独立 sql.Open → history.Reader.PayloadDB | maas_history_payload_reader；私有服务读取原载荷及保留证据 |
| publisher | 本地工作台调用 mysqlstore.OpenPublisher(ctx, connections.PublisherDSN, cluster, core) | maas_release_publisher；显式函数参数，自动开启完成hook；生产publisher/operator适配器仍缺 |

metadata Reader 的原模板在 `config/mysql/release-permissions.sql`；payload/Operations 新模板在候选 `config/mysql/controlapi-projections.sql`。Operations 的完整 UPDATE 列为 `state,reason,acknowledged,cr_uid,requested_generation,publication_id,updated_at`，还有新建 operation 的 INSERT。它是管理运行角色，不能称为 SELECT-only 或仅查询完成投影角色。action/spec/expected_rv 不在 UPDATE 列内；有效权限仍需核查继承角色和 default role。模板没有 CREATE USER，服务启动不执行 GRANT/迁移。

payload角色现为 `maas_history_payload_reader`。作者完整临时安装复现旧35字符名称的MySQL1470后缩短名称，部署核对确认SQL除角色名外逐字节不变，原SELECT范围保持。不能只改values标签而继续引用旧模板；生产账户/角色的任何变更仍由批准安装方执行，本轮未执行GRANT或账户迁移。

新增工厂位于 `internal/release/mysqlstore/runtime.go`，仅消费显式DSN参数，不读取MAAS_PUBLISHER_DSN或回退core/operations。缺DSN、证据端口、合格DSN选项或原CURRENT_ROLE均拒绝；工厂不创建用户/迁移/授权，default role检查不等于完整有效权限审计。本地身份安装只在带localworkbench标签且受自有临时socket/schema guard保护的入口执行，五个身份交给各自handler/工厂，安装连接不交给业务handler。更多入口与来源见[工厂和本地装配](publisher-factory.md)。

R3 已为 publisher 的同事务完成 hook 补齐窄权限：operation 元数据 SELECT 为 `cluster_id,operation_id,cr_uid,namespace,name,requested_generation,state,acknowledged,desired_state,action,spec_sha256`；UPDATE 仅 `state,reason,publication_id,updated_at`。publisher 无 operation INSERT、action/spec/expected_rv 更新或整个 Operations/core 角色继承。部署检查按精确列集和模板摘要核对；不复制或执行 SQL。

原 QA `50354a705c03383d0102d0d437119afd7ffed8b3` 在 ac94 的真实 default role/启用 hook 流程验证 Activate/原 Update、关闭/Paused cleanup/原 Pause、撤销 state 列后无半提交，以及真实 COMMIT 丢 ACK/同 CommandID 恢复；三项受保护列写返回1143，Key/预算/usage/DDL四项返回1142。原5项和独立10项按原范围引用，本轮未重跑；0559 相比 ac94 只增加 README、本地服务文档和宿主脚本，不能扩张原独立结论到整个后续 PR 或生产。

## Secret 与预检

Chart 0.2.3 的 `core.databaseSecrets` 保留四条实际已有env的独立 `secretKeyRef`，`optional:false`。publisher为显式函数参数，没有新增可供生产core消费的env，因此不虚构第五条环境变量。五身份计划与四env合同分别记录；不使用envFrom、内联DSN或核心键回退。以下仅示例引用，实际Secret由安装方通过批准渠道提供：

```yaml
core:
  enabled: false
  databaseSecrets:
    core: {name: approved-db-connections, key: core-dsn}
    historyReader: {name: approved-db-connections, key: history-dsn}
    operationReader: {name: approved-db-connections, key: operations-dsn}
    payloadReader: {name: approved-db-connections, key: payload-dsn}
```

启用工作负载时四条引用都必须非空；同 Secret 不同键可用，同键拒绝。锁清单 `databaseIdentities.connections` 同时记录 namespace/name/key、非秘密 principalRef、精确角色和权限证据引用，预检逐条比对实际 env 引用与已检查环境名，拒绝同账户、跨 namespace、Reader 写角色、未消费变量、旧源码身份记录、缺证据及未合入候选。预检只验证输入，不解析 Secret 内容，无法证明两个不同引用背后不是同一账户。五条身份计划中 publisher 仍待生产接线，`productionWiringVerified` 保持 false。

受控 control-api 只有 loopback bootstrap，没有生产健康/推理监听；Chart 继续拒绝 `/control-api` 和 `/workbench` 作为生产 core。四条 env 的渲染证明配置合同可表达，不证明未来 `/core` 自动消费它们；实际生产镜像须由后端交付并重新核验。

## 缺配置、故障和恢复

候选源码中空历史 DSN 返回 nil DB，对应历史请求失败关闭；并非无条件启动失败。管理开启时缺 Operations 连接才拒绝启动。配置的 Reader/Operations 连接不可达会拒绝启动，错误不输出 DSN。payload 在启动时可省略，不完整回滚依赖继续不可用；不能借核心连接补齐。显式提供相同账户的 DSN 没有运行时去重，安装预检拒绝共享身份，但生产仍需同实际工厂的权限正反证据。

恢复时先以批准安装工具核对原六份迁移 Applied/checksum，再核对每条连接的 CURRENT_USER/default role/继承权限；迁移身份不进长期 Pod。Reader 正例为允许目录查询，反例为 spec、账本/发布/operation 写和 DDL；payload 只允许批准原载荷范围；Operations 正例包含受理/确认及完成投影，拒绝改 action/spec/expected_rv、账本/发布/DDL；publisher/core 按原写集隔离。修复缺连接或权限后用原 operation ID 查询，不重放写入或模型请求；原 UID、ledger/tombstone/held/slot、ACK 未知语义与保留策略沿 runbook。

## 本轮证据与后端缺口

`candidate-wiring.json`核对新工厂/本地消费与原env入口；`source-inspection.json`与`assembly-inspection.json`核对完整固定来源及部署覆盖层。作者292份来源清单也从认证附件取回并逐文件比对，结果单列`author-unified-source-inspection.json`，不等同本轮重跑作者15组浏览器或MySQL身份测试。历史e564证据移入evidence/history；本轮只执行部署预检、来源及模板策略检查和现有服务只读GET，不启动数据库或重新配置角色。

已交付的OpenPublisher及本地五身份不再列作缺实现。仍缺获准生产publisher/operator适配器、部署身份绑定、真实Higress/Secret/validation及就绪证据。control-api上的只读ModelGate仍与真实publisher写入口区分；生产core不能由本地workbench替代。目标部署、真实模型/GPU、镜像发布、HA与A01–A34未执行，生产继续不可调用。
