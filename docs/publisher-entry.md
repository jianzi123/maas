# Publisher 运行入口与接续边界

本增量从统一基线的 8dbf99e 接续 MAAS-3/11，复用 OpenPublisher、发布存储及原 operation 完成 hook。新增 cmd/publisher 是独立的内部 mTLS 命令服务；它不是完整 Operator 工厂，也不执行模型推理。默认 Operator 不因本增量获得数据库凭证。

## 启动和身份

以 Go 1.26.0 构建，然后使用显式配置文件：

~~~sh
go build -buildvcs=false -o publisher ./cmd/publisher
./publisher -config /approved/private/publisher.json
~~~

配置形状见 config/publisher/publisher.example.json。路径相对配置文件所在目录解析，所有值须由安装/运维批准；样例不能直接作为实际运行输入。未知/重复字段、缺证书、缺 DSN、无界 SQL 超时、非 UTC 连接均拒绝，不从环境或 core/operations 连接回退。启动时不建表、不改权限、不创建用户。

publisher_dsn_file 只含一个 DSN，由预置 Secret/文件安全渠道提供，文件不得进仓库/评论/日志。要求 parseTime=true、loc=UTC（或 Go 驱动默认 UTC）、time_zone=%27%2B00%3A00%27、显式非零 timeout/readTimeout/writeTimeout、禁 multiStatements。Unix socket 需获准的本机隔离；TCP 必须使用验证服务器身份的 TLS，拒绝 false/skip-verify/preferred。OpenPublisher 继续拒绝 root 并要求 CURRENT_ROLE 恰为原 maas_release_publisher，且开启 WithManagementOperations。角色名检查不代替额外直接/继承权限审计，目标 GRANT/DEFAULT ROLE 仍由运维按现行模板配置。

服务端只接受 TLS 1.3、经安装批准 CA 验证的 clientAuth 证书，以及配置中精确匹配的单一 SPIFFE URI。Bearer 平台 Key、头部声称的身份及仅受同 CA 信任的其他角色均不能获得发布权。证书/CA轮换需重新启动；本入口不承诺在线身份撤销或生产身份注册完成。

## 调用链与失败路径

~~~text
原 Operator CommandClient（安装批准的 mTLS 证书）
  -> POST /internal/v1/releases/{cr_uid}/commands
  -> URI 身份 / 路径 UID / 原 ControlCommand 严格校验
  -> OpenPublisher 所持的独立发布连接 + 原完成 hook
  -> 同一 *sql.Tx / guard S / 发布 CAS / command ID+hash
  -> kernel.PublisherKernel 的同事务只读元数据/排空计数
~~~

命令只提交一次：成功 204、身份不符 403、ID/hash 或活动态冲突 409、缺依赖 503；commit ACK 未知为 503 release_commit_unknown。HTTP层不重试，也不换ID。调用方继续沿原 operation/request/command 身份恢复查询；本增量不增公开生成或状态查询接口。响应不回显 DSN、正文、秘密或底层 SQL 错误。

PublisherKernel 没有 core DSN/Key pepper，只暴露原 Kernel 的三个只读接点；所有读取使用传入的发布事务及原窄 SELECT 权限，不另开连接、不修改业务预算/Key/终态/slot。它不装配任何证明生成者：Activate 始终因缺真实证据而拒绝；Prepare/RequestValidation 等未实现路径仍沿原存储返回 DependencyMissing。CloseAdmission/安全 Cleanup 复用原事务约束，不能绕过排空和 UID/inventory 门槛。

GET /healthz 的 204 只表示进程存活；GET /readyz 始终为 503 DependencyMissing。两者同样在 mTLS listener 上，不会因 DB Ping 或非空接口而提升生产 Ready。现有 Chart 未自动装配此服务；本增量不修改其 DSN env 或 deploymentApproved 标记。

## 已有 / 新增 / 尚缺接点

| 接点 | 当前实际入口 | 本增量与剩余门槛 |
|---|---|---|
| Core DSN | cmd/control-api: MAAS_MYSQL_DSN；本地工作台独立 Core | 复用；publisher 不消费它 |
| History / payload / operations | 原三个 MAAS_* 独立 DSN；workbench 五身份安装器 | 复用，未合并权限；publisher 仅获原完成投影读写 |
| Publisher | mysqlstore.OpenPublisher；本地 PublisherDSN 参数 | 新增 cmd/publisher 配置文件入口与实际 mTLS 服务；生产身份/目标批准仍缺 |
| Secret | gateway.KubernetesSecretReader / SecretAgent | 已有受限读取/内存库；插件本地认证通道、真实实例绑定/轮换撤销仍缺，未借用 publisher 取密 |
| Gateway | gateway.Authorizer / Receipt 验证库 | 真实 H1–H4 生产者、实例/boot覆盖及 stock Higress 补丁仍缺 |
| Validation | kernel 的持久 intent/候选准入/唯一结算库 | 原库保留；RequestValidation 调度/安全 Key 引用与真实同链调用仍未装配 |
| Runtime | release.Compile 的 SelfHosted NONDEPLOYABLE 计划 | 未伪造 LWS/SGLang 工厂；准确模型、镜像/权重、模板、placement/完整组容量输入待核定 |

跨仓固定版本、路径与最小补丁清单继续使用 docs/higress-minimal-patch-scope.md，需 Mika 明确承载分支/交付后才能写第二仓库。不能靠普通 Wasm EOF/四个 bool、fixture producer 或新增 HTTP 入口补成真实证明。

## 输入卡的已知记录和具体缺项

MAAS-12 v1.9.1 是交接清单，不是执行配置。已复用统一树的原内核、OpenPublisher/五身份及 MAAS-9 a7b6564 的三份 pending profile；没有把“已有文档/向量”改成批准。

- EXT-06：本增量交付 publisher 命令入口、独立 DSN、原事务/角色及受控运行证据；gateway/Secret/validation 工厂和权威非空用量仍 pending。
- EXT-01/02：由 MAAS-9/成员核定精确模型/站点/固定 endpoint 和批准的完整计费上界、progress/final/终止语义。现有 profile 禁执行，不用文档型号或干净 EOF 代替批准。
- EXT-03/04：由 MAAS-8/成员提供安全 Secret 引用、验证 Key/预算/额度、币种及价表版本/窗口/停止条件的批准记录。这里只消费非秘密配置，未填测试 TST 价格或默认额度。
- EXT-05：由 MAAS-8 与后端核准目标环境、路由/插件 digest、TLS/身份、实际接流实例 boot 和验证权限。当前缺真实生效/停止证据，不能真实调用。
- SELF-01–04：沿 MAAS-9/8 原职责核实际模型/许可/既有权重、tokenizer/template、引擎镜像及完整 LWS 组 placement/余量和目标动作。已有本地 GPU 研究授权不因此改变。
- SELF-05/06：同一发布/准入/计量和真实私有推理、生命周期及安装恢复证据仍按新候选交原 QA；受控 SQL/HTTP 结果不替代它们。

上述是本轮核对到的批准缺口，不声称整个工作区不存在其他记录。收到准确任务号/批准引用后复用，不索取 Key 原值、不重复确认九块范围。

## 验证与复现

~~~sh
go test ./internal/publisher -count=1 -v
go vet ./internal/publisher ./cmd/publisher ./internal/kernel
go build -buildvcs=false ./cmd/publisher
~~~

Windows 默认运行真实临时 TLS/HTTP测试；无专用 MySQL socket 时明确跳过数据库组。Linux 实测前交叉编译以下两个程序到当前仓库 artifacts（Windows 设置 GOOS=linux/GOARCH=amd64；Linux无需设置）：

~~~sh
go test -c -o artifacts/publisher-linux.test ./internal/publisher
go build -buildvcs=false -o artifacts/publisher-linux ./cmd/publisher
MAAS_TEST_MYSQL_BASEDIR=/approved/portable/mysql \
MAAS_TEST_MYSQL_LIB=/approved/portable/lib \
bash scripts/test-publisher.sh
~~~

脚本只读批准工具目录，创建自己的无网络临时 MySQL、随机 schema/用户与临时 TLS 证书；执行真实 mTLS -> store -> SQL、缺证据 Activate 拒绝、原 command 重复/冲突、最窄角色拒绝、完成 hook 权限失败整笔回滚、连接重开读回，以及实际 publisher 二进制 healthz/readyz/命令/退出。最终收集子进程并清理自有数据；不复跑 UI16、GPU 或既有全仓 QA。

ACK 未知 HTTP 分支使用明确注入错误验证单次调用；原真实 commit 后 ACK 丢失属于已有独立范围。本轮连接重开不等于 MySQL 崩溃/HA、证书撤销或目标网络故障验收。原始日志随任务交付，未把测试 profile/身份当生产事实。
