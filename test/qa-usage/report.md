固定PR #6提交d2d7869fe16b8968d6ca5b00a63560c322b84dc1完成本轮定向独立复验。该提交包含整合默认基线925d8c55be9ce823d100bf90a5c78cf19ea66d58，祖先关系已核实。只新增test/qa-usage下的测试/报告/矩阵，产品api/cmd/internal/scripts/config/go.mod/go.sum与指定SHA一致。本轮未发现新的产品失败；两种策略仅在明确合成批准profile内验证，不代表真实provider已获批准。MAAS-3/7仍in_progress。

**唯一计数与证据。**

|范围|本轮结果|原始文件|
|---|---|---|
|独立Usage|20个唯一leaf最终通过：19个调用场景＋1个不可变profile检查|qa-targeted.txt、qa-partial-retest.txt、qa-results.json|
|独立Reader|12/12通过|qa-targeted.txt、qa-reader-evidence.json|
|受影响作者数据库场景|8/8通过：Usage7＋Reader身份1|qa-targeted.txt|
|受影响作者纯函数|7/7通过：策略6＋缺连接1|qa-targeted.txt|

上述不是全80重跑，80包含原72，均不与本轮或前次相加。首轮独立Usage为19过/1失，失败来自QA的partial oracle错误；按既有字段独立规则修正后，只复跑该1项通过。原日志和原evidence的passed=false保留，最终同名用例覆盖计数，不伪装成一次全套零失败。Reader12及作者8/7没有无理由重跑；无匹配包的no tests to run不计通过用例。

真实运行环境：WSL2 Ubuntu-22.04，Linux6.18.58.1-microsoft-standard-WSL2 amd64，Go1.26.0，MySQL8.4.7；原编排还启动了Redis6.0.16，但本次fixture使用受控rate adapter，没有重新验证真实Redis故障/重建。调用使用loopback受控HTTP上游＋实际Go Relay/耐久账本/终态和汇总。H1–H4见证/metadata/批准profile是测试替身。Reader使用真实SQL账户、角色和实际openProjectionDB连接工厂；缺连接HTTP使用真实Handler的httptest recorder，启动失败调用实际run函数，没有声称浏览器或正式server已完成生产装配。

**Usage独立结论。**

final_only下相同最终快照重复可接受并只结算一次；父量12/7/19→12/8/20、缓存4→5、推理3→4、最终字段由已知变缺失均冲突。冲突receipt的父量/缓存/推理子集按原JSON逐字段比对，原值保留，诊断sequence/owner/fence/request绑定正确，末条termination为usage_conflict；从新的仅获诊断表SELECT连接经真实DiagnosticReader读取。源码顺序为AppendDiagnostic事务返回后再observe冲突并结算；本轮未注入诊断COMMIT ACK故障，不外推为崩溃/HA证明。

cumulative_until_finish下17→19只结算最新19，不能求和36；finish前无usage时，finish后的首份19为最终，相同重复仍幂等。同事件finish封闭后增长、finish后的增长均拒绝；中间缺字段不能清空高水位来掩盖后续回退。不可变profile的AdapterRevision/Mode改写被拒绝，原注册profile仍为原策略。

缺策略时receipt仅作diagnostic_only；缺adapter修订和未知mode均故障关闭。进度后EOF、final+finish但未DONE的EOF、最终receipt后显式取消均没有正常DONE/重发。实际终态/请求/汇总各一次，异常token_actual/cost_actual_atomic为null，合成Token held140、金额held520000保留，原allocation释放不退款也不改写终态。成功场景Token已知19、TST金额已知72800且与终态cost_actual_atomic一致，保留金额/Token均归零；金额由本fixture冻结价表核算，不是成员运行预算默认值。

非流式有批准策略的完整响应成功，缺策略即失败并保留未知held。所有19个调用均仅一次上游尝试。中间receipt与公开正常最终结果不混同，本轮不切D1，终态保持3.0。

关键请求ID（均本轮独立生成）：
- 相同final重复成功：c7936acf-b281-4510-9efc-d13e1e920b7b。
- 父量final冲突：e0edb74b-1ef7-4724-bad7-274c347e92cb；缓存冲突：a2e4af7d-17bb-42a8-a26d-3ff2c629a2ea。
- 合法累计进度17→19：f9b131d7-970a-45d3-b8b1-31fcf5210975。
- 缺策略：877ffd8e-8568-4448-b82d-71ae63bf4cea；EOF：9498ed68-1e94-4fd7-bd8b-34308322cf67；取消：a7667fd6-d281-4d75-9cf0-568ed6ab0cc3。
- 最终partial定向复跑：5de8d8bf-1173-4556-ae2c-f99f4f08d9d3。

**partial oracle纠正。**

最后一个批准final只有input=12，旧进度为12/7/19。首轮QA错误要求这个已知input也为null；产品实际保留input12，而output/total/cache/reasoning均null，result=failed，计费实际null且held不变，无正常DONE。依据原MAAS-2最小补充2319eb6 §5的缺字段对应null、缺父量不推导规则，以及本次不从旧快照补最终缺字段的边界，修正oracle为保留明确已知input12且严格禁止补齐其他字段。这个修正没有改产品、没有把不完整成功当通过；只定向重跑该leaf。所有失败场景的token/cost actual=null另经原始终态JSON逐例离线核对，不新增用例计数。

**Reader独立结论。**

测试从原release-permissions.sql的maas_release_history_reader模板截取实际授权语句，仅替换为本次专属role/schema；创建临时账户并显式default role。SELECT CURRENT_USER()/CURRENT_ROLE()确认实际连接与角色，实际openProjectionDB连接未继承核心身份。

publisher.Observe写入含原spec/Resolution的完整HistoryCapture后，该身份成功读出同UID的1条脱敏历史，revision正确，不含私有credential handle/endpoint/spec_bytes。未装配真实live/evaluator时没有宣称rollback eligible。

6项负例实际返回MySQL1142，而非缺表：原spec、platform_keys、usage_events读拒绝；release_links写、release_management_operations写、DDL拒绝。核心迁移和operation表均真实存在。历史身份也不能作为Operations读连接使用。缺history连接不fallback核心，真实Core＋有效管理cookie下GET历史503；缺MAAS_OPERATIONS_DSN时实际run()在启动监听前返回explicit management operation connection required；不可达连接错误不回显DSN/私有标记。

这证明当前受控工厂/Reader/启动防护与SELECT-only身份相接；没有验证真实安装方生产账户、实际operations写角色和独立payload账户的完整部署。config/mysql/controlapi-projections.sql仍是安装模板，不能把显式DSN或局部身份测试当作生产最小权限已落地。

**运行与清理。**

bash test/qa-usage/run.sh需要显式批准的Linux Go/MySQL及自有缓存，可选Redis；Go overlay只编译独立测试。原scripts/test-mysql.sh前台持有临时服务并清理。本次实际先执行20/12/8/7定向范围；partial oracle修正后仅按^TestQAUsageAuthority$/^final_partial_not_backfilled$补跑。首次WSL查询发生Wsl/Service/WSAETIMEDOUT，未重启发行版或误停其他进程；通道随后自行恢复，编译/测试完成。补跑将编译并发限制为4，未更改产品行为。

qa-cleanup.json核对2个MySQL临时数据目录和2个专属Go工具缓存均已删除，没有本次MySQL/Redis/Go测试进程；临时schema/账户/角色/socket随数据库和前台生命周期清理。保留依赖二进制缓存，无长期服务。测试结果、逐请求终态/诊断、权限错误码和失败历史均随证据包交付。

**剩余范围。**

原QA-001/002/003受控通过范围保留；不重跑QA-003或重复实现内核。30cfce9前端消费者复验沿MAAS-7原工作流，此处未替代其独立结论。全80数据库、全仓Go/vet/build、浏览器、首非空内容时间测点、非retained历史409分类均非本轮新验证项。完整A01–A34矩阵保留34行，所有整项状态NOT_ACCEPTED，当前Usage/Reader局部证据与历史记录分开。

真实adapter修订/最终性保证仍待架构与算法核定；两种受控语义的行为通过不表示真实Higress/provider具有这些保证。Chart源码快照未锁定本增量；真实Higress/Secret/validation、接流实例/boot覆盖、模型/GPU、目标部署、Helm/HA与整体验收仍未闭合。生产继续不可调用。