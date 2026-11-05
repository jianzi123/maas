# FE-R02 真源与公开响应接续

基线为 PR #2 `2319eb6`、发布 PR #1 `6302256`。已读取 MAAS-7 原后端分支 `b6d2d77`：工作树干净，平行诊断候选已退役；其完整 bundle 保存在本轮工作区归档，没有覆盖该分支或重复合并替代内核。发布历史在隔离分支 `agent/MAAS-11-authoritative-history` 实现，再正常 merge 进入唯一后端分支；原发布PR继续fast-forward，未强推、未另建远程仓库。

实施采用 MAAS-2 最小补充（附件 `01a1abe7-babf-7740-8912-661a32e5f30e`）。公开字段、终态3.0、ObservationEnvelope1.0、内部诊断0.1-draft.1均不变。此前58项为历史自测口径；本轮72项包含它们，不能相加为130。

## 历史真源及读取

原发布迁移1、核心迁移1/2/3字节不改；发布域新增迁移2。具体实现见 `docs/retained-history.md` 和 `internal/release/history`。首次通过 uncached CR 获取、fresh UID/generation/spec核对和批准解析的快照，在原 Observe 的同一事务建立原所有者、不可变spec/精确Resolution输入、算法标识、原RV、DB UTC首次接收时间和同UID提交序号。捕获授权域必须与参与revision计算的批准Resolution元数据一致。同键不覆盖，ACK未知原键查回。

`created_at` 是首次平台接收该UID/revision的主库时刻，不是CR创建时间或回填时间。旧hash缺原spec/Resolution/可信时间/授权域时，迁移只记missing清单，Reader503；不复制当前CR、不跳过旧行返回完整分页、不伪造eligible。校验通过的旧证据导入工具尚未提供；必须由原责任核验原证据后显式接续。

读端只读 `release_history_directory/projection/completeness` 脱敏视图及原发布活动态，真实默认role证明不能读原spec/revision输入或写历史/业务表。摘要不含Secret引用/正文、credential handle、完整URL或Pod模板。原所有者授权域独立于同名新UID；命名空间能力403、原域不可见404，存储/完整性失败503。

第一页冻结同UID串行事务分配的history_seq水位，排序仍为(created_at,revision)倒序；游标HMAC保护并绑定cluster、授权scope、namespace/name/UID、page_size、目录版本、水位、末尾二元组。晚到插入或带旧时间的新记录不会串入后续页；目录版本变化拒绝旧游标。保留状态独立可变且不覆盖原输入；缺批准策略不自动清理或设默认天数。

Reader重新读真实UID/RV并有界复核；deleted/replaced/deleting阻止回滚，缺live/registry为unknown，不借历史存在宣告Callable。`RollbackService` 为受控管理工作流内部端口：原UID/RV→同UID权威载荷→完整性/批准引用/来源→新鲜UID/RV→一次K8s CAS；冲突拒绝、ACK未知不重放。公开operation.id持久管理工作流及完整公开回滚HTTP仍需原发布管理层接续，本轮没有伪造202/成功操作记录。

`controlapi.Handler.Revisions` 已接同一Reader并严格校验ReleaseRevisionPage。`cmd/control-api` 可显式配置 MAAS_HISTORY_NAMESPACES、MAAS_HISTORY_DOMAINS、MAAS_HISTORY_SCOPE、MAAS_HISTORY_CURSOR_KEY（至少32字节）；可选 MAAS_HISTORY_KUBECONFIG 仅建立实际只读K8s客户端。不配置则保持依赖失败；无批准引用Evaluator时资格unknown。没有自动建立集群、授权或读取任意namespace。

## 公开响应

Go relay现在按完整SSE事件组装CRLF、多data行及UTF-8，受事件/总量限制，事件上限不超过原前端262144限制。keepalive不当token。不原样透传provider body、id、model、metadata或prompt/completion usage。

所有正常响应id=`chatcmpl-原可信UUID`，model=原快照alias，created=原请求固定服务端Unix秒；响应头X-Request-ID始终原UUID，不采用上游头。上游物理model若提供须精确匹配批准快照；未实现任意名称宽松匹配。多choice、工具/不支持finish、非法计数或语义字段故障关闭，不伪造stop。

usage帧仍按v2在转发可见内容前先写独立receipt，但所有中间ChatChunk不带usage。仅确认唯一终态succeeded后，读该不可变终态的Usage构造最多一片最终Usage，随后一次DONE。非流式同样先结算/读回终态再白名单构造ChatResponse。未提供total仍null，合法0保留0，不从诊断表填财务显示，不启用D1。

缺合法finish、重复DONE、DONE后数据、解析/诊断/结算失败、取消/截止均无正常DONE；已写headers时尽力写event:error＋原Error形状并关闭，未写headers用脱敏HTTP错误。写失败发生在成功终态之后不反向改账，只记传输诊断。原58项异常null/held、slot独立回收、owner/fence和ACK约束继续成立。

核对了前端固定提交 `6d016041...` 的 `console/src/api/stream.ts`：Schema仍严格，finish必须先于DONE，解析多data行。前端header/chat/error ID一致性检查与现有五项竞态修复仍归原MAAS-5；本轮没有改前端或用放宽消费者掩盖后端问题。

## 验证与范围

`go test ./...`、vet/build通过；真实临时MySQL8.4.7/Redis6.0.16的72个数据库/受控场景通过（含原58）。新增14项为历史6、视图默认role1、公开流6、历史HTTP1。普通缺省数据库组明确skip；原始事件和SQL输出随任务附件交付。K8s写入/ACK为fake client与注入，不是目标集群或API-server保证；Higress仍为受控上游替身，未执行浏览器联调。

独有测试分支/原始提交已保存，未重复接管MAAS-7。自有临时实例、schema/账号、socket/数据已清理；未影响其他工作区。生产Operator继续DependencyMissing，真实H1–H4/Secret/validation、原旧行证据导入、完整公开发布管理/回滚、SelfHosted/GPU/Helm及A01–A34仍待对应授权和独立验收。
