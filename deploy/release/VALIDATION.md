本次安装候选验证范围
====================

准确源码、四锁、镜像版本以包根 VERSION.json 为准。以下分项记录，不将健康或作者历史结果代替模型闭环。

已实际完成：Go1.26.0普通cmd/maas-service构建、Node22.23.4生产Vue、应用/Web/迁移三镜像构建；独立Compose四服务启动，MySQL/Go/Web健康、迁移正常退出；同一Cookie/管理员/CSRF跨应用与MySQL重启保留、退出401；正式站点只读浏览器3项/0页面错误/0 Run POST；安装器四项回归通过。初轮七项SQL检查是历史候选范围；权限审查后移除未消费的metadata/payload/Operations三角色，新增三项拒绝检查及旧角色故障关闭门槛，最终回归结果见任务原始证据。

K8s使用kubeconform模块v0.7.0及K8s1.36.0公开schema做静态校验。没有获准自有隔离集群，未执行目标kubectl安装/重启，不能据静态结果宣称集群应用通过。

真实模型未验：external-api默认models为空；原正式上游仅text-v1，tools-v1未批准/装配时拒绝。已接入后端f990576的同正常入口显式offline-controlled profile、002迁移与独立管理工厂；离线Chat/两工具/批准/原子用量及重启回放以本轮同组合实际证据单列，不冒充真实模型结论。管理默认关闭，目标Registry/K8s/四独立身份的实际装配未验。未使用真实供应商/Higress/Secret、GPU、付费或目标发布。

首次纯容器尝试存在镜像short-read/超时及npm ECONNRESET，不计通过；旧Node22.12不满足当前锁依赖要求，验证路径使用22.23.4。本机构建完整source再用Dockerfile.native构建运行镜像；纯容器Dockerfile保留，但当前网络失败不算成功。

离线安装必须显式选择profile并使用专属MySQL；不能用agentcontrolled文件会话入口或空models健康充当Chat/Agent完成。活跃取消/未知工具恢复、AR-R01/R02独立关闭及全A01–A34仍沿原责任验证，作者SQL结果不自动外推为本轮容器或独立验收。

回滚保留MySQL业务表、原request/usage/held、消息/事件/checkpoint及原安装身份/Secret；应用回滚只在schema前向兼容下进行，不清历史、重结算或自动重放未知执行。原始日志/命令在本轮任务附件；包完整性不构成模型验收。
