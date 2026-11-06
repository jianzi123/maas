固定后端 821269bd32164918443e63e66c6a7cbce45d440b、发布依赖 4d45c6f5a033783a8c1a8886f2b6e65eff7a3cf4、前端严格消费者 428d44e0b4f64ec628e6a945fd4b63a0e45c260b 完成本轮独立API复验。发布依赖祖先关系已用git merge-base核实。产品api/cmd/internal/scripts/config/go.mod/go.sum与指定SHA一致；只新增独立测试和报告，没有产品修复或新PR。

严格消费者仍固定428d44e；本轮期间新到达的实际页面aef53eeb7eac16bd7a956294fefab750a3de31f8另行完成独立浏览器复验，未混用旧夹具。

**结论与计数（各范围分开，不按轮次相加）。**

|范围|唯一用例/样本|本轮结果|证据|
|---|---:|---|---|
|原共享数据库/受控回归|72|72通过；包含此前58，不累加|qa-baseline-shared.txt、qa-results.json|
|同命令额外纯函数|7|7通过|同上，单列，不纳入72|
|辅助子进程入口|1|TestOwnerCrashChild默认skip；父进程恢复用例实际执行通过|同上|
|原真实管理场景|15|15通过|qa-baseline-management.txt|
|原实际HTTP响应严格Schema|37|37通过|qa-baseline-http.json、qa-baseline-http-schema.json|
|新增独立管理场景|6|5通过、1失败（QA-003）|qa-independent-management.txt|
|扩展管理装配中的原场景复跑|15|15通过；重复原15，不累计|同上|
|实际新页面浏览器|21|21通过，pageerror=0；原18＋独立新增3|qa-browser-go.txt、qa-browser-results.json及3张截图|
|原QA-001剩余EOF定向用例|1|通过；两次结果一致，不计为2项|qa-eof-first.txt、qa-eof.txt|
|扩展装配响应Schema|47|47通过；其中包含该装配重复的原响应，不与37相加|qa-independent-http.json、qa-independent-http-schema.json|

真实环境为本机WSL2 Linux amd64，Go1.26.0，MySQL8.4.7，Redis6.0.16，API-server1.36.0，etcd3.6.8。最终记录的WSL kernel为6.18.54.1-microsoft-standard-WSL2，见qa-environment.txt。独立测试使用真实临时API-server/etcd、数据库及loopback Go HTTP；registry和网关producer是明确测试适配，producer返回DependencyMissing。没有推理Pod、GPU或供应商调用；store/HTTP适配器重建不等同OS或DB崩溃/HA。

**QA-003/P2，开放：缺私有历史连接被误归类为请求参数错误。**

在存在同UID权威历史、有效target_revision、expected_cr_uid和If-Match的回滚请求中，仅令history.Reader.PayloadDB=nil（对应cmd/control-api/main.go:117允许缺省MAAS_HISTORY_PAYLOAD_DSN的受控配置），实际HTTP为400 invalid_request，预期为503 dependency_unavailable。文档docs/release-management-http.md要求缺历史载荷/依赖返回503。首次request_id为837d9197-4047-4617-af58-df5a33bac2ae；完整复验为0057485b-60f1-44cb-91e7-d2dbea962632，均复现。

定位internal/release/history/spec.go:13将PayloadDB缺失与非法UID/revision并入ErrInvalid；internal/controlapi/http.go:321映射为400。Kubernetes写计数未增加，最终generation_requests/usage_events/budget_windows均为0，故障关闭仍正确；问题是错误语义和恢复提示，不能据此宣称安全绕过。该错误体能通过Error Schema，进一步说明Schema通过不能顶替功能判断。原后端可沿现有PR拆分输入无效与依赖缺失分类；无需扩展共享字段或另造调用内核。复测应保持非法UID/revision的400、合法且缺连接的503、恢复连接后的原合法回滚202，以及写入前失败无副作用。本轮保留失败断言，没有代改产品。

首次新增用例调用继承测试helper时，helper对父测试FailNow，使后续用例中止。已保留qa-independent-first-failure.log；QA只改为在当前子用例记录实际响应及错误后继续执行，仍严格要求503。完整复验的21组管理用例为20通过/1失败（15组继承＋6组新增），所有补充场景均已执行，没有用skip隐藏QA-003。

**其余API证据。**

原15组覆盖目录、列表/详情/创建/更新/暂停/恢复/回滚/删除、真实CAS/UID-RV冲突、无重试、会话/CSRF/平台Key拒绝、写后ACK丢失、重建适配器后原ID查询、删除后查询、分页与DB窄权限、无生成/业务账务副作用。202/Running不能推定发布成功；目录缺真实证明始终callable=false。

新增通过的5组为：合法会话/CSRF配错误Origin仍403且无写；同namespace不同scope复用游标400、原operation.id查询404且无写；原Unknown查询遇503后恢复仍Unknown且不重发；删除后同名新UID不重绑旧Create/Delete/Unknown操作；Paused到Paused的JSON保存保持Update。原暂停/恢复分别为Pause/Resume，回滚/删除允许resource=null。

**QA-001与QA-002。**

沿原QA提交e6c7be21d40f6e1115b9830a46a0407bf825608c的TestQATerminationMatrix/before_headers/transport_eof，原断言全部保留，另加该EOF请求的原allocation释放/晚到释放断言。实际receipt=0、termination(eof)=1、result=interrupted；只读SELECT诊断连接读取真实DiagnosticReader。权威五项实际均null，合成Token held140、金额held520000不退款；原请求/终态/汇总唯一，无正常DONE、无重发。受控关闭证明仅释放原allocation，后继slot仍HELD，原终态字节归一后保持一致。请求ID分别为2b752a25-e33f-426c-97f6-71d02c2c2b22和d726f96b-7215-4cce-aeda-8d89793a9c42。QA-001原剩余EOF缺口在本次受控基线已通过，建议原清单按该范围关闭；不扩大到真实Higress/HA。QA-002沿2319eb6原受控通过范围保留，本轮未重跑整套19格矩阵。

**复现与原始证据。**

独立入口为test/independent/run.sh，需显式提供已批准的MAAS_TEST_GO_ROOT、MAAS_TEST_MYSQL_BASEDIR、MAAS_TEST_REDIS_BASEDIR和KUBEBUILDER_ASSETS。本轮先按原scripts/test-mysql.sh（启用envtest）执行72及15，再用Go overlay执行原EOF及新增管理断言。Schema入口为python test/independent/schema.py，使用固定前端Git对象的原始稳定/草案文件和Python Draft202012Validator＋FormatChecker，没有放宽Schema。

首次工具装配误用了尚未完整复制的Go目录，发生标准库缺失；日志保留qa-toolchain-setup-failure.log，属于环境装配失败，不计为业务用例失败/通过。之后使用完整的已批准Go1.26工具链，在自有WSL临时缓存重新执行。没有把本轮普通Go全仓58事件/vet/build报告成复跑结果；本轮仅执行上述有证据的范围。

qa-cleanup.json确认5个记录的自有MySQL临时数据目录全部消失，未见本次测试的MySQL/Redis/API-server/etcd/Go测试进程；原编排已清理DB/账号/socket，专属临时工具缓存也随前台进程退出清理。依赖二进制缓存保留，未留下长期服务。

**剩余范围。**

A01–A34完整34行矩阵在matrix.json/matrix.md，全部维持NOT_ACCEPTED；历史用例映射与本轮current_run证据分开。实际页面aef53ee的本地受控管理生命周期、桌面1440px及移动390px已独立通过；不扩展为真实模型或完整平台验收。真实Higress/H1–H4、Secret/validation、可信旧行导入、模型/GPU/目标部署、Helm安装升级回滚及性能整体验收未执行，生产继续不可调用。MAAS-3/7保持in_progress。

**实际新页面独立浏览器接续。**

在API结果已完成后，读到前端新交付aef53eeb7eac16bd7a956294fefab750a3de31f8，随后接续实测。54个前端产品文件与该SHA逐字一致；console/contracts与原严格消费者428d44e没有差异。Windows Node22.23.4、Edge156.0.4314.58，真实临时API-server/etcd/MySQL/Go HTTP，运行原18项页面检查并补3项独立边界，共21/21、pageerror=0。

原18覆盖真实空目录/列表，创建及原operation.id、同UID历史，暂停/恢复、JSON保存动作分类、回滚/删除resource=null及原ID查询、确认配置后编辑，API-server CAS409和实际写后ACK丢失、390px、HttpOnly/零存储及退出。另加：Unknown时重读当前CR仍锁定编辑；关闭操作DB连接所得真实503、换scope所得真实404，均保留原ID和Unknown，恢复后仍只查原ID且PUT计数不增加。故障只在隔离测试wrapper中注入；没有拦截/伪造页面HTTP成功体。父harness在结束前断言generation_requests、usage_events、budget_windows均为0。

原浏览器脚本与Go harness来自该前端SHA，独立扩展保存在frontend_browser_test.go.in与release-browser.mjs；复现入口browser.sh，需显式双路径视图及便携测试依赖。页面源码未修改。普通前端100项/11门控skip和原14项Key/预算浏览器不是本轮重跑结果，本轮不引用为独立通过。

release-created.png、ack-unknown.png、release-mobile.png均已独立查看：桌面与移动界面明确不可调用；Unknown操作保留原ID，依赖错误不会变成发布成功。浏览器/Vite在finally中关闭，Go/临时API-server/etcd及schema随前台harness退出清理。模型/GPU/目标部署等仍未执行，QA-003不因页面通过而关闭。
