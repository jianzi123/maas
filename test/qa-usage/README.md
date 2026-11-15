本目录为MAAS-7针对PR6 d2d7869fe16b8968d6ca5b00a63560c322b84dc1的独立受控复验。基线为整合默认分支925d8c55be9ce823d100bf90a5c78cf19ea66d58，其祖先关系已核实。只新增测试、结果和报告，不接管产品实现，不重新打开QA-003。

kernel_test.go.in通过Go overlay进入internal/kernel，复用原数据库fixture（真实核心/账务/发布库，Redis和H1-H4批准为替身），19个调用场景＋1个冻结profile检查。断言最终19不能求和为36、最终重复只结算一次、冲突父/缓存/推理/缺失状态先保存完整原receipt再失败、合法finish边界、缺策略/非法策略、EOF/取消、非流式批准及缺策略。缺策略/冲突/EOF取消时权威量全null；批准但不完整最终快照仅保留已知字段，token_actual/cost_actual仍null，禁止从旧进度补齐、Token held140/金额held520000、唯一终态与汇总、无DONE和重发、原slot释放不退款；诊断用新SELECT-only账户和真实DiagnosticReader读取。测试数据不代表真实provider批准。

reader_test.go.in通过overlay进入cmd/control-api，调用实际openProjectionDB工厂。由原样角色模板替换为本次专有角色名，显式default role；实际非空历史来自publisher.Observe的完整HistoryCapture，非手工伪造公开成功响应。验证能读脱敏历史、不能读原spec/Key/账本或写发布/operation/DDL，负例必须为MySQL1142/1143/1227授权错误。缺Reader连接HTTP503使用真实Core和有效cookie会话；缺operations DSN调用实际run函数验证启动失败；不通连接错误脱敏。该装配使用httptest与内部真实Reader，不冒充浏览器、生产账户或完整生产server启动。

显式提供MAAS_TEST_GO_ROOT（批准Linux Go1.26）、MAAS_TEST_MYSQL_BASEDIR（任务.cache下批准MySQL8.4.7）、可选MAAS_TEST_REDIS_BASEDIR和自有MAAS_TEST_GOMODCACHE/MAAS_TEST_GOCACHE后，前台运行bash test/qa-usage/run.sh。脚本复用原清理守卫，只创建/清理自己的临时MySQL/Redis、schema、账号与socket。不会创建集群、访问真实Secret、下载模型或调用供应商。

原作者新增Usage7、Reader身份1，以及6个策略纯函数和1个缺连接函数，按受影响范围复跑，分别列结果。不是重新跑全80，也不把80与原72/前轮相加。QA-001/002/003已过范围保留，30cfce9前端消费者另由原MAAS-7工作流处理；本次不复制其评审。公开3.0/Observation1.0冻结，未启用D1，生产仍不可调用。
首轮partial样本的input=12被QA错误要求为null；依据MAAS-2最小补充§5的缺字段对应null、缺父量不推导规则纠正。保留qa-targeted.txt及原evidence中的失败记录，只定向重跑该leaf；最终计数合并同名用例，不增加样本量。