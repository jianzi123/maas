# 正式模型与管理发布闭环：契约收口 FC-1

供原MAAS-20最小实现及MAAS-21归并。范围仅迁移门禁、tools-v1桥和单活/四身份接点；不接管实现或合并PR。本文标记【事实】为当前源码/已读交付记录，【决定】为本轮规范裁定，【建议】为尚待原角色实现/验证的动作。

## 基线与保留范围

【事实】2026-11-26本轮ls-remote读到统一分支agent/MAAS-10-offline-metrics最新SHA为4402c456a155646ee4111e5f4a1f285621c11273。merge对象双亲为8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a和d27d893890146c97e91454365b081f2be7d409b2，tree与d27相同。MAAS-21合并回交01a20cb4-2c7d-7697-b732-ad352f10c8e1记录PR19于2026-11-24 08:36:29 UTC以Merge commit合入。Multica关联表当前为空，不把它误判成未合并；本次Git对象/远端复证不冒称重新查询了GitHub合并API或CI。

【事实】d27同版Compose/原生K8s两包及离线MySQL/两真实安全工具、审批/取消、重启/原child消费、AR-R01/R02和完整性QA范围按原交付保留。当前源码存在正式MySQL服务和可选管理四身份工厂；不再描述成只有设计或文件会话。Compose受控已验不等于真实供应商/生产Higress、正式tools-v1、管理目标/独立publisher/完整Operator或K8s集群验收。002 Applying观察未被原QA计为门禁通过。

## FC-M：必需迁移与启动/就绪裁定

【事实】internal/app/database.go:Migrate顺序为kernel→release（含history/operations）→agent→product v1→ledger初始化→product v2→admin/offline seed。validateSchema仅核product_schema_migrations v1的摘要与Applied，再做少数LIMIT 0结构/权限探测；未核v2记录。runtime.Open在启动前调用它；/readyz目前检查root上下文与DB Ping，未重验全部迁移。故“product v2 Applying但表完整仍ready”与现路径一致；本轮未重复跑SQL故障注入。

【决定】**物理对象完整不是迁移完成证明。当前必需迁移必须摘要匹配且已Applied，同时结构/权限与安装身份一致，才允许serve/ready。** 不允许serve补Applied、重放DDL、清库或从文件/内存/SQLite恢复。ready与模型Callable分层：空models且迁移/身份正常可ready并登录查历史，具体模型仍准确不可调用。

| 当前正式服务必需输入 | 记录/结构要求 |
|---|---|
| kernel schema/0001_kernel.sql、0002_control.sql、0003_diagnostics.sql | kernel_schema_migrations版本1/2/3，各自固定文件摘要、Applied；覆盖guard、Key/预算、request/slot/usage、控制/诊断等实际读写对象 |
| release schema/0001_release.sql、0002_history.sql、management/schema.sql | release_schema_migrations版本1/2/3，各自摘要与Applied。当前Migrate无条件装配，management.disabled不能据此跳过既有必需迁移 |
| agent migrations/001_sessions.sql | agent_sessions_v1及其列/索引、JSON文档版本和运行角色读写权限。此迁移当前没有独立Applying/Applied记录，不能伪造agent迁移标记；本轮最小修复不新增平行迁移账本 |
| product migrations/001_product.sql、002_offline.sql | product_schema_migrations版本1/2，摘要均与本版本嵌入文件一致且Applied。v2当前无条件执行，即使offline_controlled=false也必需；feature可选迁移只能由以后明确的版本清单重新定义 |
| 初始化/实例输入 | 原cluster/ledger guard/slots、稳定admin、pepper/cursor身份；离线模式才核其显式seed关联。保留原Key和预算，初始化不能重置账本 |

【决定】迁移状态/门禁真值：

| 观察 | 启动/就绪与恢复 |
|---|---|
| 全部必需记录Applied＋匹配摘要＋完整结构/权限 | 可继续Open，ready仍须当前单活所有权/DB有效；不推定模型或管理目标可调用 |
| 002或其他必需记录Applying，表全部完整 | 启动拒绝；运行中探测则not ready/503并禁止新dispatch。仅迁移身份在维护窗口核验并完成原迁移，不根据存在表直接UPDATE标记 |
| Applying且部分DDL完成／必需版本缺行或缺表/列 | 同样失败关闭；保留数据和原记录，核对部分提交范围/来源再由原迁移器或受审恢复动作补齐 |
| 摘要错、未知/Failed状态、Applied但结构/权限不符 | 失败关闭并人工核对，禁止把旧checksum改成新值。MySQL DDL可能独立提交；迁移失败不一定存在名为Failed的持久枚举，原Applying可继续代表中断 |
| 主库/记录读取错误或权限不够 | 不将未知当Applied；启动非零，运行ready503。错误脱敏，不回显DSN/SQL凭证 |
| 运行所有权丢失 | 立即停止新派发并取消自身执行/退出；不能凭新池连接Ping成功恢复旧owner。旧在途按原ID/unknown恢复 |

启动未成功时没有HTTP监听，不能把它描述成已有/readyz返回503；“503”适用于已运行进程发现依赖失效的探针/业务门禁。/healthz仅存活，不伪装ready。探针失败不应让前端重发生成/创建/工具。

【建议：给MAAS-20的最小改动】

1. 在原validateSchema中抽出只读required-schema校验，首先补product版本2的固定摘要/Applied判断（直接修本缺口）；复用原kernel/release嵌入摘要列出1..3必需记录，核agent表形状/版本。不要调用Migrate或给runtime增加DDL/迁移标记写权。schema读取的SELECT授权由原运维在现有最窄角色模板追加必要范围，不授UPDATE。
2. 原Open在Host/模型恢复调度前完成此校验；原/readyz复用有界校验、DB和实际所有权状态。运行中失效须关闭新派发，而不能仅从负载均衡摘除后继续接受已连接请求。具体锁/缓存失效实现由后端提交；检查不等于跨DDL瞬时事务保证。
3. 升级使用原显式migrate命令/Job与独立migration身份。先停止/排空业务dispatch、备份，取得安装维护独占权，再执行任何域DDL；当前product锁在kernel/release之后取得，不能被说明成覆盖全部域的全局升级锁。首期不承诺在线滚动DDL。保留Applying用于核对，不允许启动自动修复。

【决定】兼容升级与恢复：checksum以准确发布manifest的原始迁移字节为准；不改旧SQL，新的变化新编号。兼容旧二进制只在其明确接受的schema manifest范围内，遇未知高版本须先评估而非自动忽略/降级。回滚应用不执行破坏性down迁移、不回滚账本/事件/身份；保留MySQL卷、pepper/cursor、原子请求/工具/审批/unknown-held。对于product v2 Applying而物理完整，原applyExtraMigration当前会拒绝继续，故不能宣称重跑migrate就自动成功：需原后端提供受审幂等恢复/核验动作，持锁验证完整布局、seed及摘要后才可提交Applied；runtime不能手工补标。kernel/release现有可重放Applying语义不自动外推到product域。

验收由原MAAS-20/7在同SHA：002 Applied/缺行/Applying完整/Applying部分/错误hash/Applied缺列/读取拒绝；恢复后原历史/消费不变、runtime无DDL/UPDATE标记权限；运行中漂移ready503且0新child；两个进程/迁移与调度并发、DB重启/锁断开；每种情况区分作者与独立SQL/Compose证据。

## FC-T：v0.8能力输入到真实工具桥

【事实】已读MAAS-9 v0.8固定包，代码ac5e9af36c2fbdda09e3713f3d0b6f9e6ca11f88、四锁037be34aba15563aa77c3dc1dcd1068c591f620b。45 SSE向量与内部maas.model-tool-turn/0.1-draft是受控输入：termination=controlled_clean_DONE、accounting_authority=false。包内deepseek-flash/模式/文档版本只保留当时pending事实，本轮不重新认证当前账户能力；MAAS-9已沿原运行更新来源，不重复派发。其本地字符串回显是算法夹具，不替代本产品已交bounded_arithmetic/list_visible_models。

【事实】4402的app.Models.Resolve/Supports/prepare、kernelmodel.RelayModel.Supports均明确拒绝生产tools-v1；capabilities.tools_protocol=null。prepare只允许user/assistant文本，拒绝ToolPart/tool role，旧kernel.public_response严格拒tool_calls。offline_controlled另外经同一MySQL/原Admit/Finalize做显式受控演示，不是生产fallback。真实工具桥属于待实现/批准接点，不是把配置protocol改成tools-v1就开启。

【事实】现有a.Usage已使用Tokens/Money可空指针与Groups，app.Models.usage读取原子账本逐维known_used/unknown_held及价格/币种，已证明no-send释放也有专门投影；这部分继续复用，不另造整体known布尔或第二账本。v0.8的sum_ints/echo_text是算法夹具注册名，而产品工具是bounded_arithmetic@1与list_visible_models@1；不能静默改名伪称消费同一Schema。原45向量保留，产品注册表派生的新向量需独立ID/修订和映射。

【事实】现有a.Usage已使用Tokens/Money可空指针与Groups，app.Models.usage读取原子账本逐维known_used/unknown_held及价格/币种，已证明no-send释放也有专门投影；这部分继续复用，不另造整体known布尔或第二账本。v0.8的sum_ints/echo_text是算法夹具注册名，而产品工具是bounded_arithmetic@1与list_visible_models@1；不能静默改名伪称消费同一Schema。原45向量保留，产品注册表派生的新向量需独立ID/修订和映射。

| 接缝 | 【决定】最小实施边界与可复用点 |
|---|---|
| ModelClient/来源选择 | 原接口继续text-v1；新增tools-v1的批准能力分支与独立结构化归一化器，维持同一个app/modelSource和受保护Relay工厂。明确返回完整Calls和原child request_id，不走供应商SDK/新URL客户端/另一账本。缺能力/adapter批准422且0上游attempt |
| 输入与Higress | 冻结source/model/mode/profile/capability/adapter/tool registry及Schema修订；工具Schema、原assistant工具提案和tool结果均算输入上界。Higress必须保持已批准role/tool_call_id/arguments形状，不删除工具字段降级为文本；实际Body摘要/route/publication/epoch和私有mTLS必须与原H4票据一致，不以新增客户端header自报能力 |
| 旧协议兼容 | AR-1 draft.2路径/事件1.0、票据v3、终态3.0、Observation1.0不改。tools-v1是原已有能力枚举下的独立内部流分支；旧text公开序列化照旧拒tool_calls。若既有Profile/票据body/能力绑定无法覆盖新语义，先给最小内部版本差异，禁止放宽旧validator或篡改历史snapshot hash |
| v0.8回合提案 | 不把0.1-draft Schema直接作为生产证明/应用Event。它的accounting_authority=false必须保留证据身份；生产结果需从可信Store读取原child终态和计量。不能把controlled_clean_DONE改名当Higress真实终止证明 |
| SSE工具组装 | 完整UTF-8/SSE事件解析，choice=0，按tool.index分别拼接原arguments JSON字符串；冻结source call ID/name/type，拒越界/重复/缺口index、ID冲突、非法/重复键JSON、未知Schema/工具/权限、过量字节。保留原wire摘要，整批校验完再执行第一工具 |
| 结束与财务 | 仅批准来源的finish=tool_calls＋最终usage/有界结束能完成当前模型回合；每个子调用原Go Admit/Finalize唯一结算。finish=tool_calls不等于父Run完成，工具结果回填下一次新child；无效工具提案不抹掉已经结算的模型费用 |
| 结果回填 | 原assistant工具提案一次入历史，按固定index串行工具执行，每call仅一个role=tool/tool_call_id/content结果；禁将输出作为system指令或可执行HTML。无供应商并行保证时不发送未批准parallel_tool_calls，不把合成双工具当真实并行验收 |
| 审批/取消/unknown | 沿原参数hash＋tool/policy/scope修订＋expiry/decision_id和fence；源完整、原child可信终态、整批校验后才可批准/派发。取消只结束当前执行并阻止下一child，不撤销已提交子账务；ACK/工具副作用未知按原ID needs_confirmation，不以批准重跑。slot回收须独立关闭证明，不能释放财务held |

【决定】批准来源final与可计算维度分开：缺最终权威性时不得从progress定actual；已获证最终但价格分类不足时，原内核能算的Token与未知Money分别保留known/held，不能把未知维度填0、也不能清空已知维度。硬预算缺可信全计费上界在发送前拒绝。凡当前终态3.0无法合法表达的状态，先保持原失败/不完整行为，不自动采用D1/3.1。不得为了执行工具而伪造一次成功子终态。

### 可重放正反验收输入（规范期望，非本轮真实运行结果）

| 编号/映射 | 期望 |
|---|---|
| T01：v0.8 TC01/02/36/38 | 两个工具arguments交错分片，批准finish/usage/结束→原child成功一次→整批验证→按index串行真实算术/可见目录→原call结果回填→第二child最终回答；父只聚合两child，不另记usage事件 |
| T02：TC03–15/33/43/44 | 第二工具参数非法/重复键/未授权，即使第一工具合法也零工具dispatch；如果原模型child已结算则原消费保留，Run失败而非退款 |
| T03：TC16–18/40 | progress、缺usage、相同/冲突final、cache/reasoning子集、null与0逐项映射原权威性与逐维unknown-held，不按last/max相加 |
| T04：TC19–26/31/32/39/41 | EOF、顶层error后DONE、重复DONE/finish、length截断工具参数、总截止：无成功工具dispatch；原首次终止原因/receipt先耐久；不换childID重发 |
| T05：TC27–30/34/35/37/42/45 | tools未批准/text-only来源、profile漂移、伪造tool结果历史/ID错配：拒绝或故障关闭，不能静默换源/降级/忽略第二调用 |
| T06：批准后取消/派发竞态 | 决策过期、参数/权限变化、旧fence拒绝；未执行call attempt=0，已执行安全工具失败/取消保留attempt，非幂等未知needs_confirmation |
| T07：子成功之后父取消 | 已提交child actual/usage不改；不派工具或下一child，不产生父级第二结算，不把流写失败当退款 |
| T08：Admit/Finalize ACK未知、重启回放 | 查原child/command/call身份确认；重复GET/replay新增模型/工具/usage写入为0；缺证据不能解除未知屏障 |

这些向量先用于原后端受控HTTP/SSE→原内核/真实MySQL回归，再由MAAS-7同SHA独立复验；真实来源批准后才扩成供应商证据。当前不要求密钥才能完成分支/归一化/受控验证，也不凭旧文档选真实模型。

包内另给FC-wire-P1/FC-wire-N1两份产品注册表派生SSE：正例分片组装bounded_arithmetic({a:17,b:23,op:add})及list_visible_models({})，未来可信桥确认原child后顺序得到40及主体可见目录，再以原source call ID回填第二child；反例第二工具带额外scope=all字段，整批零执行且保留已结算的模型费用。它们具有独立样例ID、保留v0.8映射；只验证规范JSON/SSE组装一致性，不签发批准、不执行工具，不是供应商保证或HTTP实测。

包内另给FC-wire-P1/FC-wire-N1两份产品注册表派生SSE：正例分片组装bounded_arithmetic({a:17,b:23,op:add})及list_visible_models({})，未来可信桥确认原child后顺序得到40及主体可见目录，再以原source call ID回填第二child；反例第二工具带额外scope=all字段，整批零执行且保留已结算的模型费用。它们具有独立样例ID、保留v0.8映射；只验证规范JSON/SSE组装一致性，不签发批准、不执行工具，不是供应商保证或HTTP实测。

## FC-I：单活MySQL与管理四身份评审

【事实】正式app.Open使用MySQLStore聚合Session JSON/CAS；数据库专用GET_LOCK的持有连接定义唯一scheduler，第二进程拒绝。后台每秒在该连接上检查IS_USED_LOCK=CONNECTION_ID，异常取消自身并退出；恢复running→needs_confirmation，accepted/waiting保留原截止。该检测周期不是瞬时fence保证，原文档不能将它宣称为多活/无重叠调度。运行新派发、恢复检查点和已在途回调的原fence/CAS仍须测试。

| 管理身份 | 当前原工厂接点/保留最小边界 |
|---|---|
| Reader：maas_release_history_reader | history.Reader.DB，脱敏历史/活动投影只读，不取得原spec/Secret/核心写权 |
| Payload：maas_history_payload_reader | 独立PayloadDB，仅受限历史装载/回滚检查服务读取原spec/Resolution；不得原样回浏览器或经Reader泄露credential handle/URL |
| Operations：maas_release_operations_runtime | 原管理Service操作ID/状态与完成投影写集，不写核心Key/预算/request/slot/usage，也不代Publisher激活 |
| Publisher：maas_release_publisher | 原OpenPublisher→WithManagementOperations，同事务发布/完成hook；保留原guard→release→operation锁序和有限列权限，不以合并operations/core角色绕过 |

【事实】scopedDB检查四用户名不同/非root/不共用core，要求各自CURRENT_ROLE精确；OpenPublisher也核窄默认role。注释明确这不是完整effective grants审计：直接GRANT、跨DB/服务端错误指向及账户权限漂移仍需实证。四连接必须指同一获准安装数据域/server/database/cluster，不能只因用户名/role正确就接受错误目标；payload/reader/operations/publisher按实际角色做正反SQL验证，不打印DSN。

【事实】management默认关闭，启用时原Registry、kubeconfig、namespace/domain、Reader/Operations/Publisher工厂已装配；K8s client构造不证明CRD、RBAC、目标Operator/Higress已部署。4402的cmd/operator仍为缺生产依赖的骨架；独立publisher/Operator候选不因为管理工厂存在就进入已验安装包。MAAS-21合并记录将PR12/20等单列未纳入范围；本轮不自动合并它们。

【决定】服务ready、管理模块可用、候选发布已受理、活动publication可调用分开。management=false允许明确不可用；management=true缺四身份/目标/Registry时不能退core或假对象。真实发布要原UID/RV/history/批准与H1–H4/validation屏障、全接流boot和密钥代际。回滚新generation/publication/epoch，旧命令ACK未知只查原身份；清理/slot释放不退unknown财务占用。

## 按风险最多三项下一步

| 优先级/原责任 | 下一步（不新建平行实现） | 可验证验收 |
|---|---|---|
| 1／P1，MAAS-20＋8＋7 | FC-M迁移一致性及维护窗口门禁；先补002 record/摘要，再共用全部必需schema就绪检查 | Applying完整/部分都不serve；Applied才可ready；运行漂移0新派发，恢复/降级不改历史账本；runtime无DDL/标记UPDATE |
| 2／P1，MAAS-20＋9＋7，架构维护 | 消费v0.8完成tools-v1受保护桥，批准模型/适配修订才开启；原离线两工具演示保留 | T01–T08在真实MySQL＋受控HTTP下每child唯一Admit/Finalize；错误批次0工具副作用；再按EXT-01–06做获准真实来源 |
| 3／P1正式管理上线前，MAAS-20/11＋8＋17＋7 | 单活锁丢失/旧owner停止与四身份同数据域/最窄权限；独立publisher/Operator候选分开审查接入 | 双进程、锁断开/DB重启、旧callback/fence、四角色正反GRANT、错误DSN目标、真实K8s UID/RV/回滚/原operation恢复；全接流boot/Secret验证单列，不用client构造代替 |

本轮不增第四深化方向，不重复广播五方review。当前并行Mika评审可直接复用此表与证据索引；d27离线可部署交付和既有独立关闭不因此撤销，后续新组合另记完整SHA/四锁/镜像与受控/真实边界。

## 本轮验证边界

本轮只读Git提交/源文件、authenticated附件及离线契约期望矩阵；原始源码摘要、迁移摘要/物理对象清单、v0.8包摘要和合并tree关系随证据包。没有SQL故障注入、Compose/K8s/浏览器、真实模型/工具桥/角色/生产部署运行结果，不重跑或认领旧d27/QA计数。规范用例可复现检查是设计边界检查，不能自称产品门禁修复。公开AR-1/OpenAPI/票据/终态/事件无本轮版本变更；原后端按本结论提交最小实现、代码后重锁，架构不代写或自动合并。
