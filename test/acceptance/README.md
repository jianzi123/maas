当前固定后端2319eb62d84f278d1dd6d444ce52e532e202766e。先读retest-2319.md/results-2319.json：已有58项通过；独立42项41通过/1失败，剩余为已准入headers前EOF缺termination。QA-002建议在受控修复范围关闭，QA-001保持开放。

本目录为独立QA资产，通过Go overlay把kernel_cases_test.go.in编译进internal/kernel；不改产品实现。原report.md/results.json/oracle-v2.md/results-v2.json为历史记录，旧SQL环境变量接合方式已由实际NewDiagnosticReader替代。history保留原失败字节，shared协议保持终态3.0/Observation1.0，D1 3.1未切换。

```sh
MAAS_TEST_PATTERN='^TestQA' bash test/acceptance/run.sh
MAAS_TEST_PATTERN='^TestMySQL' bash test/acceptance/run.sh
bash test/acceptance/regression.sh
python test/acceptance/review_diagnostics.py --closure-dir ../inputs/closure-v2/unpacked --output artifacts/qa-2319-static.json
```

run.sh沿既有短寿命MySQL/Redis编排使用本任务.cache：Go1.26.0、MySQL8.4.7、Redis6.0.16。全独立集保留一格失败；只测单格见报告。regression.sh执行全仓默认Go测试/vet/build；数据库skip不算通过，42项QA由overlay单独运行。readonly账户只授诊断SELECT，读取原生产reader；账号仅存在于本次隔离测试实例并自动清理。

diag迁移/读取实际入口为docs/usage-diagnostics-v2.md。retest-v2.json继续维护12项诊断、19格终止与11项FE关项的最新状态；静态样例不是运行证明。probe_admin.py仍仅是只读HTTP子集入口，要求已授权loopback、可信原request_id/原CR UID，以及由安全渠道注入MAAS_QA_ADMIN_COOKIE；不得把部分probe通过当完整FE或浏览器验收。

所有模型/币种TST/价格/保留引用/限额均是合成夹具。ACK为真实COMMIT后driver注入；Higress/H2仍有受控替身，Store重建/Go进程退出不代表DB崩溃/HA；slot释放不释放未知财务held。没有供应商调用、GPU/权重或目标集群写入授权外的运行。
