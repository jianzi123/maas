a4c1347本次执行未完成，不关闭AR-R01/R02。固定代码b808dc6abe73b6614ef865238f8a1e0ec31aae5f、四锁a4c1347b6e01ed6fdf9925cf9ee26cb82251c405；远端pull18/head与branch均按本轮读取固定。独立有效产品用例0、通过0、产品失败0；没有借作者19/28或静态Schema结果签收。MAAS-7保持in_progress。

执行前必需issue/线程扫描/AR相关时间窗/active runs/wakeup均核。只有本唤醒批次，未找到同a4c独立签收；一次性wakeup已enabled=false，无需disable。原qa-single-model本地未推送成果15a65b1干净且保全；当前工作沿原18项矩阵，仅补ar_a4c_repair受影响字段，没有新建产品矩阵/改产品。未中止TLS或他人工作。

原审查证据ZIP01a1f251-ce2c-7c89-96d7-49c099f5e2a1认证已下载解包。19e原review_probes_test.go、review-probes.jsonl及review-summary/validation-status原字节保存为old-19e-*。其2过2失是旧审查记录，非本次重跑，不把旧200反例改成新方案通过。未执行压缩包中的脚本/manifest命令。

建立独立detached qa-agent-a4c工作树固定a4c，不切换其源码。读取真实修复/19新增叶与工具注册/审批路径，准备QA派生测试overlay：0/98/100/102历史使用正常AR HTTP命令构造；稳定分页200；delta后旧签名token410且snapshot_required=true/retryable=false；丢弃旧页/旧resume_cursor，完整新Snapshot/分页后核“你🙂”一次、新after无重复，GET不写revision/不新增模型。终态/编辑使token失效仍保守要求重取；频繁写入可能连续410，不宣称旧水位冻结缓存。

新oracle不再把旧cursor回放作为成功恢复路径（旧逻辑仅原件留档）。步骤/工具页的全面跨页独立覆盖仍需补跑，不能只借源码表明三个路径都检查revision就关闭。CursorMigration同revision/legacy/篡改、纯/读/经批准synthetic write×duration/tool_timeout/cancel、未审批取消attempt0等派生用例只准备，未运行。来源模型/认证/目录及阻塞工具是_test.go受控适配，真实service/handler/registry原件复用，不当真实供应商或外部副作用。

工具判据：Run仍limit_reached/duration_limit，ToolCall不能出现run专属enum；纯/读合法failed或cancelled，按持久派发事实attempt=1，未批准未派发取消0。旧缺Attempt的known executing/completed/failed/unknown按原推断，ambiguous cancelled保持0不得伪造执行。synthetic write依原registry强制审批及原approval API，unknown/needs_confirmation不能改failed或重复Drive重放。ToolCall/Step/Run/Event按原draft.2严格Schema验证，当前仅原契约字节与旧19e一致的静态核对完成。

实际环境尝试：
1. Linux Go1.26，既有批准工具/模块缓存、自有固定源码和私有GOCACHE，命令go test ./internal/agentruntime -run '^TestARReview' -count=1 -v -timeout=120s。会话33084，Go PID34109观察到futex_do_wait且无测试输出，等待后只向该前台会话Ctrl-C，退出1。
2. Windows既有Go1.26工具链（version实际确认），同固定源码/自有GOCACHE及overlay，选择'^TestQAAR'，会话80975。无测试事件后仅本会话Ctrl-C，退出1。
3. Windows离线GOPROXY=off/GOSUMDB=off同选择器，会话99469仍无事件输出，后仅本会话Ctrl-C，退出1。空输出不能判断是编译/依赖/执行哪一内部阶段，本轮只确定未产出测试开始/结果；不是有效产品失败，不写“测试通过”。
无已执行skip成绩。首次QA UTF-8/路径等问题没有作为本轮产品结果；Go测试超时只约束测试二进制，不证明编译阶段已完成。本轮未通过更改宿主账户/共享WSL/他人缓存绕过。

清理：没有启动MySQL、无本次datadir/socket/SQL账号，SQL两个child/两个usage/父聚合/known-unknown-held与MySQLSessionStore都未执行。命令原样保留scripts/test-agent-mysql.sh选择器，不把TestInstallationComposition无匹配算通过；本次不作安装结论。Windows记录的两个自有Go PID35240/59100按进程路径及原TestQAAR selector逐个核对后清理，结果见独立cleanup记录；Linux34109仅向原session Ctrl-C，额外进程消失核验未完成，不虚报全环境清空。未终止其他Go/daemon或重启WSL。

后端纯服务、SQL及前端组合均未验。旧8dff511对19e的作者8/13组范围不变，尚无本次同a4c/最终UI/Principal-Cookie-CSRF独立记录，不借其替代新410/guard恢复。真实模型/Higress/生产与A01–A34仍未验。旧UI16/Delete/U2/R1–R3/Usage/Reader/TLS/性能窗口全部保持原SHA，不重开。

下一步：执行环境恢复后，在固定a4c工作树先运行两个派生QA测试文件和必要step/tool分页/legacy attempt兼容；collect Run/Session/ToolCall/Event原始HTTP与模型/工具计数。SQL可用再按原Agent选择器跑两个子R/两个usage/父聚合唯一账务；后续安装组合独立保留TestInstallationComposition。前端新head交回后才补同一可信会话与a4c服务端的410全量重取及新cursor after。继续按原18项分段填结果，未得到有效测试事件不得关闭AR-R01/R02或批准合入。
