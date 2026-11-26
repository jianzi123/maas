MAAS-20 FC-1 与受保护 tools-v1 作者验证（2026-11-26 UTC）
====================================================

从统一远端4402c456续接，确认原228bbe4祖先保留、PR18已合并关闭；新增工作沿同一实现流/PR24。迁移代码edece873→标准四锁0b331584；持锁连接取消隔离代码dd1018e5→标准四锁e9f58b74。最终工具代码提交由本报告所在提交及其后独立四锁引用，精确最终head回任务评论，不把旧切片head当完整工具交付。

| 实际范围 | 结果与边界 |
| --- | --- |
| 原生工具/AR/有符号JSON回归 | 30个顶层、含子测试124项，0失败/0跳过，整体exit0；包括45原始MAAS-9 capture的真实loopback HTTP线路重放、原Step来源映射/旧消息恢复、整批/ARReview及工具Schema可签名。45个线路断言不冒充45个完整业务用例。 |
| 完整protocol包 | 3个顶层/3项，exit0；包含原票据验证与新增工具JSON安全整数域。与上行有重叠，不相加。 |
| 最终正常产品/真实MySQL批次 | **18个顶层、含子测试57项，0失败/0跳过，整体exit0。** 包含全部Product、原ARReview、MySQLToolsRelay；详见原始JSONL，不累加旧879或其他角色成绩。 |
| 正式程序构建/定向vet | GOMAXPROCS=1、-p=1、GOMEMLIMIT=256MiB，go build及变更相关go vet均exit0。两个纯迁移隔离快照也分别构建成功。 |
| 实际HTTP/持久事件样本 | 仅补充可选测试制品导出，产品逻辑与b2a79c7相同。定向闭环1顶层/含子测3项exit0；成功案例23 HTTP样本/33持久事件/2原child，非法后项11 HTTP样本/9事件/1原child。独立Python jsonschema用官方OpenAPI及事件Schema逐份通过；未捕获登录、Cookie、CSRF或原始Key。 |
| 清理 | 专属skip-networking MySQL8.4.7，/tmp/maas11-mysql.*私有socket/数据；日志确认正常shutdown。HTTP/TLS服务器、Host与自有连接均在测试中关闭/join，无自有常驻服务。未停止其他项目。 |

最终SQL的具体断言
-----------------

- kernel/release1–3、product1–2固定摘要/Applied；002 marker-only Applying/Failed/未知、缺行/hash错、物理缺表/列、Agent缺索引、其他必需域Applying、新高版本均拒绝。原文档版本/索引直接检查，不造Agent journal。运行失效ready503且重授权拒新dispatch；调用方预先取消不退役服务。
- 实际`ReconcileProduct002`：活跃scheduler时拒绝，维护下核摘要/完整布局/原seed后幂等Applied，不重放DDL；原Unicode历史字节与unknown-held投影保留，重开仍1request/1usage，无模型/结算重放。原普通共享登录、离线两工具/批准/停止/重启回放也通过。
- 正常HTTP登录Cookie/CSRF→AR-1创建/Run→ModelClient→签名Body/Plan→受控mTLS网关→原Admit/Finalize→真实Calculator/目录→原供应商ID反馈→第二child最终回答。正常分支2工具/2request/2usage，父known_tokens=38；第二工具参数带非法scope时0工具、1request/1usage、原known_tokens=19保留。事件/成功DTO沿原官方AR Schema验证。
- Relay同原MySQL账本覆盖成功、非法arguments、missing usage、部分cache分类、EOF、顶层error、实际取消。缺usage继续held；分类不足保留Token已知19、金额held520000，既不填0也不丢已知维度；每场景1request/1usage，错误没有成功DONE或原始供应商错误文本泄露。
- 显式诊断策略：Migrate经原ConfigureDiagnostics只初始化缺行；重复迁移不重置，运行Open/prepare对缺行/不匹配拒绝且不修复，不产生模型行；原数据存在不同策略时迁移准确冲突，不覆盖。配置缺失也明确拒绝。

真实与替身
----------

正常Go HTTP/AR-1、MySQLSessionStore、原准入/预算/唯一计量、事件/checkpoint、Schema、两个工具、Cookie/CSRF和实际TLS交换是真实现。测试中的**模型、Higress传输/H4、rate、publication/closure生产者是明确受限替身**，只在专属临时DB及测试注入使用；正常配置不能选择这些注入。没有供应商凭据或付费调用，真实供应商调用0。不能把上述结果称为真实Higress、完整mTLS身份注册、供应商tools并行保证或生产验收。SQL连接为专属临时数据库测试身份，不称正式最窄角色已验。

原始失败也保留
--------------

1. 首次长编译期间继续修改依赖，出现混合快照undefined NormalizeUsage；未计通过，后续固定源码重跑。
2. 新测试把missing usage误期望成功；原内核正确失败/held，修正测试，没有放宽实现。部分cache价格分类不足则沿原逐维语义保留已知Token/未知金额，按实际终态核验。
3. 最小签票夹具缺Catalog元数据，正常创建先被目录门禁503拒绝；补受控安装元数据，未删目录门禁。
4. 真实Calculator Schema含负数minimum，被原非负财务canonical误拒而无法prepare；新增独立CanonicalToolJSON并保留原票据/计划/计量规则，修正真实Schema hash，未删负数限制或放宽财务域。
5. 原正常Migrate未初始化Relay依赖的diagnostic_policy行，真实发送后receipt故障/held。补显式原策略配置及迁移消费/运行只读校验后整桥通过。未以零用量或跳过receipt掩盖。
6. 集成静态审查发现请求ctx可能关闭持锁连接。dd1018e改为保存CONNECTION_ID、普通池查询IS_USED_LOCK，服务monitor独立。作者不把“进入函数前取消”当“查询中取消”证据；后者由集成/原QA在最终组合复验。

复现
----

```powershell
$env:GOMAXPROCS='1'
$env:GOFLAGS='-p=1 -buildvcs=false'
$env:GOMEMLIMIT='256MiB'
go test ./internal/protocol ./internal/agentruntime/kernelmodel ./internal/agentruntime ./internal/toolwire -run 'TestTool|TestMAAS9|TestDeepSeek|TestCanonical|TestRemaining|TestUnavailable|TestAR1|TestARReview' -count=1 -json
go test ./internal/protocol -count=1 -json
go build ./cmd/maas-service
go vet ./internal/app ./internal/agentruntime/... ./internal/kernel ./internal/toolwire ./internal/protocol ./internal/release/mysqlstore ./internal/release/management ./cmd/maas-service
```

Linux/WSL使用本任务已核准portable MySQL/Go缓存，原runner建立并清理自己的socket，不连接已有MySQL：

```sh
export GOMAXPROCS=1 GOFLAGS='-p=1 -buildvcs=false' GOMEMLIMIT=256MiB
export MAAS_TEST_MYSQL_BASEDIR="$PWD/.cache/mysql-test/mysql-8.4.7-linux-glibc2.28-x86_64-minimal"
export MAAS_TEST_GO_ROOT="$PWD/.cache/go-linux/go"
export MAAS_TEST_PRODUCT_SERVICE=1
export MAAS_TEST_PRODUCT_PATTERN='^TestProduct|^TestMySQLToolsRelay|^TestARReview'
bash scripts/test-mysql.sh
```

最终原始记录位于test/controlled/maas20/fc1-tools；早期失败文件单列，不截取通过片段抵销非零exit。标准锁必须从已提交代码运行，四锁另交；不能沿用本分支锁覆盖集成最终树。

wire/complete.json与wire/invalid_second_tool.json包含实际HTTP响应、完整MySQL Session/事件/checkpoint及原child查询记录。wire/schema-validation.json为独立官方Schema结果；validate-traces.py可在仓库根复验。重采样时对原runner增加`MAAS_CAPTURE_PRODUCT_TOOLS=1`、只选`^TestProductToolsProtectedLoop`，输出到artifacts/fc1-wire，不重放已有持久请求。

仍未验/后续交接
--------------

原MAAS-21/7负责新组合独立QA、实际查询中取消/真实失锁、最窄角色正反、MySQL进程重启/两包及浏览器。旧879/R01/R02、d27 manifest范围保留。实际供应商/Higress生产producer及原EXT-01–06输入、获准Profile.Tools/UsagePolicy安装、完整publisher/Operator/管理目标、K8s实装和A01–A34整体未因此关闭；不自动合并。文本v1仍拒工具Parts/非法工具流，不静默剥离历史或切demo。MCP/文件/shell/子Agent等没有新执行器。
