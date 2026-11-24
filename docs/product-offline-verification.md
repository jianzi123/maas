正常服务离线profile与管理挂载验证（2026-11-23）
==============================================

沿原6732正式程序新增opt-in offline_controlled及可选management挂载。仍是同一maas-service、同一MySQLSessionStore、同一登录Cookie/CSRF/稳定principal与原Agent循环；没有新增文件/内存/SQLite回退，也没有把agentcontrolled入口放进部署。

最终专属Unix-socket MySQL8.4.7选择器`^TestProductOffline|^TestProductManagement`实际4个顶层用例通过，0断言失败、0 skip。模型与rate/publication/closure证据是明确受控适配；原Admit/Finalize、MySQL、工具、授权/审批、HTTP、事件/checkpoint是真实现。两真实工具输出42及当前scope目录；原批准API后第二child完成，真实MySQL为2请求/2唯一终态，父known_tokens=20。随后通过相同正常API停止一个已准入child，Run取消完成，最终3请求/3usage。应用关闭重开后同Cookie/原事件字节不变，回放新增请求和扣量为0。未执行真实供应商、真实Higress、付费或目标集群。

管理源码缺口已核实：正常构造时Releases/Revisions原为nil。新wireManagement复用原history.Reader（独立PayloadDB/访问域）、Operations、management.Service、OpenPublisher和明确Kubernetes客户端；每个DSN非root且不与core/其他投影共用户名，CURRENT_ROLE必须恰为原最窄单角色，不接受DEFAULT ROLE ALL组合。SQL用例验证错误地把core DSN用于管理时启动拒绝；完整合法角色＋真实K8s管理请求尚待最终安装组合，不将此拒绝用例称全管理通过。management未启用时页面/API故障关闭依旧准确标明。

首次离线模型/工具/审批/重启断言已通过，但harness尾部在运行期间编辑后出现EOF引号解析失败（整体exit2），原始JSONL保留；当前脚本`bash -n`通过，稳定脚本重新执行离线/管理选择器整体exit0，停止/3child/3usage来自后者。不是把失败exit2改记全绿。原R01/R02独立门槛不因此关闭；最终Compose/MySQL进程重启/浏览器由原MAAS-21/8/5/7按最终同树验证。

构建/vet低并发退出0。例子与命令见product-management-and-offline.md，独立002迁移不修改已发布001。内部受控Key只以AES-GCM加密值放MySQL；旧Key/预算不被重建，其他来源Profile禁止与离线模式混用，受控证据也不批准其他publication/key。默认不开启demo，失败不切换来源。MCP/文件/shell/子Agent等仍未实现，原功能清单保持准确。
