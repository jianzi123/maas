# Usage 权威性与管理连接接续

从已合入默认分支925d8c5接续，原PR #1–#4均已合并，本轮新建增量PR，不重开原实现。已读取独立QA-003报告：bfc1f7d/8ccf6c0的27/27 HTTP、24个失败无副作用、恢复后一次回滚202通过，沿原受控范围关闭；本次不重派该缺陷。

## 内部适配策略

`Profile.UsagePolicy`可选且绑定不可变profile摘要/调用快照。旧profile无此字段时JSON字节保持兼容，但旧“最后非递减即最终”的Usage不再可用作实际结算。无策略的receipt继续耐久诊断，actual不可获取、Token/金额原held保留；冻结终态3.0不允许incomplete succeeded，因此沿原逻辑降为失败并拒绝正常DONE。不能临时从公开请求、头或供应商自称字段选择策略。

批准策略必须有AdapterRevision并明确Mode：

- `final_only`：每个usage receipt都被该固定adapter声明为最终，后续相同快照可重复；任一父计数、缓存/推理子集或缺失状态变化都拒绝。12/7/19→12/8/20和cache4→5即使递增也冲突。
- `cumulative_until_finish`：明确批准的adapter在合法finish事件前发累计进度，finish边界封闭最新完整快照；若finish前没有usage，首个finish后usage是最终。边界后只接受逐字段相同重复。进度不求和，不从旧快照补最终缺失字段。此模式仅用于明确具备该协议保证的adapter，不能给任意Higress/provider默认启用。

两种规则仍要求合法finish、唯一DONE与EOF完整边界后才结算。冲突receipt先保存diagnostic_only，再记usage_conflict并失败结算，无正常DONE，actual=null和原held保留。即使收到最终receipt，EOF/取消仍不成为正常完成；slot继续依赖原独立关闭证明。非流式须有批准策略及合法完整响应才可取其usage。公开Schema、终态3.0、ObservationEnvelope1.0与原迁移不变；D1未启用。

本地测试fixture显式批准其原累计至finish协议；这不证明真实provider或Higress具备同样保证。实际Higress/Secret/validation及全接流副本/boot证据仍未齐，生产依旧不可调用。更复杂的独立progress/final标记、增量计数或另一结束事件须先由架构/算法批准adapter规则，不在此猜测兼容。

## 管理身份装配

`cmd/control-api`现在显式读取 `MAAS_HISTORY_READER_DSN` 与 `MAAS_OPERATIONS_DSN`，不再把核心MAAS_MYSQL_DSN隐式传给History.Reader或Operations。缺历史连接时对应历史读失败503；启用管理写而未配置operations连接时启动失败。私有 `MAAS_HISTORY_PAYLOAD_DSN`继续独立。任一配置连接不可达时启动明确拒绝，错误不回显DSN。现有本地workbench是明确临时组合环境，未改成生产装配。

运维使用既有maas_release_history_reader角色及新增 `config/mysql/controlapi-projections.sql`模板；operation角色只有管理操作写集和完成投影所需列，私有payload身份不授给公开历史投影。模板不创建用户、不在服务启动执行、不修改目标权限。安装方仍须核定三者权限及default role；显式DSN不等于自动证明其账户窄权。

本轮实际连接测试通过管理入口同一个openProjectionDB工厂创建临时SELECT-only身份，Reader可读允许视图，不可读原spec或写release/operation/DDL；缺配置不会退回核心连接。原权限/故障矩阵继续针对性验证，不把模板等同真实生产授权。

## 本轮验证与接续

真实临时MySQL8.4.7/Redis6.0.16共80个数据库/受控leaf通过：包含原72及新增Usage7、Reader身份1，不与历史轮次相加。新增7项为同最终、冲突最终、冲突缓存、合法累计进度、缺策略、进度后EOF、最终收据后取消。冲突时两份receipt和usage_conflict终止均耐久，终态唯一，未按较大最终值入账；未知Token held140保留，未发正常DONE。真实网关仍是替身。

全仓Go测试、vet、命令构建通过，缺临时socket的数据库测试明确skip；后续单独新增的“进度缺字段不抹掉高水位”纯函数回归亦通过。原始输出为artifacts/continuation-mysql.txt及usage-authority-go.json。自有临时进程、schema/账号/socket和数据已清理。未跑新的浏览器、目标部署、真实模型/GPU或A01–A34验收。

管理连接的新环境变量需由安装方配置，旧部署接口源码快照尚未重新锁定本增量；不能把原Chart记录视作这次生产装配完成。下一步由原架构/算法核对两种显式adapter语义并提供真实批准版本，再由原QA定向复验；真实H1–H4/Secret/validation和实例集合仍缺，生产保持不可调用。
