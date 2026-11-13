# 数据库身份与候选装配（2026-11-13 UTC）

本轮沿 PR #5 的 `36806456333f5c8c6ee0651bb3088776cf354728` 接续，只改部署目录。默认分支仍为 `925d8c55be9ce823d100bf90a5c78cf19ea66d58`；后端候选为草稿 PR #6 的 `d2d7869fe16b8968d6ca5b00a63560c322b84dc1`，尚未合入。runtime-interface 和依赖清单记录候选 SHA、默认 SHA 与逐文件摘要；它们不证明镜像已构建或生产装配成功。

| 连接/环境名 | 候选实际消费 | 安装角色模板与边界 |
|---|---|---|
| core / MAAS_MYSQL_DSN | kernel.New；管理目录 ModelGate 的 mysqlstore.New 仍接同一 db | maas_kernel_runtime + maas_release_reader；不因此授予 publisher 写角色 |
| historyReader / MAAS_HISTORY_READER_DSN | openProjectionDB → history.Reader.DB | maas_release_history_reader；5 个 metadata 表/视图 SELECT，不读原 spec |
| operationReader / MAAS_OPERATIONS_DSN | openProjectionDB → management.Operations.DB | maas_release_operations_runtime；SELECT、operation INSERT 及指定列 UPDATE |
| payloadReader / MAAS_HISTORY_PAYLOAD_DSN | 独立 sql.Open → history.Reader.PayloadDB | maas_release_history_payload_reader；私有服务读取原载荷及保留证据 |
| publisher | 此管理入口无独立 publisher DSN 配置项 | maas_release_publisher；真实发布进程接线/证据仍缺，不注入无人消费的变量 |

metadata Reader 的原模板在 `config/mysql/release-permissions.sql`；payload/Operations 新模板在候选 `config/mysql/controlapi-projections.sql`。Operations 的完整 UPDATE 列为 `state,reason,acknowledged,cr_uid,requested_generation,publication_id,updated_at`，还有新建 operation 的 INSERT。它是管理运行角色，不能称为 SELECT-only 或仅查询完成投影角色。action/spec/expected_rv 不在 UPDATE 列内；有效权限仍需核查继承角色和 default role。模板没有 CREATE USER，服务启动不执行 GRANT/迁移。

## Secret 与预检

Chart 0.2.1 的 `core.databaseSecrets` 为四条固定 env 提供独立 `secretKeyRef`，`optional:false`；不使用 envFrom、内联 DSN 或核心键回退。以下仅示例引用，实际 Secret 由安装方通过批准渠道提供：

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

`candidate-wiring.json` 是 12 项源码核对，`source-inspection.json` 是精确候选/默认源码摘要比对；`permissions.json` 比对 metadata Reader 的 5 项 SELECT。候选原 Go 测试 `TestProjectionMissingDoesNotFallback` 实际执行了空连接工厂。Chart/预检使用合成输入；本轮未启动数据库、读取真实 Secret 或验证 MySQL/default role/继承权限，未验证完整生产进程启动。

原后端后续需交付真实生产入口、独立发布进程身份和受控生产装配/就绪证据，明确 ModelGate 的只读连接与 publisher 写连接的角色边界；payload/Operations 模板已存在，不再沿用“缺模板”的旧结论。目标部署、真实 Higress/Secret/validation、模型/GPU、镜像发布、HA 与 A01–A34 未执行，生产继续不可调用。
