# 发布协调的耐久意图与真实进程崩溃实验

调用超时至少可能意味着没执行、执行中、已提交但ACK丢失。只写一段“重试幂等”解释不了这些状态。本章用[durable_lab](../../../tools/perf/engineering/durable_lab.py)实际启动子进程，在三个提交截点调用os._exit，再由新进程读取数据库恢复。

实验使用两份本地SQLite：journal.sqlite是命令与owner状态，remote.sqlite模拟外部资源服务。没有连接项目MySQL、Kubernetes、Higress或模型。真实本地持久化与fake外部资源明确分开。

## 命令身份与状态表

原命令为publish:M1:p7，payload固定CR UID、revision与publication。摘要来自规范化JSON，禁止NaN。命令表保存id、hash、原payload、state、resource_uid、prepare_pid和apply_writes。

同id同payload返回原状态；同id异payload拒绝，不覆盖原行。owner另保存fence与deleted。prepare和record_applied都在短事务内核验当前owner，外部ensure发生在两次本地事务之间，没有持有journal事务等待外部动作。

外部fake服务也耐久地以原command记录hash/UID。同command重查只返回原UID，冲突hash拒绝。这个外部幂等保证是实验自己实现的；不能推断任何供应商生成API也支持相同语义。

## 三个真实退出点的恢复矩阵

| 退出截点 | 子进程exit | 恢复前journal | 外部资源数 | 应用提交数 |
|---|---|---|---|---|
| prepare已提交、外部未做 | 91 | prepared | 0 | 0 |
| 外部已提交、journal未确认 | 92 | prepared | 1 | 0 |
| journal applied已提交、ACK未返回 | 93 | applied | 1 | 1 |

新进程恢复后三种情况都应为applied、资源1个、apply_writes=1。同命令再试仍返回同UID。原prepare_pid与恢复pid不同，用来区分真实重启和同对象再次调用。

第二行是关键：外部副作用已经存在，不能根据本地prepared判断“没执行”。恢复必须按原身份查询可信外部事实，确认归属与payload，才能记录原结果。若外部不提供可信回查，需要保持unknown或进入人工/协议规定的恢复路径。

第三行只读回原结果，不重新触发生成、验证或创建一份新资源。MaaS原始生成attempt、业务终态和发布命令有不同身份域，不能互换。

## owner 在副作用后失效

额外实验在外部资源创建后将owner fence从1增到2。旧进程尝试提交applied被拒绝，journal仍prepared，外部资源仍存在。新owner按同一原意图恢复并记录。

fence限制后续受控写入，不会撤销已发生的副作用。生产inventory必须能追踪这份资源；不能因为旧owner提交失败就直接删未知UID，也不能假装“从未创建”。原命令与资源证据需要保留。

deleted tombstone则阻止新的执行；测试确认删除后不创建外部资源。相同名称的新UID不继承旧命令、回执或清理权限。历史结果可作为原操作查询，不等于当前发布仍可调用。

## 从实验移植到既有 Go/MySQL 接点

项目继续由现有Go/MySQL发布服务实现耐久锁序、owner/fence、inventory和活动CAS，Operator使用已有port。SQLite实验没有提供生产迁移或替换数据库的方案。

实际接线至少需要：原UID/精确修订输入、批准依赖与当前授权；外部动作的可回查身份和可信实例/UID；短事务内的冲突判定；提交ACK未知读回；恢复失败保持关闭；网络调用不占核心账本长锁。

Kubernetes resourceVersion CAS与MySQL事务分别保护各自状态，跨两者没有自动原子性。若资源已创建但本地尚未记UID，恢复不能仅按名字认领；共享对象只修改本模型拥有条目。停止/排空和财务held仍分别取证。

## 运行与检查

~~~text
python tools/perf/engineering/run.py --lab durable --output tools/perf/reports/my-durable-run.json
~~~

使用新输出文件名。报告记录每个退出点的恢复前状态、资源数、应用次数与恢复结果；同目录保留独立SQLite文件可复查。测试结束会清理自己的测试临时目录，正式实验输出保留供审阅。

进程退出证明的是这些具体截点的本地SQLite重开与应用幂等，不证明断电、磁盘故障、MySQL多副本、真实网关回执或Kubernetes垃圾回收。事务接口细节参考[Python 3.13 sqlite3](https://docs.python.org/3.13/library/sqlite3.html)，项目实现以原共享契约与后端提交为准。
