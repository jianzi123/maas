固定PR #6 ac94a373ec0a61c5fd4dc5380a7985a4fb47840f完成R1–R3定向独立复验，三项在本次受控范围通过，可交Mika协调MAAS-8刷新最终来源/角色锁。未改产品或Chart，未合并PR；默认925d8c5与候选ac94分开。MAAS-3/7仍in_progress，真实Callable与A01–A34整体验收未完成。

|范围|实际结果|原始证据|
|---|---|---|
|原TestMAAS17 oracle|5/5通过，原文件字节未变|qa-targeted.txt、original-oracle.go.txt|
|独立Relay边界|7/7通过|qa-relay-evidence.json、qa-targeted.txt|
|独立完整写集提交前回滚|2/2通过|qa-targeted.txt|
|真实publisher角色/hook增强流程|1/1通过；含多步允许/拒绝、故障回滚及ACK恢复|qa-targeted.txt|

原5项与独立10项分别记录；重复原反例和作者11/追加4项不相加为新的验收总数。首次运行全部通过，0失败、0跳过；无匹配包/编译no tests to run不计通过。原oracle来自认证MAAS-17附件，SHA256为4dac0037a305c2ab8bdc14491962e9ae2ec1fb7bb56994f0276489023132b0cc，与候选仓库文件及保留副本逐字节一致；未gofmt或改其断言。旧c7失败记录不覆盖、不重复跑旧失败。

实际环境为Ubuntu-22.04 WSL2 Linux6.18.58.1-microsoft-standard-WSL2 amd64、Go1.26.0、MySQL8.4.7。原编排启动Redis6.0.16，但本轮rate/H1-H4/profile是受控fixture；实际Go Relay、loopback HTTP、核心账务、发布库和SQL事务参与。不宣称真实Higress、生产权限或模型验收。

R1：finish写回后取消与原5秒context截止均返回异常，无正常DONE，分别cancelled/timed_out。五项未知usage及token/cost actual均null，Token held140/金额held520000，原slot隔离。正常控制与确认提交后取消分开：后者在最终usage写入回调中先从新SQL查询读到真实已提交event，再cancel；事后event字节不变、result=succeeded、known19/金额known72800、held0，停止正常DONE，不反向重开账务。所有7个Relay场景只发一次上游，终态/汇总各1。

两项提交前guard注入分别返回context.Canceled/DeadlineExceeded。在同一真实sql.Tx内确认usage_events和usage_daily完整写集已经建立后再拒绝COMMIT；返回后event和summary均0，request仍in_progress，Token reserved140/金额reserved520000、known/held为0。随后复用原EventID唯一结算cancelled或timed_out，actual=null、held保留；受控证明释放原allocation不退款、不改终态。guard错误注入证明真实写集整体回滚，与Relay原context实际终止测试分开；不外推最后检查到跨系统COMMIT之间绝对原子，也不把提交ACK未知猜成退款依据。

R2：finish后的content及矛盾finish均在展示前拒绝，无AFTER_FINISH、无正常DONE，result=failed、未知实际与原held保留。批准final_only fixture的finish后独立最终usage正例成功且只结算19；没有用last/max或粗暴拒绝全部后续usage。原顶层error控制也在原oracle中通过。独立检查终态3.0 Schema、请求与唯一汇总/slot边界。

R3：由仓库release-permissions.sql及kernel-permissions.sql原模板安装随机publisher role和用户，设置并查询真实default role，使用实际mysqlstore.New(...).WithManagementOperations。未继承整个core/operations角色，未关闭hook或忽略SQL错误。

Activate真实完成原Update operation。撤销UPDATE(state)后CloseAdmission失败，admission_closed仍false、原operation仍Succeeded，release_operations里该CommandID仍0条，证明没有半提交。恢复该窄列后通过真实driver.Tx.Commit执行后丢ACK得到ErrCommitUnknown；用同一CommandID恢复，门禁实际closed且该命令记录仅1条。随后Paused Observe/RecordCleanup完成原Pause operation。

实际拒绝SQL：action、spec_sha256、expected_rv三项UPDATE返回1143；Key写、budget held写、usage删除、DDL四项返回1142。相关表真实存在，不用缺表假装权限拒绝。R3沿作者真实模板流程派生，仅增强operation状态/命令唯一性断言和可审日志；并非独立重新实现发布库。

关键独立关联：finish取消89546d44-f963-4824-8f22-53b3d69e0dc3；finish截止44250479-3a8f-44a5-a86d-4b3ad8aa832c；提交后取消c4f7f970-eb91-4962-ad62-6887a9a97e09；非法finish后content ee9e3de8-ff3d-40f7-b2cb-f827f1046cc6；合法独立final 4854a9c5-ecd1-493f-881d-13d0594d33fd。事务回滚请求a1fd8138-970d-4365-9244-7441283f3c89与aaa41e1f-b2fb-4858-9607-0ce58d1de0cd。R3原Update operation=69012c4e-608f-4a89-be5b-4fa8a71cef43，Pause operation=bfcfe751-a672-41c4-8fa1-55a78761732e；ACK未知恢复command=cf2e9700-f57e-4a68-b665-ef60439ea120。

复跑bash test/qa-r123/run.sh，显式提供批准Linux Go/MySQL及任务自有缓存；Go overlay只增加两份独立测试，原oracle直接执行。summarize.py按leaf去重，确认原hash与实际权限错误码，原始终态/诊断另附。SQL/HTTP与受控proof分开，不把测试fixture当provider批准。

qa-cleanup.json确认本轮MySQL临时数据目录和专属工具缓存消失，无本次MySQL/Redis/Go测试进程；schema/角色/账号/socket随自有生命周期清理，未留长期服务。产品api/cmd/internal/scripts/config/go.mod/go.sum与固定SHA一致，只有test/qa-r123新增内容。

原dbba820源端19/9、94ef518消费46/42、d2 Usage20/Reader12及QA-001/002/003保留原SHA/范围，不批量重跑、不外推PR整体。没有重跑全仓/vet/build、80/72或浏览器。完整34项矩阵均NOT_ACCEPTED；生产身份/真实adapter/Higress/Secret/validation/实例boot和Callable门槛保留。本结论仅允许Mika按既有分工接续MAAS-8来源/角色锁复核，不代表旧d2/35/36或目标部署已闭合。