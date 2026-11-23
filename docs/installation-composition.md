# 最小安装组合根及Higress局部补丁

本增量依赖PR #14的00a3e62；保持原PR #14和其独立QA固定SHA不动，新增隔离依赖分支。统一目标仍为agent/MAAS-10-offline-metrics，未重拼旧前端、未合并其他候选。

## 实际配置消费

internal/installation.LoadConfig严格解码安装JSON，拒绝重复字段、未知字段、附加JSON和超过64KiB输入。Config仅含cluster、publisher DSN文件、签名密钥文件、Kid/SignerOwner/Instance/Epoch、原RelayTLSFiles和CredentialBinding安全引用，无Ready开关或内联Secret值。time.Duration的JSON值按Go纳秒单位，必须显式提供；不填生产默认。

installation.Open(ctx, config, Dependencies)要求既有kernel.Store、真实Registry、SecretReader及私有peer认证回调。Registry在打开任何工厂前核对cluster/instance/kid/signerOwner/epoch，每次Authorizer请求再次检查撤销。Credentials必须非空且匹配instance/epoch；原SecretAgent验证完整引用。DSN/密钥从文件有界读取，错误脱敏；实际调用原OpenRelayTLS与OpenPublisher，publisher启用原事务内完成hook，失败清理已打开连接。原Core仍负责profile/request/publication/price/最终性绑定和唯一准入结算，不复制账本。

Runtime.Authorizer("")构造原serving授权器；Runtime.Authorizer(originalValidationIntentUUID)绑定原candidate用途和耐久intent，由Core.Admit继续核验，未新增validation HTTP协议。只允许安装到获准私有mTLS listener；此包不注册公开路由、不创建服务。Close应在停止私有listener及在途处理后调用，只关闭资源/撤销缓存，不证明上游停止或退款。

cmd/control-api和cmd/operator尚未消费此组合根，因为当前没有真实Registry/H1-H4/validation生产者可注入。不能仅提供任意Check返回nil的实现或测试Peer便将其视为生产就绪。本轮测试替身均在_test.go中；包内无默认Registry或Proofs实现。核心独立DSN/角色、publisher角色及原K8s Secret读取继续复用，未修改SQL权限/迁移。

## 验证与边界

真实临时MySQL完整角色安装+组合根构造：沿原scripts/test-controlled.sh，设置MAAS_TEST_WORKBENCH_IDENTITY=1。它执行TestLocalRuntimeIdentities及TestInstallationComposition，使用原迁移、实际default publisher role、证书/DSN文件、严格JSON加载。未知/重复配置、缺registry、未认证peer、撤销registry、非法candidate intent被拒绝，generation_requests仍0。真实组件是MySQL/角色/工厂/文件读取；registry、SecretReader、peer是测试替身，TLS仅构造，Higress/生产握手/票据成功准入/结算/真实模型未测。本轮不重跑旧R1-R3、UI16、Delete或TLS13项独立QA。

## 仓内版本化补丁

patches/higress/v2.2.5-maas-r1固定Higress v2.2.5标签ff10455、peeled 4deae1dd3b4cb2707273748985e55bef28e747d1；本轮git ls-remote及只读浅取git对象复证。Envoy gitlink为9bd2ded786073d115beb71d0f2ca0afc075e4f4d，Proxy为919836551144ad42c41bbe25597d74c1b9cb8421；ext-auth/ai-proxy两个源码SHA256与原登记一致，manifest保存精确值。未写第二remote/fork、未发布插件。

0001补丁是专用MaaS ext-auth变体：每个选中请求都必须有且仅有一份非空原request_id/票据/计划头；移除MatchRules跳过和FailureModeAllow分支。附纯Go头校验helper及11条正反断言。它仅是H4局部加固，不构成完整H4：可信route/body摘要、签名/用途链、内部头剥除、严格一次attempt等仍按既有清单实施。此变体不能被当成通用stock替换。

应用：python patches/higress/v2.2.5-maas-r1/apply.py --source <固定源目录> --output <不存在的新目录>。脚本先校验选定源及patch摘要，拒绝覆盖/源输出嵌套/符号链接，再复制并git apply --check/apply。可加--build；构建要求完整干净的固定commit/gitlink、TinyGo批准版本及二进制摘要。当前实际结果：选定源应用通过，helper原生Go测试通过；Wasm构建退出失败，明确原因tinygo executable unavailable，批准版本/digest亦未提供。没有Wasm产物或Envoy运行验证，不能把apply-check/helper测试记为插件构建通过。GitHub公开API曾403限流，gitlink改用只读Git对象复证。

H1动态credential lookup调用方/本地认证通道本轮尚未实现，ai-proxy仅作为固定来源输入核对；H2/H3 sealed/attempt/active、全副本boot生产者仍缺。源码补丁承载已落仓内，下一段优先H1调用方与H4完整可信metadata，H2/H3分阶段。MAAS-9/2收敛真实来源/最终性输入，MAAS-8/成员补TLS身份/安全Secret引用/工具链，Mika归并scope；真实Secret、模型/付费、目标部署授权未扩大。生产Callable和A01-A34仍未通过，旧工作台URL不作在线事实。