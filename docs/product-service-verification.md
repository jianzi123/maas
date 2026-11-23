正常产品服务验证记录（2026-11-23 UTC）
======================================

本轮在原a4c修复及#15/#14后端依赖祖先上实现正常`cmd/maas-service`，没有改原前端/部署包目录。初始可构建交付代码7b0230e→四锁c96e598已交原运维/主单，后续最终源码与本记录同提交，标准四锁单独引用。原AR-R01/R02独立验收仍未关闭；不得因本轮作者结果写成独立通过。

实际完成：

| 验证 | 结果和范围 |
| --- | --- |
| 正常程序构建 | 无agentcontrolled/localworkbench标签，Windows低并发go build退出0；listen/config/migrate/serve为实际代码接点 |
| 正常MySQL服务SQL选择器 | 最终4个顶层／含子测试6项通过：原配置→原v3票据（零发包）、released/held原生投影、共享登录/应用重开/零重放、未迁移/非MySQL拒绝 |
| 真实组件 | MySQL8.4.7、原kernel/release/Agent迁移、产品身份/会话表、原Admit策略/Profile/平台Key读取、票据验证器、原MySQLSessionStore、同源Cookie/CSRF及Host |
| 测试适配 | 应用重启用例中ModelClient/Catalog/ContextCounter为显式测试注入，正常二进制无法从JSON选择这些替身；没有将该用例称真实供应商计量 |
| 工具上下文 | TestTrustedToolExecutionContext通过，元数据取自原run/step/call/request/fence/deadline，Schema为JSON对象；执行框架/两个既有工具不另造 |
| 旧核心回归 | 同轮完整SQL选择器中原AR-1/Agent MySQL及两child/两usage用例通过；该轮整体曾因新配置夹具失败，不称整套全绿。修正后只定向重跑产品用例，避免低内存重复扩跑 |

真实SQL用例在自有`/tmp/maas11-mysql.*`数据/socket、skip-networking实例执行，未接目标环境。密码/DSN/Key只在测试临时文件及MySQL使用，不进入证据。运行连接是专属临时数据库测试身份，不当作正式最窄权限已验。应用实例重开保留同一Cookie、原事件字节和一条模型执行计数；重复迁移不清空/重建原平台Key。最终Compose/MySQL进程重启、镜像、最窄角色及浏览器证据由原MAAS-21/8/5/7在最终同树验证。

负结果保留：首次配置消费用例实际失败invalid_input，分阶段定位为admission_claims_invalid；原因是受控Profile夹具漏填route_id，被冻结v3 Schema正确拒绝。只补夹具字段，不改契约/验证器。修正前原始JSONL与修正后的定向JSONL分别保留；初始等待无事件不被当作断言失败，后来取得的真实失败按真实失败记录。

正式模型配置确实读取原Profile/publication、平台Key/当前预算Policy/rate、原Body/Plan绑定、签票Key和时间限制；验证票据不发包、不调用供应商、不写新generation_requests。实际Higress TLS/认证、发布屏障、H1–H4 producer、Redis可信重建和真实tools-v1能力仍依原批准输入/组合根，不用demo替代。正常服务缺这些条件时保留准确不可用原因，不能将应用readyz=200说成模型Callable。

正常服务只用MySQL，不执行SQLite/文件/内存会话回退；serve无DDL，migrate使用独立Secret文件。调度以MySQL advisory锁单活跃，旧在途恢复为needs_confirmation；这不是多活HA声明。产品安装配置/Secret文件/静态产物不是第二份业务日志。没有执行付费模型、目标集群、GPU、远端merge或停止他人服务。

复现：`scripts/test-product-mysql.sh`复用原test-mysql.sh临时生命周期，需MAAS_TEST_MYSQL_BASEDIR和MAAS_TEST_GO_ROOT指向本任务隔离固定工具；可用MAAS_TEST_PRODUCT_PATTERN=^TestProduct仅复跑本轮四用例。原Agent和Installation两个选择器均保留。构建/启动/配置见product-service.md，工具接口见agent-tool-interface.md，功能状态见agent-feature-status.md。
