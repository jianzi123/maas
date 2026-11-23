本轮部署差异独立 QA：运行闭环通过，完整性验证器未签收

运行对象固定 b8688ecbe3f9647ac8feb1c42afd8f7a021370b7 / code64b36c3480735ae28148bf973103678c92a76d0b；制品/客户端新对象 bc2f7b37e540511644794a30cac4a4b88fddd96c / code41e8ec3f09b83f247503cf2599e2d126b8171f33。已用Git逐路径核对internal/cmd/api/console/go.mod/go.sum、镜像配方、Compose/K8s YAML零差异，复用已完成的业务证据，没有因文档/获取方式换ref重做旧矩阵。原879 R01/R02受控关闭及性能结论保留。

唯一当前交付阻塞 QA-DEP-MANIFEST-001：完整性验证器接受不完整清单。

|实际负例|预期|实际|
|---|---|---|
|完整清单＋破坏main.go字节|拒绝|CLI exit1，正确|
|MANIFEST.sha256.json={}，仅保留VERSION及四份锁|拒绝必需源文件缺失|CLI exit0、passed=true、filesChecked=0|
|清单删source/cmd/maas-service/main.go，实际main.go也损坏|拒绝不完整清单|CLI exit0、passed=true、filesChecked=846|
|SOURCE.sha256.json删cmd/maas-service/main.go|拒绝且不发布source|fetch_source发布缺main.go的source，并报passed=true、833文件|
|来源hash错误或../路径|拒绝且不发布source|分别拒绝，正确|

准确入口：deploy/release/verify_bundle.py的verify只遍历传入manifest；fetch_source.py仅遍历SOURCE清单，未对锁定源码必需集合做完备性核对。正常制品及网络字节均已核正确；缺口发生在解包后清单损坏/不完整的负例，不声称已下载的原ZIP本身损坏。取源遗漏情况下，后续完整bundle检查仍能发现缺文件，不能误报为完整链路静默成功；但fetch自身的“已全部核验后发布source”结论失真。

最小复现（只复制四份元数据，无需模型/Docker）：

```powershell
python test/qa-delivery-b868/reproduce_manifest_001.py --installer <已按bc2取完source的安装器目录> --output <全新QA目录>
```

该QA oracle当前预期退出1，保留产品CLI错误exit0及oracle.json。关闭条件：完整正常包继续通过；empty/漏必需项/实际损坏在普通与source_only路径均拒绝，fetch不发布partial source；不能只增加非空判断而漏掉非空删项。由原集成实现流最小修复后交新精确SHA定向复测，QA未代改产品。

已有效完成（各自范围分别计，不汇成18项/A01–A34）：

- b868 full两包独立确定性重生，精确匹配2388734/2387364字节及交接SHA；全609后端/110前端/114部署逐字节校验，manifest840/842项。
- 真实包内build_native.py构建Linux Go/探针和生产Vue，Dockerfile.native构建自有三镜像。独立项目maas7-b868-c51fdfd0-offline与external分别实际启动；MySQL8.4.7/maas/web healthy，migrate退出0。应用/迁移UID65532、Web UID101；runtime未挂migration/bootstrap/root密码；未借他人运行实例或镜像标签。
- 正常入口显式offline-controlled下Chat/SSE、两真实工具、原批准API、同operation重复POST通过。工具parent known20。此次默认200ms＋127.0.0.1:53713确实见唯一child in_progress后才cancel，最终cancelled/1child/1usage；完整顺序在admitted-cancel-trace.json，不把自然completed算停止成功。同行localhost/慢流5秒事实只作其他环境输入，没有重做自己的已通过取消。
- 应用与MySQL分别重启，原Cookie/admin_id/CSRF仍有效；消息/工具/事件/原child消费hash及内部Key密文hash稳定。generation_requests=4、usage_events=4、usage_daily finalized=4，重复业务GET/verify无新生成或扣量。消息额外独立取全页核hash，不只借原smoke的事件/工具hash。只有本次受控ModelClient执行，真实供应商/付费/GPU为0。
- 默认external空models实际422 model_not_configured，0请求/0消费/0合成Key；offline+external组合配置拒绝。两安装用各自独立配置、卷、端口53713/53714，顺序执行并清理。
- runtime权限10项通过，默认角色精确kernel_runtime/release_reader/agent_session_runtime/product_auth_runtime四项；未消费history/payload/Operations、DDL、全局凭据、管理员策略写均拒绝。真实runtime DSN指向migration入口被拒。直接/默认/继承旧宽角色三负例均使迁移失败，且原错误授权未被产品静默撤销；fixture DBA最后恢复自己的测试角色。
- 四个management DSN字段分别用“不同文件名但同core凭据”均拒绝；重复独立身份也拒绝。四个本地单角色身份可推进到缺Registry的明确拒绝，未连接真实Registry/K8s，不把工厂前置检查当管理目标验收。
- 新toolContext 3顶层/6叶通过：运行主体/权限/会话/run/step/call/原request/trace/fence/实际deadline绑定；caller伪上下文被覆盖、工具参数不能伪造；不同call幂等键不同、completed重放不执行。原注册/批准路径下受影响write duration/timeout/cancel unknown屏障及未批准取消保持。
- bc2两份认证小包193530/191904字节及SHA正确；分别实际从固定GitHub URL下载，834源文件/四锁全部校验后形成source；正常完整bundle manifest847/849通过。bc2 full模式也独立生成并验证609/110/115。获取程序负例使用已捕获的同一真实下载字节，不重复网络，也不执行清单中的命令。
- b868空runs/pendingCommand错误verify exit0已独立保留。bc2前置修复4负2正通过：负例在网络/认证前拒绝；旧完整/取消record可通过前置门禁，正例在首个网络哨兵处停止，不称新客户端完整网络跑通过。后续业务GET逻辑按不变源码映射复用b868实际完成记录；不重复模型生成。

另有非本段第二交付阻塞的待裁定观察：仅将已存在、数据完整的002状态从Applied改为Applying，普通serve仍healthy/ready。原件schema002-marker-observation.json含SQL状态、实际one-off和ready探针exit0；validateSchema只核version1。物理移走offline表后则准确失败，恢复表/状态后原4/4业务行保持。该marker-only fixture需架构确认启动契约，未计迁移门禁通过，也不声称导致计量错误或文件回退。

环境/失败记录：Windows Go1.26/Node22.23.4，2并发；npm首轮ECONNRESET及生成目录清理警告保留。只读按lockfile SHA512复制161个已有公共tarball到自有短临时缓存，25个其他平台optional缺失；离线补构建成功。长缓存路径、取源前误判manifest中source尚不存在属于QA准备问题，原件保留后修正。002 Applying负例因产品持续serve而超时，实际健康证据已采集再精确停止该自有one-off；不是空输出登记失败。所有自有project/卷/网络/镜像标签已清理，临时Secret已删除，未停止共享WSL、未动他人容器/卷/缓存内容。

可复现运行命令为包内README的configure→build_native→独立Compose build/up→smoke create/verify及smoke-product-cancel。实际完整argv/环境、原ID、hash、SSE/HTTP轨迹及失败输入在证据包；reproduce_manifest_001.py提供独立最小失败入口。当前不签收最终完整性保护；无真实管理目标、真实供应商/Higress或目标K8s安装证据，缺这些不是本段额外阻塞。浏览器页面不在本轮独立范围。主单与MAAS-7保持in_progress，一次回主单处理唯一完整性缺口。
