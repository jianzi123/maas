本安装候选的验证范围
====================

准确源码、四锁、镜像标签及逐文件来源以包根VERSION.json、SOURCE.sha256.json和MANIFEST.sha256.json为准。本页更新到2026-11-27恢复截点；**QA-MIG-SHAPE-001/P1尚未关闭，不能作为生产就绪安装签收。**

本轮PR21纳入原PR11/12/20/22/24/25，保留统一4402/d27及作者祖先。正式受保护tools-v1桥已实现，需新批准Profile.Tools/UsagePolicy、deepseek-chat-tools/1/non-thinking和显式ledger.diagnostics，不是仅填供应商Key即可调用。默认external-api空models准确拒绝，显式offline-controlled才使用带标记受控模型；业务仍走正常MySQL和唯一账本，不用agentcontrolled文件会话。

组合36d34e2实际通过：正常maas-service构建；Go协议/Agent30顶层124测试及子项；真实MySQL正常HTTP/Cookie/CSRF、受控mTLS、原Admit/Finalize、两个真实工具和第二child（2request/2usage/38Token），非法第二工具0执行且原child正常计量；kernel工具Relay七种完成/参数/缺usage/cache/EOF/错误/取消场景；前端五文件64项、生产build/format。SQL专属容器与卷已清理。这些是集成受控结果，不能替代独立QA或真实供应商/Higress验证。

迁移journal/摘要/取消隔离/维护CLI有集成及独立有效范围，但独立QA固定1f8/e12的50唯一为47过、3失：Applied/hash正确时，缺usage_events、only_terminal唯一索引或retained_release_snapshots仍被Open/checkReady接受；窄身份正常serve缺usage_events仍ready200。原后端正在补必需物理门禁，私有元数据可见性须维持最窄身份，runtime不得DDL/补标/借管理角色。最终修订与原3反例独立签收另列，不能据健康或历史通过关闭P1。

PR25已修R-P01未挂载试用入口、登录bootstrap及旧poll淘汰新open的竞态。旧4402真实Chrome的QA-CHAT-RACE-001失败保留；作者浏览器演示/组合64测试不等于独立关闭。原879 AR-R01/R02、d27 MANIFEST完整性关闭按原SHA保留，不相加成全仓通过。

上一里程碑已有包内原生构建＋Dockerfile.native三镜像、独立Compose四服务、显式离线Chat/两工具/批准/已准入取消、应用/MySQL重启、窄权限及浏览器原件；这些是各旧SHA结果，不声称新组合已重跑Compose升级/恢复。纯多阶段原npm ECONNRESET/镜像short-read/超时保留；成功路径是Go1.26.0/Node22.23.4包内原生构建后再构建运行镜像，无预发布镜像可用性承诺。

原生K8s已有专属kind/kubeconfig/namespace、迁移前停scheduler、Applied检查及保留Secret/PVC的install/upgrade/verify/stop脚本；19夹具和旧14资源schema通过，实际安装/PVC/重启未签收。原运维续办runtime_offline、重试未启动，已恢复现场检查；最新621140KiB低于新增节点测试预设4096MiB，不降低门槛或停止他人服务。静态/schema/计划不等于实装。

独立publisher已受控验证MySQL/mTLS/UID65532进程、幂等/冲突/权限拒绝/事务回滚，live204/ready503准确表示缺生产证明。管理四身份虽接线，真实目标未验；Operator仍review/nil生产适配，Control读侧、Inventory/BundleCatalog和真实receipt/validation等未补齐。不因此声称完整发布成功。

真实供应商/生产Higress、管理目标、目标集群、付费/GPU及整体A01–A34本轮未验。新包构建/校验、准确ref及后续独立签收以主单原件为准。工具接口见source/docs/agent-tool-interface.md，演示见source/console/docs/demo-15min.md，功能表与完整问题/负责人见source/docs/delivery-feature-matrix.md和next-release-integration.md。

升级/回滚保留MySQL、原request/usage/held、会话/事件/checkpoint及安装身份/Secret；停旧写者后迁移，仅schema兼容时换应用镜像。不清库、重结算、自动重放未知执行或serve自动DDL。
