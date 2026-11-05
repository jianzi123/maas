最新：已按v2修订oracle并复验实际后端6dc3914；已有48项通过，独立QA12项9通过/3失败，两个问题均未关闭。

本轮依据 Mika 评论 `01a1aba0-d123-7001-b0bf-91fae22e68bf` 及 MAAS-2 原清单 v2 修订独立 oracle。QA-001/002 均保持开放；终态 3.0、ObservationEnvelope 1.0 不变，D1 3.1 未切换。

## 变更依据与原记录

原 QA 提交 `ca9fcdde6d2d28293b8a218935f88c08b1319dcf` 将 total=19 的位置断言放在 terminal.usage。架构 v2 已明确该片段不是最终计费收据，现将五项 12/7/19/4/3 的断言移至独立耐久诊断。原源码仍可从原提交读取；原运行失败记录按字节保存在 `history/qa-v1-failures.txt`，其 SHA256 与旧 `results.json` 中 qa-mysql-final.txt 完全一致。旧 report.md/results.json 为历史结果，不能作为本轮修复结论。

依据附件为 `01a1ab9a-d947-7c65-9398-6875fab20d5c`（MAAS-2-QA-closure-v2.zip）。本目录 contracts 保存原诊断草案和21个原正反样例；没有修改共享协议或为诊断增加公开 API。

## 新 oracle 的具体行为

`TestQAUsageBeforeTransportLoss` 保留 EOF、writer 失败两个场景：

- 第一次向客户端写字节前，从新 SQL 连接的只读事务读取实际耐久 receipt；核对五项、request、owner/fence、原始冻结 snapshot_sha256 与原 invocation_binding。
- 终止后新建 Store 并再次独立读取 SQL，要求 receipt 与 termination 顺序正确，原因分别为 eof / client_write_error。新连接重读不是 OS 崩溃或 HA 证明。
- 校验原 Terminal Schema；五项终态计数及权威 token/cost 实际仍为 null，不再接受已收到分片却标 *_before_usage；该夹具使用 not_provided。
- Token held=140、金额 held=原 plan.Money（此夹具520000），请求计次1、request/terminal/summary各一次，生成尝试一次，无正常 DONE。
- 无 H2 关闭证明先 QUARANTINED；受控关闭证明只释放原 allocation，不改终态/held；新请求复用 slot 后重放旧关闭证明不释放新 allocation。

初读PR #2为4f3eb93；本轮期间发现实际新提交6dc39149a9d44b1bcca57cec59a0920f535ac1eb并接入QA分支复验。其relay部分修复截止分类，但未新增usage耐久诊断；QA-001迁移/读取接点仍未交付。不自行创建 `request_usage_diagnostics` 表、不安装诊断替身、不猜字段名。

为适配实际交回的持久层，本次 QA 只读适配器要求两个环境变量：

| 变量 | 所需真实读入口 |
|---|---|
| MAAS_QA_DIAGNOSTIC_READ_SQL | 实际表/生产持久层投影的一条 SELECT，绑定原 request_id 的一个 ?，一列 JSON 诊断封套，可返回多行；不从内存或合成 JSON 返回成功 |
| MAAS_QA_SNAPSHOT_HASH_SQL | 一条 SELECT，绑定同一原 request_id 的一个 ?，恰一行一列核心在准入时持久化的冻结摘要；不能对当前 profile 或重建 Snapshot 再 hash 冒充 |

SQL 仅允许 SELECT、单个绑定，不含语句分隔符，运行在新连接的 ReadOnly 事务。此处是 QA 读取配置，不是新的产品接口；须在实际后端 DDL/读取入口交回后填写，不提供虚构 SQL 默认。缺失变量、不可读或零记录均明确失败，绝不 skip/视为通过。生产诊断读取 API 的权限测试仍须单独取证。

复测入口：

```sh
# 仅在获得并核对实际后端 SHA、只读 SQL、迁移/权限及保留策略后配置上述变量
MAAS_TEST_PATTERN='^TestQAUsageBeforeTransportLoss$' bash test/acceptance/run.sh
python test/acceptance/review_diagnostics.py --closure-dir ../inputs/closure-v2/unpacked --output artifacts/qa-v2-static.json
```

## 本轮实际验证与限制

独立静态35项通过（包含21个Schema正反样例），覆盖7份源文件清单摘要、2份冻结QA输入、原失败记录摘要、3份产品协议快照不变及Schema元校验。不是架构师53项重跑，不与历史80项或原35个数据库场景累加。

在旧产品 SHA 上对**修改后的测试入口做反向验证**：EOF/writer 两例均继续失败、0 skip；已确认实际 null、Token held140、金额 held520000，并执行原终态/汇总唯一、无DONE/无重发、slot关闭及复用边界。失败在实际诊断/冻结摘要读入口缺失及旧 before_usage 分类。未获得修复 SHA，因此本轮不称“修复复测”，不关闭任何问题；缺少读入口也不能证明某个已建产品表丢数据。

旧35个数据库场景作为新48项的一部分已重新执行，不能相加。历史全仓50个Go通过事件、性能41项和草案80项本轮未重跑。QA-002原首片后截止现通过，但先deadline后父cancel的补充函数反例失败，仍保持开放。

## 后续完整运行门槛

`retest-v2.json` 逐项列出：12项诊断/账务/slot门槛，19格截止/取消矩阵，以及 v2 原表的11项 FE-R02/03/兼容门槛，全部保留未在修复后运行的状态。当前两个用例的旧基线反向验证不替代这些关项。

须补实际 receipt 追加接口与故障注入，验证写失败/体积或次数上限、重复/冲突/旧fence、receipt ACK未知、终态ACK未知；保留期沿批准策略，不新增默认天数。QA-002 在清理 cancel 前采原 sendCtx 原因，区分自身deadline/更早父deadline/显式取消与纯EOF；未准入场景不得强造请求或计次。writer错误的诊断为 client_write_error，不能当作用户已点击停止。

FE-R02/03 保留原草案字段与现有只读 probe；下表为完整关项范围，均未执行 HTTP/浏览器验收：


| 门槛 | 实现与断言 | 证据 |
|---|---|---|
| R02-1 历史真源 | 保留修订有耐久来源，按namespace/name/原CR UID限定；包含已删除/同名替换历史。批准引用、snapshot缺失/清理和当前K8s未知分别给blocked/unknown；不标eligible | MAAS-11持久层＋MAAS-3管理路由；QA原/新UID、重启、空历史404与底层故障503 |
| R02-2 分页 | cursor绑定原namespace/name/UID及稳定(created_at,revision)顺序；不同UID/查询上下文的cursor拒绝，不能跨UID泄漏；并发插入不重复/跳过既有序列，资格值注明读取时刻 | 后端/QA；多页、同时间戳、并发插入和坏cursor证据；不承诺跨页冻结资格 |
| R02-3 回滚竞争 | 新流程发送expected_cr_uid及If-Match；服务端从当前UID历史加载目标并重验批准引用。重建/更新竞争409，依赖不可用503，无隐式移除UID或force重放 | 原后端/前端；受控写入夹具验证错UID、旧版本、失效引用。旧服务忽略未知字段也不能被当作支持 |
| R02-4 ACK未知 | 可信operation.id仅查原operation；404/503/Unknown及无ID都不推定原写失败/成功；当前CR只供核对，禁止自动重放写入/validation | 后端/前端/QA；响应丢失、原ID迟到、删除后查operation，核对写入/validation次数 |
| R02-5 引用与秘密 | 批准模板/精确修订由服务端核验；失效/撤销拒绝。返回摘要不含Secret、credential handle、完整目标URL或Pod模板 | 原后端/前端/QA；401/403/404、脱敏、无网络/生成副作用 |
| R03-1 一致读 | request、terminal及原slot日志来自同一主库一致读，或显式注明各checked_at的差异；只用原快照/原价格。未装配容量返回unknown | MAAS-3/6；读端SQL/权限和事务边界；迟到终态/并发slot释放下不自相矛盾 |
| R03-2 精确0/1 | request_id单独进入精确模式，不带普通列表默认参数；忽略隐式今日窗。recorded恰1行、lookup与行ID相同、next_cursor=null；unknown零行且data_complete=false | 后端/前端/QA；原ID跨UTC日、in_progress到终态、错ID、显式筛选冲突400、普通列表回归 |
| R03-3 证据型空态 | not_admitted只用原ID最终拒绝，expired只用保留期标记；没记录为unknown。互相矛盾或主库不可用503，不能200空页；不可见ID按原规则404 | 后端/QA；分别注入存在/不存在/不可用/矛盾证据及401/403/404，不以UUID日期猜过期 |
| R03-4 容量与账务 | 原slot_id/allocation_fence/request_id三元组；released只取原释放日志。slot复用读新allocation不能覆盖旧状态；released后原终态和财务held不变 | 后端/QA；旧证明迟到、slot复用、日志缺失/故障、未知held样例 |
| R03-5 停止与ID | 保留收到的可信原生成ID；后续GET的X-Request-ID不覆盖它。无原ID显示未知。停止/传输关闭、终态、引擎停止、容量、usage分开呈现，不重发生成 | 原前端/QA；浏览器abort在headers前/后、迟到终态、轮询503、无ID；纯writer夹具不算浏览器通过 |
| 兼容门槛 | 以固定草案生成/配置实际消费者，覆盖普通页、精确页、401/403/404/409/503；旧服务器普通页不能当精确命中；旧严格decoder不能因union变化崩溃 | 后端/前端/QA返回部署版本、SHA及解码回归；禁止靠探测性写入判断支持 |

## 实际新提交复验：6dc3914

远端PR #2实际新head已核对代码差异及两份controlled-api文档，作为依赖合入QA分支；本角色未修改产品实现。

| 分组 | 本轮结果 |
|---|---|
| 已有受控组 | 48/48通过，含原35（不累加）；临时MySQL/Redis、真实role/管理HTTP、Redis重启、Go owner子进程恢复 |
| QA独立12项 | 9通过、3失败；原8项现6通过/2失败，新增判因函数4项为3通过/1失败 |
| QA-001 | 两例仍失败：真实诊断与冻结摘要读入口未接合，旧before_usage分类仍在；实际null、Token held140、金额held520000 |
| QA-002原例 | 首片后原硬截止请求现为timed_out，通过；无正常DONE，保守held/slot保持 |
| QA-002补充顺序例 | 子context已DeadlineExceeded后再取消父context，子context保留最初截止原因，但relayFailure先检查父Canceled，返回cancelled，期望timed_out |
| v2静态 | 独立35项通过（含21个Schema样例），三份协议快照未变 |

新复验request ID：EOF=c09d5c85-d757-42e5-a3be-70115e48bf64；writer=7005ac7b-0e07-4f5c-8bc0-e4b9a8ce8d0f；首片后截止=0973bde8-26ac-4416-8e00-cd8f3c35d469。判因函数反例不生成请求，不伪造request ID。

QA-002补充定位为internal/kernel/relay.go的relayFailure：父context后到的取消覆盖原sendCtx先发生的截止。应保留原sendCtx的首个终止原因，再做事件映射。此为确定顺序的实际函数调用，未冒充浏览器/真实网关并发验证；修复仍由原后端负责。

本轮原始记录qa-v2-6dc3914.txt，默认Go原有子进程入口的一次skip不计通过场景；其子进程行为由恢复场景实际执行。48项是独立复跑已有场景，不能代替真实Higress/生产证明链，保留修订仍默认503。独立probe、浏览器、完整FE关项、19格全传输矩阵、真实模型/GPU/Helm及A01–A34完整验收未完成。QA-001/002保持开放。
