# MaaS Docker Compose 安装包

本包包含完整同版本source、四锁、Dockerfile与安装器，不引用其他工作目录或未发布镜像。VERSION.json给出Git快照/code提交；MANIFEST.sha256.json覆盖全部包内输入。

## 准备与首次安装

验证路径：Linux/已有WSL＋Docker Engine/Compose、Python3.10+、Go1.26.0、Node22.23.4。Node锁依赖最低22.22.2。无GPU要求。首次构建需要获取公开依赖与基础镜像；本包不声称全离线介质。Windows可在PowerShell运行Python/Go/Node构建，在已有WSL运行Docker Compose。

```sh
python -m pip install -r source/deploy/checks/requirements.txt
python source/deploy/release/verify_bundle.py --root .
python source/deploy/release/configure.py --format compose --directory . --port 18080
# 核对config/product.json的origin、agent/ledger安装值，保留同版本公开config/console-config.json。
python source/deploy/release/build_native.py --root .
export MAAS_DOCKERFILE=deploy/release/Dockerfile.native
docker compose --parallel 1 build
docker compose up -d --wait --wait-timeout 300
docker compose ps
```

PowerShell选择构建文件用：`$env:MAAS_DOCKERFILE='deploy/release/Dockerfile.native'`。若已有固定镜像缓存且网络稳定，可省略本机构建步骤，使用默认多阶段Dockerfile；纯容器构建的Go/Node基线在source/deploy/release/Dockerfile。验证报告明确区分两种构建路径，首次网络失败不算启动通过。

打开 http://localhost:18080 ，账号admin；初始密码仅存本地.secrets/migration/maas_bootstrap_password，用自己的编辑器读取，不提交Git/评论/日志。端口可由configure --port选择；反向代理外部URL须同时配置--origin，HTTPS启用secure_cookie。配置默认没有获准模型，页面不得显示可调用或伪造用量；模型接入见下文。

生成器只在新目录生成随机密码/稳定安装ID/pepper/cursor key，不覆盖已有.secrets。保留.env/config/.secrets和MySQL命名卷；同一数据库不能重新随机生成cluster/admin/key值。生成器在.env保存本次独立project名称，可用--project显式选择；第二套安装须用不同COMPOSE_PROJECT_NAME和端口，不能覆盖已有项目。

## 实际组成

mysql:8.4.7独立卷，默认不发布3306；migrate一次执行真正Go迁移和原窄角色模板；maas常驻serve，无DDL且只挂runtime DSN/pepper/cursor；web提供生产Vue和公开JSON，把全部/api及/v1代理到同一个Go。迁移DSN、bootstrap密码不挂常驻应用。就绪检查/单活scheduler保证与MySQL一致，replicas=1，更新短时停机，不宣称无缝多活。

当前核心账户仅授kernel_runtime、release_reader、agent_session_runtime、product_auth_runtime四角色。未消费的history/payload/Operations/publisher不预授给核心；后续正式管理接线需各自独立DSN/Secret，不能回退core。旧安装如存在其他直接/default/继承角色，迁移拒绝并提示DBA审查，不自动撤权或声称只删GRANT即收紧。角色模板的对象权限及外置实例直接授权仍需安装方审计。

MySQL首次初始化在本机约2分钟，安装等待上限5分钟。/healthz是Web存活，/readyz转发到Go检查数据库/所有权；ready不等于模型Callable。SSE禁缓冲，代理75秒超时覆盖当前后端30秒响应窗口；Cookie/CSRF/If-Match/ETag保持同源。日志仅方法/路径/状态/时长/后端请求ID，不记录查询串、消息或凭据。

## 模型与验收

先初始化/登录/读取MySQL，再由安装者填写已有获准publication、平台Key文件及私有Higress TLS/签票输入。实际完整字段见source/config/product.example.json、source/docs/product-service.md；配置的models/gateway从Go严格解析，不直接调用供应商或自动换来源。运行Secret额外文件放.secrets/runtime，按JSON引用/run/secrets下同名文件。正式text-v1与tools-v1独立，未有真实tools批准/适配时准确拒绝。空models启动成功不等于Chat/两工具闭环成功。

本包提供同一正常maas-service/MySQL/唯一账本的显式离线profile，不用agentcontrolled/文件会话。首次安装选择：`python source/deploy/release/configure.py --format compose --directory . --port 18080 --profile offline-controlled`，其余构建/迁移/启动命令相同；默认不传profile仍为external-api且没有获准模型。离线profile与真实models/管理装配互斥，使用专属数据库/身份，不能改已有生产数据库来演示。回答标明离线，模型、rate及来源证明是受限替身；预算、两工具/批准/事件/原child用量在真实MySQL。不调用真实供应商、不承诺生产Ready。

新002迁移初始化加密内部Key，只保存在MySQL；保留pepper/cursor/cluster/卷，勿重建随机安装身份。工具/模型能力及实际消费见source/docs/product-management-and-offline.md。14分钟UI步骤及功能清单保留source/console/docs，最终验证范围以本包VALIDATION.md及任务原始证据为准。

仅在明确启用离线demo模型后：
```sh
python source/deploy/release/smoke.py --base http://localhost:18080 --password-file .secrets/migration/maas_bootstrap_password --offline-demo --limits-file config/console-config.json --phase create --record smoke-record.json --output smoke-create.json
docker compose restart maas mysql
docker compose up -d --wait --wait-timeout 300
python source/deploy/release/smoke.py --base http://localhost:18080 --password-file .secrets/migration/maas_bootstrap_password --offline-demo --phase verify --record smoke-record.json --output smoke-restart.json
```

create只在显式demo配置使用，真实供应商/付费调用需对应批准。verify只GET原记录，不自动重新生成。没有模型时smoke应拒绝而非填假数据。

也可运行后端原验收器：`python source/scripts/smoke-product-offline.py --url http://localhost:18080 --config config/product.json --password-file .secrets/migration/maas_bootstrap_password --approve-safe-tools --record backend-offline-record.json`；重启后用相同前三个参数加`--verify-record backend-offline-record.json`只读核对。它仅支持受控loopback，不用于真实模型。

管理页/API默认明确不可用。启用须按source/docs/product-management-and-offline.md配置真实management字段及四条独立DSN（history/payload/operations/publisher）、单角色账号、批准Registry/kubeconfig/namespace/domain。沿原角色模板由DBA建独立身份，将各DSN/证书文件加入.secrets/runtime并仅按实际路径挂载，Registry可额外只读挂载。不要改成core DSN或把四角色授给core；无目标K8s/CRD/Operator/Higress输入保持关闭，不据健康宣称管理可用。

## 停止、升级、恢复与排障

- 停止保留数据：docker compose down（不带-v），保留卷和本地Secret；临时demo结束同样停止自有project，不停他人容器。
- 升级先备份MySQL和Secret/安装身份，保留原request/usage/unknown-held、Agent消息/事件/checkpoint；解压新版本到新目录并安全沿用旧config/.env/.secrets，再构建新source版本。停止旧应用→执行新迁移→整体up新maas/web，使代理重新解析新容器地址。旧迁移checksum冲突失败关闭，不改旧值或清库。
- 新迁移容器失败时只查该容器日志，maas不启动；运行身份不能CREATE/ALTER表。普通回滚只换兼容镜像，数据迁移向前处理，不down migration、不删原历史或未知占用。
- 备份：使用MySQL受限备份/迁移身份做一致快照，完整保留所有maas表，Secret另走受保护备份；保留期/RPO/RTO由安装者批准，不内置TTL删除。恢复到隔离实例先确认单写/迁移与原身份，再查原ID，不能重放不确定模型或工具写入。
- 健康失败：docker compose logs --tail 100 mysql migrate maas web。浏览器401/403先核origin与实际URL一致、凭证与CSRF；502查Go就绪/代理地址。无模型或tools_protocol_unavailable按能力限制处理，不改为开发bootstrap。
- MySQL重启使原调度锁失效，Go应退出并按restart策略恢复；历史只读回放不产生新usage。未知在途进入needs_confirmation，不把容器消失当作资源已安全释放。

## 外置MySQL

使用同版本MySQL8.4、已授权的maas数据库和安装账号；首次版本以maas schema/3306为约定。用configure --database-host <DNS> --root-password-file <受保护文件>生成对应DSN，并使用compose.external.yaml，内部mysql服务不会启动。若由DBA预置运行账号/最窄角色，按source角色脚本审定，设置MAAS_INSTALL_PROVISION_ROLES=0并用批准DSN替换生成文件；不能把全局同名maas角色脚本直接叠加到他人共享实例。私有CA/不同端口/非root安装账号按实际DSN和mysql-client.cnf配置，先验证TLS与权限；无明确授权不连接目标环境。

Kubernetes、真实供应商/生产Higress/Secret/付费/公开镜像发布分别按对应批准，不能由本包健康结果推定已验。

### 已准入停止与原ID验证

离线站点启动后可显式运行（只允许loopback、正常MySQL离线profile）：

```sh
python source/scripts/smoke-product-cancel.py --url http://localhost:18080 --password-file .secrets/migration/maas_bootstrap_password --record smoke-cancel.json
```

脚本先读原child的in_progress账本，确认已经准入再发送停止；保存原Run/child和终态/消费hash，不自动重试写。使用同一smoke.py的verify命令、将record换为smoke-cancel.json，可在应用/MySQL重启后只读验证cancelled原记录。不要覆盖已有record去重跑。create默认读取同源console-config.json的实际限额；--limits-file可显式指定同版本公开配置，不回退其他示例币种。