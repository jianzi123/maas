固定组合879a的有界独立QA

本段通过：AR-R01/R02在受控后端范围关闭；真实MySQL SessionStore/账本/身份/Installation与正常maas-service空模型恢复范围通过。浏览器、最终Compose/K8s包、真实上游及完整18项/A01–A34均未整体签收。MAAS-7和MAAS-21继续in_progress。

产品固定head 879a7aa489eb347661a889a969ea2586b5f74cbb，代码07b00d85796da273567c377c9d232f8bf08c3373，正式服务c96e598ba245aeb02b418a6d601e036e892717d1，UI f939f3b5e7eda20938c367f9a9ee3e34c43a81a4。AR修复a4c1347与安装/TLS前置祖先保留。执行时155个原产品/契约/元数据文件逐字节不变，仅新增QA文件。后续fa81e175c0c6be832ba90c89310147b32f8c17ca已只读核对internal/及cmd/零差异；本次未切换到它，也不外推新UI验证。

|范围|本轮实际独立运行|
|---|---|
|保留的QA oracle＋新增分页边界|Windows 5顶层/20个唯一叶通过；0/98/100/102历史，中文增量，旧页410且snapshot_required=true/retryable=false，丢旧页/旧resume_cursor后全量GET与新cursor恢复；稳定页200、伪造400；终态/编辑失效；步骤/工具页分别稳定分页、410后完整重取，精确3step/2call，无丢重、GET不写/不新增模型|
|原AR1/ARReview回归|本次重新执行AR1 14顶层/26 pass事件（22叶），ARReview 4顶层/23 pass事件（19叶）。与独立oracle有交集，不能累计成全18项通过|
|工具终态|纯/读/经原注册器与批准API的受控写工具，分别duration/tool_timeout/cancel；Run limit_reached/duration_limit与合法ToolCall failed/cancelled分开；已派发attempt1、未批准取消0；写结果不明保持unknown/needs_confirmation，重复Drive不重放；Run/Step/ToolCall/Event按原严格Schema读取|
|旧attempt兼容|Linux 1顶层/5叶通过；旧executing/completed/failed/unknown推断attempt1，模糊cancelled保守0；这是旧记录投影夹具，不等于确认外部副作用|
|MySQL SQL|5个顶层通过：原SessionStore命令重开/幂等/双服务claim1，原known账本1，新增mixed known/unknown账本1，LocalRuntimeIdentities/Installation2。没有skip/空匹配成绩。SessionStore证据来自sql-attempt1；其余来自稳定PID1 MySQL的sql-attempt2|
|混合账本|真实原Admit/Finalize/MySQLSessionStore；两child/两usage/汇总各一次。known19、held140、金额held520000、inflight0，parent aggregation_complete=false；重新Submit及GET不增加模型、终态或汇总。模型/H1–H4/rate为受控适配，计算器是真实安全工具|
|正式入口|无agentcontrolled/localworkbench标签的maas-service实际运行；缺迁移serve退出1/product_schema_not_ready；migrate两次0；DML默认角色当前身份实际生效，CREATE返回1142；runtime调用migrate退出1；正常登录/未登录401/无Origin403/无CSRF403/空models创建422 model_not_configured|
|正常MySQL恢复|使用标准net/http对自有容器loopback真实请求；同一Cookie/CSRF/admin_id经过应用重启及MySQL重启恢复。DB重启后原进程退出0，重新start恢复，部署应考虑Always/unless-stopped而非只on-failure。第二owner退出1/runtime_already_owned；正式调度当前单活，不签多活/HA|
|旧在途原ID|通过正常AR命令及MySQLStore准备明确标注的model_inflight崩溃检查点夹具；serve恢复needs_confirmation，原session/run/child不变。GET及两个重启前后revision/请求/用量计数一致，新增generation_requests=0、usage_events=0。不是此前真实上游派发或未知外部副作用的证明|

混合账本样本：parent 10ca37ba-097b-42d2-a7d8-845bbcef198b，child c0ebe358-55b3-4ee1-963e-46b324c2f5b7 / f1324aa5-5e07-4610-85e4-57df1f3aca95。正式恢复样本：session 8f88918b-738b-57d9-afca-a27a46ed8428，run 39b050b2-d21d-4c66-9adf-13d621e6a9d4，child cb01ccac-3104-45b7-bf27-751f93bcca56。准确响应/GET-POST轨迹见formal-results.json，Cookie/CSRF只存hash。

环境为Windows Go1.26.0、GOMAXPROCS=2/-p=2、自有GOCACHE、现有离线模块缓存；Linux/amd64 CGO_ENABLED=0交叉编译。Docker29.9.2、MySQL8.0.44与Alpine均为现有镜像且按ID固定，详见results.json与原始environment.json。MySQL无网络、专属数据/socket卷；正式API也在自有隔离网络，最后探针仅本容器loopback，无宿主端口。未连接他人容器/卷、未重启共享WSL、未删除/重置他人缓存。所有23个自有资源清理记录为removed=true，最终容器/卷/网络前缀查询为空，临时凭据文件已删除。真实上游/付费/GPU执行均0，受控ModelClient按用例执行。

保留的失败与修正：

- 旧19e的2过2失、原a4c有效执行0、原未执行oracle原字节保留在history与original-*；它们不改为当前成绩。
- 沙箱启动助手1223、首次fetch early EOF、无测试事件的Go尝试均记录环境阶段。原准备稿存在未定义deltas与未使用cursor日志变量，修正仅日志且保留原稿；首次build-fail没有产品用例执行。
- 改变overlay/缓存/vet参数的诊断不作单一因果归因。Windows有效运行明确-vet=off；原Linux交叉编译记录返回0。一次重复构建入口被防覆盖检查拦截，未重复运行用例，不声明整仓vet通过。
- sql-attempt1在临时初始化socket切换期间后续用例连不上，保留原FAIL文本，判为连接阶段未验；PID1+ping就绪后仅补未有效执行用例。已通过SessionStore和legacy未重跑。
- sql-attempt2宿主探测未就绪但进程running/OOM=false；sql-attempt3 QA探针命名冲突；sql-attempt4 nc返回登录503。均保留。标准net/http在相同产品源码/DML权限下全部通过；nc半关闭连接可能触发request context取消是定位推断，不登记通用登录缺陷，也不抹除503原件。
- 一次临时汇总读取误用Windows默认编码，修正为UTF-8；日志原件未改。最终证据不含原始Cookie、CSRF或凭据。

复现（在本QA提交的仓库；已批准且预先准备Go1.26模块缓存、mysql:8.0.44和Alpine镜像；不自动拉镜像/调用模型）：

```powershell
$env:MAAS_QA_GO_ROOT='<Go1.26根目录>'
$env:MAAS_QA_GOMODCACHE='<已准备模块缓存>'
$env:MAAS_QA_OUT='<全新绝对输出目录>'
python test/qa-chat-agent/composition-879a/prepare.py
python test/qa-chat-agent/composition-879a/run_go.py portable-corrected
python test/qa-chat-agent/composition-879a/run_go.py agent
python test/qa-chat-agent/composition-879a/run_go.py kernel
python test/qa-chat-agent/composition-879a/run_go.py installation
python test/qa-chat-agent/composition-879a/run_go.py service
python test/qa-chat-agent/composition-879a/run_go.py probe
python test/qa-chat-agent/composition-879a/run_sql.py
```

正式重放入口是本轮实际脚本的参数化副本，新增入口不另计一次执行。portable选择器限定已签的5个QA顶层；legacy五叶在Linux阶段运行。实际原命令/环境、所有阶段stdout/stderr、每次失败及清理记录在证据包executed-tools与raw-results；所用二进制hash在results.json，二进制可按上述固定源码重建。原脚本本轮复用了已通过阶段，fresh入口默认不复用SQL，避免无证据skip。

局限与下一步：正常产品仍为空models，仅证明初始化/认证/持久读取和明确夹具恢复，完整Chat/Agent工具/消费同正常配置的受控profile尚缺；管理Releases/Revisions装配缺口沿原后端处理。Installation的registry/SecretReader/peer、模型与rate为测试适配，不代替真实Higress/供应商。文件Store回归只属显式夹具，正常serve源码/实测均使用MySQL且缺迁移失败关闭，无SQLite/文件/内存回退。后续最终前后端及两套包准确head到达后，按差异补浏览器/代理/Compose/K8s smoke。现有原18行与A01–A34保留未验边界，不累计历史总数作整体验收。
