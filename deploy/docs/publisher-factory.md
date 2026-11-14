# Publisher工厂与本地装配

固定f445362a94c18807d0059608a0c4c47968916983中的 `mysqlstore.OpenPublisher(ctx, dsn, cluster, kernelPort)` 消费独立DSN参数，返回拥有该连接的runtime；调用方负责Close。它检查DSN非空、非root、明确库、parseTime、禁用multiStatements和原CURRENT_ROLE，并要求证据端口。失败错误不回显DSN；成功必经WithManagementOperations开启原同事务完成hook。不创建用户、不迁移、不授权，也不从core/operations连接回退。CURRENT_ROLE检查只核已激活角色，不能证明没有额外直接/继承权限。

`cmd/workbench/identities.go`是带localworkbench build tag的临时安装器。它要求自有maas_workbench schema和/tmp/maas-workbench.* Unix socket，按三份原模板安装临时角色/随机用户/default role，再返回四个连接及publisher的内存DSN。`cmd/workbench/main.go`把Core交kernel，History/Payload交Reader，Operations交管理服务，PublisherDSN交OpenPublisher。安装连接不交给业务handler。它是已有本地管理演示入口，不能作为生产core/operator装配。

生产Chart仍只表达实际已有的MAAS_MYSQL_DSN、MAAS_HISTORY_READER_DSN、MAAS_HISTORY_PAYLOAD_DSN、MAAS_OPERATIONS_DSN四个环境引用。没有MAAS_PUBLISHER_DSN消费入口，故不发明第五个env。五身份计划、显式工厂、未来生产适配器分别核验；锁清单中的productionWiringVerified保持false。

payload当前角色为 `maas_history_payload_reader`。旧35字符名称的MySQL1470失败及缩短后完整安装通过，是作者真实临时结果；本轮源码比对确认只改名称，四项SELECT授权字节保持。预检拒绝旧名称和错误模板摘要；不修改目标用户/权限。

本轮认证附件 `01a1d8eb-5ce5-7d72-9249-0909c7f64ca3` 中作者292份来源全部可由固定f445、30cf、e564和附件示例重算。作者还报告同一工厂的关闭/cleanup/原Pause完成、撤state权限无半提交和七项1142/1143拒绝；这些是新增作者证据，未当作新独立QA。R1–R3仍引用ac94/50354a7的独立范围。部署本轮不重跑业务/数据库/浏览器，只核来源、模板、工厂接线和预检负例。

运行实例由原后端保留，status/stop必须在实际统一输出目录执行，日志/状态位于该目录.cache/workbench-service。原TTL、PID等会变化，以最新任务记录及该实例status.json为准；本轮不启动、替换、停止或清理它。真实模型503、Higress/Secret/validation及获准adapter/生产身份/A01–A34门槛保持。
