# Higress 跨仓最小补丁范围（只读核对，待 Mika 协调）

候选仓库 `https://github.com/higress-group/higress`，tag v2.2.5：tag对象 `ff104552c04c486e5c4c535b6344be8a47187484`，peeled commit **`4deae1dd3b4cb2707273748985e55bef28e747d1`**。本轮通过git ls-remote及精确commit的raw源码只读核对，没有checkout/写入该仓库、构建或发布插件。

该commit gitlink：`envoy/envoy` → `higress-group/envoy` **`9bd2ded786073d115beb71d0f2ca0afc075e4f4d`**；`istio/proxy` → `higress-group/proxy` **`919836551144ad42c41bbe25597d74c1b9cb8421`**。不能用.gitmodules里的分支名替代这些提交，也未宣称某目标部署正运行此组合。

| 接点 | 精确源码入口与最小改动 | 验证清单 |
| --- | --- | --- |
| H1 | Higress上述commit的 `plugins/wasm-go/extensions/ai-proxy/main.go`、`config/config.go`、`provider/openai.go`。加受限异步credential-provider lookup，只接受publication/opaque handle；对接本仓SecretAgent/KubernetesSecretReader。移除秘密配置/错误体日志可能路径，禁止按未批准token failover；不把SecretRef冒充stock字段 | 同Pod本地认证/隔离、UID/RV/namespace绑定、轮换与重启找不到旧版时拒绝、未授权handle拒绝、正文不进CRD/ConfigMap/Helm/日志、lookup失败不发上游 |
| H4 | `plugins/wasm-go/extensions/ext-auth/main.go` 及同目录配置；AI Proxy实际请求处理入口。固定可信route metadata/body摘要、v3及候选用途，剥除内部头；禁retry/hedge/redirect/跨源fallback，配置真实硬流时限 | 重复/伪造头、错route/host/body/cap/price、公开validation、签名轮换/禁用、超期/暂停恢复晚发包、一次ext-auth和一次上游attempt；Core提交未知不得放行 |
| H2 | Envoy上述gitlink的 `source/common/router/router.cc`、`source/common/router/upstream_request.cc`、`source/common/http/conn_manager_impl.cc`。受限transport状态机记录attempt数，封闭排队/重试与活跃流，关闭所有可恢复发送路径后才能sealed；独立目的reporter签发原协议证据，不以Wasm EOF/普通5xx推断 | no-send须attempt=0/active=0/sealed且永不能恢复；transport-closed attempt=1，精确request/ticket/instance/epoch/route绑定；取消/截止/实例暂停恢复、ACK未知、旧证据和slot复用；生成停止/容量/财务held分别取证 |
| H3 | Higress实例agent新增有效xDS/RDS/插件/listener/credential代际观测及本地签名出口；复用本仓Receipt验证库，但它不是生产者。agent注册/撤销/全服务副本集由安装身份/registry接合 | 新副本未应用、错digest/epoch/listener、凭证RV漂移、旧回执、过期/撤销、全副本覆盖；缺实例身份/机制版本不得以PodReady/Ping代替 |

已读上述文件与源码摘要归档于本轮只读manifest。Higress `main.go` SHA256为`4de727e1e6ec918dffd27867520c0aafec345bfd3ba93a0b06495a6f63e0441f`；ext-auth main为`884ace2733069e63edb02d9fdeaf425f06956cf9f742abcf4286c8b4f3acf0e8`。Envoy router/upstream_request/conn_manager文件已在精确gitlink上确认存在；最小patch仍需代码级实现和构建测试，不能把路径核对当运行通过。

申请协调的范围仅为以上Higress/Wasm/Envoy接点和必要新agent模块/测试，不能据此采购、调用供应商、部署目标集群或把fixture变Ready。正式跨仓写入、patch承载分支/PR和供应链产物由Mika明确后接续；当前原生产路径继续不可调用。
