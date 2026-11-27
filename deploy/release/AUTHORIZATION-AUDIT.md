# 安装/升级有效授权前置（FC-M-AUTH-PRE-1）

接合基准是主单冻结cd34c02bdc379f135ca21c216406a00639879193（含eab5d69祖先），不是未锁46181。授权审计、物理形状和页面/工具矩阵分别验收。

本前置在一次性安装镜像内执行，不进入Go运行核心，也不给runtime增加mysql.*读取。自动provision和`MAAS_INSTALL_PROVISION_ROLES=0`两种模式都必须完整审计成功；0仅跳过provision。

## 批准基准

精确账号为`maas_runtime`@`%`，四角色为maas_kernel_runtime、maas_release_reader、maas_agent_session_runtime、maas_product_auth_runtime（host均%）。期望表/列级权利由同树kernel/release/controlapi/agent SQL和独立product-auth-permissions.sql逐项解析；每个输入及安装脚本字节须匹配包内build-sources.lock.json，三个组件code ref一致。输出模板SHA/policy SHA是采集说明，不接受外部audit结果JSON或“audited=true”作为放行条件。

release-permissions.sql中的12对象SHOW VIEW逐字取原后端提交eab5d69eea21e2f098ca1e7ade87ce7d39a5d7d8，遵循架构评论01a21a94/FC-M-META-1；本分支只接该SQL，不平行改形状Go。SHOW VIEW可使固定view定义/definer可见，不能解释为只暴露TABLES/STATISTICS；审计器不读取或向HTTP/日志导出定义，也不补私有SELECT。

比较保留grantee、host、schema/object/column、授权层级、privilege及grant/admin option，不把直接权利并入role权利去重。runtime自身只允许无权限表示USAGE及四角色边。缺权、额外直接权（包括与role重复）、role内容越界、global/schema宽权、动态/PROXY/routine权、grant/admin option、其他host账号、额外/default/继承/mandatory角色均拒绝。未授权的旧grant不自动REVOKE、不删用户/角色、不改密码。

## 实际连接与可见性

只读取原安装Secret内`mysql-client.cnf`、`runtime-client.cnf`及原product配置声明的migration/runtime DSN文件。两client文件须与各自DSN的账号/密码/地址/端口/database绑定，实际runtime新连接必须CURRENT_USER()=maas_runtime@%、无proxy、实例UUID/database及激活四角色一致。查询只用原凭据，无root重试、管理DSN借用、新认证环境变量、login-path或include旁路。

当前采集模型锁定MySQL8.4.7，支持现有显式tcp DSN（parseTime/loc/连接超时参数）及tls=true配VERIFY_IDENTITY；自定义/不安全TLS profile、Unix socket或不可证明等价的客户端编码不自动支持。外置DB若使用这些输入，应交明确合法采集接点后再扩支持，不能换宽身份凑成功。

安装连接需合法读取以下**目标账号/四角色**的授权元数据；程序只SELECT下列命名列，绝不读取authentication_string、User_attributes、认证哈希或dump系统库：

| 表/上下文 | 所需事实 |
|---|---|
| mysql.user | User/Host及8.4.7静态`*_priv`列；检测shadow host与全局权 |
| mysql.db | User/Host/Db及数据库privilege标志 |
| mysql.tables_priv | User/Host/Db/Table_name/Table_priv/Column_priv |
| mysql.columns_priv | User/Host/Db/Table_name/Column_name/Column_priv |
| mysql.global_grants | USER/HOST/PRIV/WITH_GRANT_OPTION |
| mysql.procs_priv | User/Host/Db/Routine_name/Proc_priv |
| mysql.proxies_priv | User/Host/Proxied_user/Proxied_host/With_grant |
| mysql.role_edges/default_roles | 四角色及runtime的完整入边/default信息 |
| 全局/连接只读值 | mandatory_roles、activate_all_roles_on_login、server_uuid、CURRENT_USER/DATABASE/CURRENT_ROLE/proxy_user/VERSION |

具体列定义见audit_runtime_privileges.py中的固定查询。此表是**所需能力说明，不是目标GRANT授权或自动root探测**。缺任一合法可见性/出现partial输出时非零退出，报告scope、目标主体及MySQL错误码，不把空结果当“没有权限”。外置DB迁移身份只拥有DDL不等于能审其他账号；本实现没有窄自省不足时的自动放行，外置接点不具备则保持不支持/失败。DBA审批/提供同版本合法采集途径另按原通道，不把安装凭据挂给运行Pod。

查询在一次只读consistent snapshot中采集，开始/结束实例上下文须一致；维护窗口需排除并发GRANT/DDL。一次审计只证明采集时刻，不能抵抗事后高权限改权或宣称连续防漂移。

## 执行及启动门禁

```sh
python3 /app/audit_runtime_privileges.py --config /etc/maas/migration.json --database maas
```

完整成功才退出0并输出`completeAudit:true`。`--phase precheck`仅允许批准权利尚缺，仍拒既有额外授权；它是provision前保护，不是完整审计通过。migrate.sh始终执行precheck→原migrate→可选provision→完整final。这样旧default异常不会先被SET DEFAULT ROLE改写掉。预供身份仍完整final，缺权由DBA按批准流程修，不由安装器自动扩大。

独立审计器需Python3（仅安装镜像新增Oracle Linux python3标准库），无pip数据库驱动。原mysql客户端已在安装镜像中。源码锁不匹配/解释器或元数据不可用均非零；不能把依赖失败记通过。

Compose正式安装/升级用：

```sh
python source/deploy/release/install_compose.py --file compose.yaml
# 外置DB：--file compose.external.yaml，使用同样原安装凭据。
```

它停止旧maas/web，每次运行新的migrate/audit容器；审计非零不执行候选up，不复用旧completed容器。原始`docker compose`分步命令仅为底层维护接口，不能将跳过此顺序视作完整安装。

原生包用 `python source/deploy/release/install_kubernetes.py --directory . --kubeconfig APPROVED_KUBECONFIG --context APPROVED_CONTEXT --namespace maas`，外置DB加`--external-database`。它包装既有清单，不建集群。自有kind验证的local_verify.py同样每次显式install/upgrade创建新命名迁移Job，拒绝并发/不明前次Job；只在本次Job成功后装应用，旧Complete不能证明本次授权。直接`serve`、人为跳过迁移的primitive YAML、自动容器restart不是独立全effective硬拦或连续防漂移，需列未具备；该运行期切片由原MAAS-20收口，不在本前置扩runtime权限。

控制验证使用无网络/无宿主端口的独立MySQL8.4.7，表/列名从实际GRANT声明生成权限夹具，产品migrator明确为桩。它能验证真实ACL/provision/audit顺序和拒绝后旧授权保留，不能当作真实产品DDL、完整Compose/K8s安装、业务或物理形状通过。首次CURRENT_ROLE二进制JSON串导致正控安全拒绝，已通过源SQL显式UTF8转换修复，旧失败保留。

独立reconcile-product-002是维护命令，不等于安装完成；之后仍须正常migrate/audit再启动。完整物理形状门禁与授权审计分别验收，不以任一通过关闭另一项或生产/真实模型验收。
