正常服务的管理挂载与显式离线profile
==================================

默认产品仍不启用demo。`config/product.offline.example.json`只供使用者**显式选择**的独立离线安装；它和正式产品使用同一`maas-service migrate/serve`、MySQLSessionStore、身份Cookie/CSRF、原Admit/Finalize/child/usage表，不运行agentcontrolled、不写文件会话、不在任何生产失败时回退demo。

离线配置：`offline_controlled:{enabled:true,require_approval:true,step_delay_ms:200}`，不能与真实models或K8s管理装配混用；数据库不能含其他来源Profile。显示模型名`offline-controlled`，capabilities.approval_state=controlled、回答带“离线受控模型；未调用真实供应商”。text-v1/tools-v1在此模型分别显式实现，不代表正式供应商tools-v1已批准。控模型及其rate/closure/publication证据是**受限合成生产者**，只对固定离线publication/source/key有效；预算、窗口grant、slot、每child请求及唯一终态仍由原Go/MySQL真实执行。不得把此元数据当真实Higress/来源Ready。

迁移新增独立product schema v2，固定内部Key加密保存在MySQL的product_offline_state（使用安装pepper派生AES-GCM），不打印或提供浏览器。重跑迁移不会新建第二Key；seed中断出现孤立Key时故障关闭要求核对，不静默换身份。pepper/cursor/cluster/DB卷须跨重启保留；关闭profile后正常服务不会选择旧离线数据。

演示命令同一正式进程：

```sh
maas-service migrate --config /etc/maas/product.offline.json
maas-service serve --config /etc/maas/product.offline.json
```

完成原/admin登录后选择offline-controlled：Chat会流出带受控前缀的中文/emoji；Agent提示“计算6乘7并读取可见模型”，选择原两个工具，模型提出两个真实工具调用。require_approval使真实计算器按策略等待批准，目录保持当前scope只读；审批经原decision_id API，批准后计算42、读取离线目录、结果回填、第二次模型调用完成。step_delay_ms为显式合成延迟，可演示停止/取消及其原child用量。模型合成用量每child为6输入＋4输出，按标记的受控价表结算，不代表供应商真实Token/金额。

按原run读回child_request_ids和usage_groups；HTTP回放/重复命令/重启只查原身份。运行/MySQL重启后历史/工具/审批/原账务都在MySQL，不新调模型或扣量。已在途未知仍needs_confirmation，不能用审批重跑未知。独立最终Compose/浏览器/MySQL进程重启验证不由作者应用重开单例替代。

管理API装配（真实K8s/已有发布链，**不是离线模式**）：在私有product.json显式设置`management.enabled:true`，以及：

```json
{"management":{"enabled":true,"history_dsn_file":"/run/secrets/maas_history_dsn","payload_dsn_file":"/run/secrets/maas_payload_dsn","operations_dsn_file":"/run/secrets/maas_operations_dsn","publisher_dsn_file":"/run/secrets/maas_publisher_dsn","kubeconfig_file":"/run/secrets/maas_kubeconfig","registry_file":"/etc/maas/release-registry.json","namespaces":["approved-namespace"],"authorization_domains":["approved-domain"],"scope_id":"installation-admin"}}
```

这些是安装占位值，不是已批准目标。每个DSN必须是独立非root用户名，不能与core/runtime或其他投影共用；默认角色须分别**恰为**原maas_release_history_reader、maas_history_payload_reader、maas_release_operations_runtime、maas_release_publisher，不能DEFAULT ROLE ALL把私有角色合并。publisher实际通过原OpenPublisher工厂并启用同事务管理完成。原Core＋release_reader边界保持，授权文件/账户由原运维装配，不在serve创建或授予权限。

代码将Revisions接原history.Reader及其独立PayloadDB/访问域，Releases接原management.Service/Operations、原Registry与明确kubeconfig客户端；缺任一输入/角色/范围启动失败，不回退core。Registry沿原control-api的严格格式（原spec/resolution/授权域），不制造Ready/真实凭据。K8s已有ModelRelease CRD、Kubernetes读写权限、Operator/publisher/Higress前置仍需安装者按原批准范围提供；构造客户端不等于已部署这些前置。API用户写入仍由共享登录/CSRF授权。

management默认false时，发布/修订/操作API仍明确不可用；此时仅有持久Chat/API及配置已有publication的入口，**不能宣称全管理闭环恢复**。Compose无需K8s的离线演示也不伪造发布页K8s资源。功能清单、最终演示和包说明须据实际profile/验证结果标注。
