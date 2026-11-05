独立复测固定后端 2319eb62d84f278d1dd6d444ce52e532e202766e。QA-002 在本次受控修复范围复测通过，建议原清单登记关闭；QA-001 原 receipt 丢失用例已修复，但扩展 EOF 终止记录仍有缺口，保持开放。MAAS-7 继续 in_progress，A01–A34 未获完整验收。

## 环境与结果

环境为 WSL Ubuntu-22.04/linux-amd64、Go1.26.0、MySQL8.4.7、Redis6.0.16。MySQL无TCP、Redis port=0，使用本任务私有socket和随机schema；未调用真实模型/供应商、使用GPU或写目标集群。

| 分组 | 实际结果与计数口径 |
|---|---|
| 已有实现回归 | 58/58通过，含此前48，不累加；为独立重新执行已有用例 |
| QA独立用例 | 42个唯一用例，41通过/1失败：先执行40项，再执行受影响故障小组8项，其中6项为重跑、2项为新增，不计作48项 |
| 19格终止矩阵 | 18通过/1失败；3格发送前已终止时没有分发/建档/扣量；其余16格有实际准入 |
| 四个原判因函数例 | 全通过，含先子context截止、后父context取消的确定顺序反例 |
| 新故障小组8项 | 全通过：receipt/termination写失败、记录数上限、字节上限、无保留策略、非法usage、冲突快照、部分usage |
| Go全仓默认回归 | 54个pass事件、47个skip、0fail，含父子事件；无socket的数据库skip不能作为数据库通过 |
| vet / build | 均通过；未启动长期服务 |
| v2静态 | 独立35项通过（含21个Schema正反样例）；不是架构53项或历史80项重跑 |
| 字节边界 | 旧0001/0002迁移、终态3.0/票据v3/Observation1.0快照未改；新增诊断Schema与v2原件逐字节相同 |
| 清理 | 本轮5个runner数据目录均消失，本任务MySQL/Redis可执行路径下无存活进程 |

Go默认回归不包括需要overlay/数据库的QA验收，故默认退出0不能覆盖本次QA剩余失败。没有使用CI或作者测试报告替代本次运行；用例耗时不是模型SLO、吞吐或性能收益。

## 实际读取与已通过边界

原两个用例直接调用生产 NewDiagnosticReader(readonlyDB).Read，使用新连接和仅授予 request_usage_diagnostics SELECT 的临时身份。在客户端首次Write之前即重读receipt，并独立核对五项12/7/19/4/3、request、owner/fence、原冻结摘要和完整调用绑定。摘要从实际准入摘要表读取，并另以准入返回的原快照字节计算SHA256作对照，不对当前profile/恢复后的对象重算冒充。

EOF/写失败后的terminal五项及权威token/cost actual仍为null，Token held140、金额held520000（合成TST预留），原请求/终态/汇总各一次，无正常DONE、无生成重发。受控H2证明只释放原allocation，不改财务held/终态；新请求复用slot后，旧证明不释放新占位。

receipt提交后Store重建/新连接读取通过；已有回归的Go owner真实子进程退出恢复也通过。重复规范内容幂等，异内容/错摘要/错binding/旧fence拒绝；receipt及终态真实COMMIT后driver注入ACK未知按原身份恢复，迟到诊断不重结算。独立实际Recover后旧owner迟到追加拒绝，原receipt仍可读。上述不是MySQL断电/HA或真实网络丢包证明。

只读身份能读生产reader，但不能读Key/冻结摘要表、不能INSERT/UPDATE/DELETE诊断或执行DDL；临时账号均清理。SQL权限仅变更本次短寿命测试实例，未改目标环境账户权限。

记录数上限为夹具2条；另用16384字节限额验证预留termination空间，实际保存8条/8658字节后停止正常转发并保守结算。64条/262144字节及保留引用均为合成安装输入；未验证生产保留策略批准。日志写失败或策略缺失的测试通过只证明故障关闭，不表示失败请求观测保存完整。

## 剩余P2：已准入、headers前EOF没有termination

步骤：受控网关完整读入请求并调用真实Admit提交，然后在发送任何响应headers前关闭连接。无用户取消/截止，Go按interrupted唯一结算；实际值null，Token/金额held及QUARANTINED均正确，只有一次分发。独立生产reader返回0条诊断，缺少应追加的eof termination。

完整矩阵复现request_id=13518df6-6820-47cb-9204-6f80ff683678；定向复测request_id=11e9588b-46fb-4c22-81fd-f1794d1413c5，相同失败。该场景没有usage，预期receipt=0，但termination应为1；未声称五项计数在此场景丢失，也未发现不安全退款。
定位：`internal/kernel/relay_forward.go:127` 的 sendErr 非截止/非取消分支只调用 finish，未走独立 termination 的 end。

最小后续动作：由原后端沿MAAS-3/PR #2处理；原request确已准入且可核验时，为该EOF追加原绑定的termination，保持原唯一结算/held，不为未准入请求造记录或重新发送。不得通过删除该格/放宽为0条诊断来关闭v2生命周期要求。修订SHA交回后可仅先复验此格，再运行受影响分组。

该缺口属于QA-001的usage前EOF/终止诊断覆盖，按P2保留开放；如原架构认为该边界需另编号，交Mika在原清单归并。本角色没有修改产品实现。

## 请求ID与可复现入口

| 证据 | request_id |
|---|---|
| 原EOF after usage通过 | b6baeee8-7056-404d-ac5f-afad67785e40 |
| 原writer失败通过 | 40317071-cf3e-42e4-abdd-0544426ae83a |
| 原首片后截止通过 | 32ae6d25-9aa0-4fdf-b9b5-e9f4e5c4f908 |
| receipt/终态ACK与迟到诊断 | 7d16fbc0-75c4-4aaa-89d8-14d76d4b63b6 |
| Store实际Recover/旧fence拒绝 | 3664c41d-a738-4f8e-856d-850b3881b43f |
| 字节上限故障关闭 | 0ddc0d73-48d2-43d3-99ca-91ffc7da2365 |

函数级判因例和发送前已终止的3格没有生成请求，不伪造request ID。部分通过夹具仅输出测试名；关键缺陷和核心复测ID在上表/原始日志中。

```sh
MAAS_TEST_PATTERN='^TestQA' bash test/acceptance/run.sh
MAAS_TEST_PATTERN='^TestMySQL' bash test/acceptance/run.sh
MAAS_TEST_PATTERN='^TestQATerminationMatrix$/^before_headers$/^transport_eof$' bash test/acceptance/run.sh
bash test/acceptance/regression.sh
```

现有独立集预期保留上述一格失败；无需MAAS_QA_DIAGNOSTIC_READ_SQL等旧接合变量，当前已调用实际reader和冻结摘要表。

历史v1/v2失败记录均保留，最新结果为results-2319.json和本报告；旧report.md/results.json/results-v2.json仅是各自SHA的历史事实，不覆盖为假通过。

FE-R02/03：已有受控管理HTTP子集随58项复跑通过，保留修订reader仍因缺权威历史返回503。独立probe、原CR UID/分页回滚竞争/ACK未知/跨日/权限503/浏览器/严格消费者的11项完整关项仍未完成；本次不扩展公开诊断/RequestLookupPage字段。

Higress/H1–H4和H2生产者仍有替身；真实模型、GPU/LWS/SGLang、目标Helm/K8s、浏览器、DB崩溃/HA和生产身份/保留策略批准均未验收。安全隔离、unknown held和slot释放不证明实际生成停止或容量已恢复。生产及A01–A34不因QA-002的受控关闭建议而放行。
