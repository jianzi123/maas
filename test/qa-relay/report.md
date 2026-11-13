固定c7e863b11fb34ee2828c947393444e1e5a9baf08完成顶层error与源端采样独立受控复验。该候选包含d2d7869，仍与默认基线925d8c5分别记录。新增error见证在本轮受控范围通过，可关闭对应函数/HTTP缺口；完整ALG-D1/P1、真实adapter与生产身份批准不因本结论关闭。仅新增test/qa-relay测试/报告/矩阵，产品api/cmd/internal/scripts/config/go.mod/go.sum与c7一致。

**本轮唯一结果。**

|范围|结果|证据|
|---|---|---|
|独立真实MySQL/受控HTTP调用|19/19通过，0失败/跳过|qa-targeted.txt、qa-relay-evidence.json|
|独立采样器配置/并发/boot函数|9/9通过|qa-targeted.txt|
|作者实际采样回归复跑|10/10通过；另导出9条作者流程新样本|qa-targeted.txt、qa-author-relay-source.json|
|作者既有有界队列函数|1/1通过|qa-targeted.txt|
|原附件JSON/hash/来源|原始SHA256匹配，6份工作树及Git源码字节全部匹配，9条原summary＋1丢样分母保留|qa-original-source-check.json及reference原件|

四种运行计数与原作者9条源分开，不累加历史80/72、Usage20/Reader12或QA-001/002/003。编译检查仅为no tests to run，不计通过用例。无新的产品失败；全部本轮断言首跑通过，没有改产品或放宽oracle。

环境为Ubuntu-22.04 WSL2，Linux6.18.58.1-microsoft-standard-WSL2 amd64，Go1.26.0、真实临时MySQL8.4.7、真实loopback HTTP和产品Relay/账务事务；Redis6.0.16随原编排可用，但本轮rate/H1–H4和批准metadata仍为明确fixture，不据此宣称真实Redis/网关验证。本轮没有API-server/浏览器/模型/GPU运行。

**顶层error锁存。**

独立覆盖：内容前立即error、role之后error、已有内容后error、error与usage同帧、error与内容同帧、error:null，以及非流式error。供应商正文及测试私有标记不进入下游输出；错误同帧的内容不输出；已有内容后只允许错误前那一份内容通过。后续合法content/usage/finish/DONE不能恢复成功，异常路径没有正常DONE。流式及非流式error终态均failed/upstream_protocol_error，summary结果与真实终态一致。

其他负例包含内容前/后EOF、显式取消、超时、内容Write失败。分类分别保留interrupted/cancelled/timed_out或实际失败状态，未生成第二次上游尝试。所有19次调用均核请求/终态/汇总各1，终态满足冻结3.0 Schema，原slot在无关闭证明时QUARANTINED；受控证明释放原allocation后Token/金额不退款、不改写终态。异常五项usage及计费actual为null，合成Token held140/金额held520000；成功只结算19 Token。没有把采样或transport关闭当作独立安全释放证明。

关联请求：
- 内容前error：09d1b0b3-2d23-478e-a299-4ca9b980e511。
- 内容后error：650e1164-99e7-49a2-b8de-48528bed35e6。
- 非流式error：6a0af234-0775-433a-a10a-5ff704b25490。
- 取消：5866b0a3-439d-4fd6-87fb-b3b809aa933e；超时：ef9dacfc-ac42-4eff-a1ef-703dc4e02d86。
- 满队列仍成功：826b13b0-a062-43b6-ae57-df32b4742fb1。

**测点与注入。**

role/空delta/空choices/usage-only和无内容完成均不能抢占content；内容不存在时终态first_chunk_ms及内部content/write/flush保持null，不能补0。立即error不算合法protocol事件；此前有合法role则protocol测点可保留。非流式仅导出end/result，所有协议/token测点null。无http.Flusher实现的writer没有Flush测点；失败Write没有write_ok。Flush只表示真实调用尝试，没有客户端ACK。

内容延迟场景通过role写入屏障再推进上游，避免仅凭sleep猜是否处理首事件。同帧含content和usage时，QA驱动wrapper在真实request_usage_diagnostics INSERT前等待90ms，下游首内容Write再等待70ms；receipt/事务仍执行真实MySQL。另有45ms内容前等待，全部是明确测试注入，仅验证测点分离，不是平台性能/SLO。对应请求5529a200-ee1a-47a2-ad14-f01865f91a04实际Go局部记录为protocol43.99ms、content89.84ms、完整Write264.33ms、Flush尝试264.35ms。该次内容测点在诊断等待和Write之前；旧first_chunk_ms与内部content使用相同接收时刻、不同起点的源码关系也已核对，独立用例检查旧字段相对request.Received及Forward相对时钟的关系。不得把这些带注入数值当作优化收益。

内部每个请求以本次Forward进入为0；旧first_chunk_ms以原request.Received为0。没有跨请求/组件相减，没有把Write/Flush写成client receive。源码取receivedAt在Next返回后且早于AppendDiagnostic和Write；本轮没有跨组件可信校准或客户端收包测量。

**有界队列与分母。**

本轮独立19次Forward中1次明确关闭采样，18次走offer，实际17条summary＋1丢样。满队列场景预填一个纯测试占位，业务调用期间不drain，结束后核占位未被替换、Dropped恰增1且没有额外summary；该占位不是另一次业务请求，不能加到执行分母。满队列请求仍成功，生成请求/终态/汇总各1，budget正确，原slot释放不改账务。独立并发函数另验证400次offer、capacity4、保留4/丢弃396；这只是有界正确性，不是吞吐或ns/op基准。

采样无业务DB写新增的实现路径已静态核对，运行上核验业务行数及唯一终态没有放大；未运行全SQL语句级开销剖析。每个Forward最多一条summary，缺采样仍业务正确。前述17条样本逐字段保留Go输出，未由Python合成时间或填身份。

**来源与D1边界。**

作者原始JSON SHA256为a2589061b5c39fb259397e6bdf6129cbdb16bce8579318438fe760642fb51458，与原manifest一致；6份源码的工作树/Git blob摘要一致。作者原9条正常/失败样本及1次满队列丢样与本轮数据独立存放。

本轮qa-go-relay-source.json的17条summary来自真实Go记录，schema保持maas-go-relay-source-1.0/maas-go-relay-export-1.0，source_revision原值c7e863b-qa-controlled不改写。原作者working-tree-d1也不回填为交付commit。qa-source-manifest.json另记固定产品commit、QA overlay摘要、原case/导出文件SHA256和生成时HEAD。每个独立场景创建本地采样器，其instance/boot是本地生成标签，不是生产进程登记或真实Worker身份；clock_scope逐request隔离。公开采样白名单不含prompt/response/error正文、Key、Secret、URL或私有payload，测试敏感标记也未进入导出。

缺trace、完整binding、工件/运行元数据、experiment/cell/replicate、生产实例登记和可信校准，complete_sidecar_ready明确false。没有拿request_id冒充trace，没有散列publication/revision来伪造完整binding。MAAS-10当前消费工作只在其原tools/perf流程接线；本轮不修改消费端、不宣称完整sidecar导入、E1、跨时钟或平台性能通过，未复跑10.31ns局部offer微基准。

**复现与清理。**

bash test/qa-relay/run.sh需显式批准的Linux Go/MySQL及自有缓存；Go overlay只加入独立测试，原MySQL编排临时副本将包筛为internal/kernel，原生命周期/守卫保留。90ms诊断延迟只在QA驱动wrapper，未改产品测点或正文。summarize.py从原始Go evidence生成去重计数和导出manifest，不补未知字段。没有二次重跑或丢弃失败记录。

qa-cleanup.json确认本轮MySQL临时目录及专属Go工具缓存已删除，无本次MySQL/Redis/Go测试进程。schema/账号/socket随自有数据库退出清理，未留长期服务。完整源码、逐请求终态/诊断/采样、真实日志、原来源JSON/manifest、摘要清单和Git bundle随评论交付。

A01–A34完整矩阵保留34行，全部整项NOT_ACCEPTED；旧Usage20/Reader12、QA-001/002/003及页面结果仅沿原受控范围保留，不无理由重跑。真实adapter/生产身份、Higress/Secret/validation、接流实例/boot覆盖、目标部署、Chart锁定及整体验收仍缺，生产继续不可调用。MAAS-3/7保持in_progress。