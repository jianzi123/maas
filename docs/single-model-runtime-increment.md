# 单模型运行接点：本轮最小增量

基线为统一分支8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a，本轮从干净工作树建立agent/MAAS-3-single-model-runtime-20261116，旧f445分支/缓存/过期工作台保留。未重拼旧候选，未重启旧URL。

新增kernel.OpenRelayTLS(core, RelayTLSFiles)：固定安装侧Higress HTTPS端点、独立CA与客户端证书文件，显式连接/响应头时限和字节/行上限。复用原NewRelay/Forward，不建立第二条准入或结算；不从请求/profile接收供应商URL。禁环境代理、拒绝重定向；证书输入最多64KiB、校验配对和有效期，错误不回显路径/秘密。Close只清空空闲连接，不修改在途请求的终态所有权。响应头时限不截断已经开始的流体，原Forward仍按原请求context/硬截止、receipt-before-forward与唯一结算执行。

调用位置示例（安装者必须提供批准文件与限值，没有隐式默认值）：

```go
relay, err := kernel.OpenRelayTLS(core, kernel.RelayTLSFiles{
 Endpoint: approvedHigressURL, CAFile: caPath,
 CertificateFile: clientCertificatePath, KeyFile: clientKeyPath,
 DialTimeout: approvedDialTimeout, HeaderTimeout: approvedHeaderTimeout,
 MaxBytes: approvedResponseBytes, MaxLine: approvedSSELineBytes,
})
// err != nil: fail closed; success: use existing relay.Forward only after
// original profile/ticket/plan/admission bindings are available.
if err != nil { return err }
defer relay.Close()
```

本轮测试是真实本地TLS客户端/服务端、临时签名证书及受控HTTP/SSE；不是Higress实现，也没有数据库或真实上游，不能替代原SQL/终态测试。运行：在已配置Go1.26缓存环境执行go test ./internal/kernel -run '^TestRelayTLSRuntime$' -count=1 -v。不重复R1–R3/UI16/Delete或全仓QA。

| 接点 | 当前事实 / 下一步 |
| --- | --- |
| Relay TLS工厂 | 本轮新增，可实际构造原Relay并验证双向认证/流式传输；尚无生产入口消费，不能据工厂存在放行 |
| 发布/Key/预算/原ID查询 | 已有内核、control-api管理入口和OpenPublisher；保持统一基线，实现不重做 |
| Secret | gateway.SecretAgent + KubernetesSecretReader已有真实K8s读取；Higress认证lookup调用方/部署身份未装配 |
| H1/H4 | gateway.Authorizer尚无binary注册；固定来源AI Proxy插件/票据通道仍需批准Higress补丁与实例身份 |
| H2/H3 | receipt验证库存在，真实transport sealed/no-send和全副本应用/boot生产者缺失，禁止以四bool或fixture替代 |
| validation | 原candidate intent/receipt账本保留；获准专用Key/额度、来源adapter、受保护执行者与实例覆盖仍缺 |
| 生产入口 | cmd/control-api仍只暴露受控管理；cmd/operator仍缺真实依赖。新TLS工厂不是完整发布/推理装配 |

跨仓范围继续引用docs/higress-minimal-patch-scope.md：Higress v2.2.5 peeled 4deae1dd3b4cb2707273748985e55bef28e747d1及其Envoy/Proxy gitlink；H1 ai-proxy、H4 ext-auth、H2 Envoy router/upstream_request/conn_manager、H3实例agent。此次未重新核验远端版本、写入第二仓库或构建插件，生产版本选择与补丁承载由Mika协调。

批准输入：已读MAAS-2本批交接与MAAS-9 v0.6两卡登记，DeepSeek优先不是具体模型调用批准。精确model/模式/固定端点及source_id、adapter revision和progress/final/error/取消/有界终止、可信I_up/O_up与缓存/reasoning维度、价表版本/币种/精度/有效期、预算/窗口/调用额度及停止条件仍需MAAS-9/2与成员确认。Secret渠道/引用、TLS身份/CA、Higress实际版本及目标权限由MAAS-8/成员提供；跨仓范围由Mika协调。缺失分别阻塞真实发包、可信最终用量结算、candidate验证和Callable，不阻塞本轮文件工厂及本地组件验证。未知actual=null、原held与slot分离、固定来源不回退不变。

本轮没有实际模型/付费/GPU调用、目标部署、生产Secret或持久演示服务，旧URL已过期。后续优先在批准来源和H1–H4实际生产者齐备后，将此工厂接入同一受保护入口，并在独立临时组件上验证原ID终态与非空权威用量；不能先开放普通Higress再补账务证据。