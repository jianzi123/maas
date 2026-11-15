本目录固定PR6 ac94a373ec0a61c5fd4dc5380a7985a4fb47840f，独立复验R1–R3，仅新增测试，不修改产品或开启真实Callable。

original-oracle.go.txt逐字节来自认证MAAS-17附件，SHA256为4dac0037a305c2ab8bdc14491962e9ae2ec1fb7bb56994f0276489023132b0cc，与产品内maas17_review_test.go相同。本轮直接运行该原文件5项，不对其gofmt或改断言。

boundary_test.go.in通过Go overlay独立覆盖7个Relay场景及2个完整写集rollback场景。终态/汇总唯一，金额和Token actual/null/原held/slot均检查；postcommit取消在writer中先读取实际已提交event，再触发cancel，事后逐字节核账务未变。deadline writer等到5秒原context真正到期，避免在准入前抢先触发。事务测试在sql.Tx内确认event和summary已写，再在commit guard返回取消/截止，证明全部回滚；随后用原event身份唯一异常结算。该guard故障注入与原ctx实际Relay测试分开，不冒充跨系统原子保证。

publisher_test.go.in复用作者真实模板和actual mysqlstore工厂流程，仅增加独立断言/日志；保留WithManagementOperations。角色/账号本次随机创建并配置default role。Activate→原Update完成、撤state权限关闭失败→无门禁/operation/command半提交、恢复列后真实COMMIT ACK丢失→同CommandID恢复且只一条记录、Paused cleanup→原Pause完成。拒绝action/spec_sha256/expected_rv与Key/预算/usage/DDL，不能以缺表假装拒绝。不继承整个operations/core角色、不关hook、不忽略权限错误。

前台复跑bash test/qa-r123/run.sh，显式提供已批准的Linux Go1.26、任务.cache下MySQL8.4.7及自有模块/构建缓存；可选Redis6.0.16。原清理守卫保留，测试结束清理临时服务/schema/账号/角色/socket。数据/HTTP/proof/profile为明确受控fixture，核心/账务/SQL事务真实。未调用供应商、访问真实Secret或部署集群。

只计原5项及本目录独立边界，重复的作者11/追加4项不累加；不重跑dbba820、94ef518、Usage20/Reader12或旧QA关闭项。完整A01–A34和生产adapter/身份/Higress/boot门槛保留。通过后由Mika协调运维刷新来源锁，本测试不修改Chart。