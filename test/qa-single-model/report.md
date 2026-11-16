UI16-U2 本次独立定向复验通过，建议在该受控范围登记关闭；不代表PR #10已合入。基线8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a；候选head aa9720f635c1e152ab8b096ef9713933232bcec0、产品修复e323c54ea43b80d8acc218b11b077e290e6fa5a4分开记录。原UI16/Delete签收1e4a1af继续原SHA/范围，不重跑。

本轮读取MAAS-7/5最新讨论、项目单模型描述及MAAS-18完整里程碑。MAAS-18为协调任务，QA仍回本单；未改其他任务负责人/状态。原工作树7089ceb干净并保留，新QA从统一分支建立增量，PR目标为agent/MAAS-10-offline-metrics；UI候选只导出缓存测试，不把它当默认分支已合入。

实际执行：Node22.23.4、候选package-lock隔离npm ci（159包），Vitest Response/jsdom。原四探针及六项成功/503×刷新/列表查询/视图切换的A/B交错，10/10通过，0fail/0skip；u2-results.json保留逐项原始结果。独立执行原探针，不把开发者10项加成20项。A作废后按钮可再启动B；A成功/503晚到不能覆盖B详情、写入error或清掉B忙碌；B返回后原B ID正确且按钮恢复；全部请求为GET，无自动生成/管理写入。不是浏览器/Go/DB/真实上游证据。

只测新U2差异，未重跑旧UI16/Delete、旧内核/历史/GPU或全仓。首轮依赖缓存已不存在导致MODULE_NOT_FOUND，属环境失败，未计业务样本；随后按候选锁文件npm ci并复验通过，未修改候选/产品源。最终源文件哈希清单见source.json。

复现：导出aa9720f的console，在隔离console执行npm ci --ignore-scripts --no-audit --no-fund，然后Node node_modules/vitest/vitest.mjs run src/usage-exact-review.test.ts src/usage-exact-interleaving.test.ts --pool=threads --maxWorkers=1 --reporter=json --outputFile=<新输出路径>。两个原始探针另以.in原字节保存，不能覆盖产品实现或把临时一行补丁当提交。

单模型里程碑准备：matrix.json列11个最小场景：发布、Key/预算、流式、取消、上游错误、原ID查询、权威非空用量、未知用量、超额、撤销、重复终态。manifest.template.json要求实际组件SHA/digest、model/source/profile/价表、环境及证据类别；每格原R或operation/CR UID/publication与原始证据单列。verify_evidence.py为只读离线oracle，校验202不能替代网关/validation、拒绝请求零上游/预留、单次生成/唯一request-terminal-summary、DONE提交顺序、原R精确读取无写、可信finality和原价表、unknown实际null/held保留/slot不改财务。它不自动发送请求或编造profile。

缺输入模板实际退出2并报告21个缺项/未执行，template-rejection.json保留；五个synthetic oracle正反控制通过，包含202无路由、unknown补0、错lookup R、重复终态拒绝。五控制是校验器测试，不是五个端到端场景。所有11场景本批controlled/real_upstream/production分别NOT_EXECUTED/NOT_EXECUTED/NOT_ACCEPTED；A01–A34完整范围仍NOT_ACCEPTED。历史可信证据仅复用其原SHA及关闭范围，未来同一SHA组合闭环仍须新关联证据。

已核新publisher候选532b154（代码db28174），它从8dbf99e新增窄命令入口但文档明确gateway/Secret/validation工厂及权威非空用量pending；本轮未执行publisher或新DB测试，未把该候选合入QA代码树。具体待输入：
- MAAS-9/2与成员：精确ExternalAPI模型/站点/endpoint、adapter/profile修订、计费上界与progress/final/error/终止语义批准（DeepSeek优先，不凭候选文件推定批准）。
- MAAS-8/成员：Secret引用安全渠道、验证Key/额度、预算周期/数值、币种/价表、停止条件及目标身份/TLS/boot/route digest。
- MAAS-3/8：同一真实Go/Higress/validation/adapter工厂及调用入口，提供可重建部署和版本组合，缺证据仍拒绝。
- MAAS-5：接同一API的真实流式、取消/失败、原R与非空/未知用量页面。当前U2组件通过不证明上述链路接通。

未启动DB/API-server/GPU/模型/目标部署，无长期服务；测试进程均前台退出。没有使用真实Secret或付费调用。下一步由Mika/MAAS-17按具体批准处理PR #10集成；新后端/批准profile交回后，在同一组件组合按11格定向执行并收原始HTTP/SQL/requestID，公开/财务/容量分别判断。MAAS-7继续in_progress。
