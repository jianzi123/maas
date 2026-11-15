# 发布管理操作

沿用原 ModelRelease、权威保留历史、RollbackService 和 MySQL 发布控制器。公开 HTTP 装配在依赖本发布增量的后端 PR #2，前端继续原 PR #4。这里的 operation.id 属于管理操作；内部 command_id、validation_intent、生成 request_id 各自独立。

发布迁移新增版本3（`internal/release/management/schema.sql`），原版本1/2和内核迁移不改。`mysqlstore.Migrate` 是显式行政迁移入口，服务启动不执行 DDL。`release_management_operations` 只保存操作范围、目标UID/RV、期望状态、spec摘要、原写入ACK及进度，不保存Secret正文、提示词或通用审计事件。没有后台重放队列或自动过期策略。

## 写入与恢复

管理服务在 MySQL 先提交原 operation.id 的 Unknown 哨兵，再发送至多一次K8s变更。登记提交的ACK未知时仅读回原ID，不发送变更。K8s ACK未知或中途崩溃时保留Unknown；查询只读回原操作，不重试写入、不由当前CR变化推定结果。已确认K8s ACK才记录原UID和实际返回generation，进入Running。API-server冲突/拒绝记录Failed并返回409/403/400；无原ID的HTTP响应丢失继续表示未知。

202表示管理意图受理，Running也不表示Callable。已确认写入的完成态复用原发布账本：精确UID/generation下的Active及原spec摘要，或Paused准入关闭且清理完成。已确认删除按同一UID的不可逆tombstone和清理完成收口，允许API-server删除时递增代次；不套用到更新/回滚，也不用于解决ACK未知。删除完成表示平台准入已关闭且专属资源清理完成，其他控制器持有的finalizer仍可能使CR保留Deleting。用户Secret/PVC等仍由原所有权和保留策略保护。

发布装配显式使用 `publisher.WithManagementOperations()`，在原发布/清理事务内持久化操作完成态；以后切换或删除不覆盖已有终态。管理查询也可从同一原账本补齐已确认操作的完成投影。缺这项装配时不能把查询前已经错过的历史状态猜成成功；未证明的操作继续Running或Unknown。新的装配选项不改变未启用它的原发布角色权限。

回滚复用 `RollbackService.RollbackObject`，它返回单次原API-server写入的ACK对象，不估算generation、不追加第二次写入。原 `Rollback` 签名保留兼容。目标必须来自同UID可信保留历史；提交重新核验引用、保留状态、UID及RV。旧hash行缺来源仍503，本增量没有导入工具或可信旧输入，未导入任何旧行。

## 权限

安装方在已有K8s命名空间权限内授予ModelRelease get/list/create/update/delete；服务不创建Namespace、不扩RBAC、不接管外部对象。配置限定允许的namespace、原授权域和scope，分页逐namespace读取，不要求cluster-wide list。游标绑定cluster、namespace集合、查询namespace、scope和page_size，并封装真实API-server continue；过期409，变更查询条件400。

操作写角色需要目标表SELECT/INSERT及写入结果列的UPDATE；操作查询/完成投影角色需要该表SELECT及UPDATE(state,reason,publication_id,updated_at)。完成投影对其他表仅需以下列的SELECT：

| 表 | 列 |
| --- | --- |
| release_links | cluster_id, cr_uid, namespace, name, last_observed_generation, active_id, desired_mode, admission_closed, cleanup_complete, tombstone |
| publications | cluster_id, publication_id, revision, generation, state, activated |
| retained_release_snapshots | cluster_id, cr_uid, revision, spec_sha256 |

查询角色不因此获得原spec_bytes、release门禁写权限、Key、预算或usage写权限。回滚私有payload Reader继续使用原独立只读权限，不与公开修订视图角色混用。生产启用前由安装方配置明确角色；临时测试的root连接不作为部署权限方案。

## 当前生产能力

管理意图可以独立实现和测试。运行时仍需实际安装批准registry、发布控制器和H1–H4/Secret/validation证明生产者，才能完成Published/Callable。当前生产Operator继续DependencyMissing；本增量未写另一个仓库、目标集群或调用模型。测试中的registry和失败网关producer均明确为受控替身，不证明真实推理可用。
