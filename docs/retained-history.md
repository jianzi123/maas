# FE-R02 权威保留修订

发布侧新增独立迁移 `0002_history.sql`，原七表与 version=1/checksum 保留。当前 CR 经 uncached GET、形状/批准引用解析和 fresh UID/generation/spec 核对后，Observe 在同一发布事务保存新 revision 的不可变 spec、原 namespace/name/UID/generation、来源、实际 resourceVersion 及 DB UTC 首次捕获时间。created_at 表示此候选/保留快照在本库创建的时刻，不把 CR 创建时间当修订创建时间，也不从旧 publication/hash 猜日期。

`Desired.History` 不参与发布意图 hash；状态更新导致 resourceVersion 变化不会制造新 epoch/重复 validation。发布行、候选及历史一并 COMMIT，ACK未知重投原意图只读回同一行；spec 不可被不同内容替换。精确 Spec+Resolution 原始输入及算法受限保存以核对 revision，可能含 opaque credential handle/内部路由元数据，但绝不含 Secret 正文/正文哈希。原始载荷仅私有回滚服务可读；管理 Reader 只读脱敏视图，不输出完整 spec、Secret 引用/值、handle 或URL。

旧 release_revisions 只有 hash 的行不自动采用当前 CR 的 spec/时间。任一旧行缺可核验历史，列表503；无可见历史404。没有编造回填或“空历史成功”。旧行来源的验证导入/清理策略仍需架构与授权；这里不提供猜测性补全或删除历史的 down migration。

`history.Reader` 对原 namespace/name/UID 先做 Access，再在同一只读主库快照取历史/活动修订。cursor HMAC 保护并绑定 cluster、授权 scope、namespace/name/UID、page_size、目录版本、history_seq提交水位和(created_at,revision)顺序。K8s/批准引用评估在 DB 事务外执行，各资格有 checked_at/RV，不承诺跨系统或跨页冻结资格。

实际 KubeLive 使用注入的 uncached reader：同名新 UID 为 replaced，旧 UID 只读；deleted/deleting 阻止回滚；依赖不可用为 unknown，不借旧Ready标eligible。批准引用通过原 Resolver 重验，缺实际 registry/Evaluator 时 unknown/state_unavailable。eligible仅是读取时资格，不是资源预留、Callable或回滚成功。

`RollbackService` 是管理操作工作流内部端口：先核 current UID/RV，从同 UID 历史加载 spec，重验来源互斥/模型别名和批准引用，再 authoritative GET 与一次 resourceVersion/UID更新。409不强写；K8s写ACK未知返回ErrWriteOutcomeUnknown，不用后来CR状态猜成功，不自动重放。公开operation.id持久工作流仍由原管理层接续，不在本端口虚造操作状态。

运行权限：publisher 对历史仅 SELECT/INSERT；不授 spec UPDATE/DELETE。历史 reader 仅读 release_links/publications/release_revisions/retained_release_snapshots，不读业务 Key/预算、诊断或 Secret。Access 和真实引用解析是安装输入，默认缺失时拒绝；没有自动增权、目标集群写入或模型调用。

测试覆盖原发布幂等/重启、真实MySQL历史/ACK、旧hash阻塞、UID/可见性、资格、同时间分页、回滚CAS/ACK未知及迁移checksum。K8s用fake client/受控故障，不把结果当真实API-server或目标环境验收。原内核/计量不另建；共享runtime和真实H1–H4继续按原门槛推进。
