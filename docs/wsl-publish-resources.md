# WSL发布资源接续

本轮基于统一8dbf99e上的PR14/15依赖，保留原分支。专用环境为kind-maas-wsl/Kubernetes1.35.0/Higress2.2.5；所有kubectl必须显式传入用户指定的私有kubeconfig和--context=kind-maas-wsl，不切全局context。首次核对控制台1/1、控制面2/2、网关1/1 Running；maas-system无Pod。MAAS11最终评论确认控制器未部署、旧构建已停止。

## 固定模板编译器

新增release.TemplatePluginCompiler实现既有PluginCompiler端口。安装侧Templates按PluginDigest查找，只接受固定url/sha256/phase/priority/pluginConfig五类公开元数据；配置整体Hash必须等于Resolver.Resolution.Versions[wasm_template_sha256]。该内部版本键由安装登记提供，不从CR、网页或默认fixture生成批准。OCI URL必须锁@sha256、摘要为规范64位十六进制；HTTPS模块也需独立sha256。配置经JSON归一化和深复制，常见内联凭证键被拒绝，输出修改不改变安装模板。模板仍必须由可信安装方审阅为公开配置，本编译器不验证插件二进制语义或生产者身份，不提供任何模板/批准默认值。

发布UID/publication/generation/revision/name必须匹配原Compile计划。输出只匹配该发布Ingress，defaultConfigDisable=true、唯一matchRule configDisable=false、FAIL_CLOSE，禁止模板覆写全局selector。原Reconciler.Plugin接口可直接消费；资源仍走原Inventory.Intent/Bind及原BundleWriter，原publisher证据决定能否Activate。没有新增账本、协议或Ready来源。

验证：TestPinnedPluginTemplate正常场景及6个拒绝场景通过，含缺模板、摘要漂移、普通/typed map内联凭证、selector覆盖和错名称；真实Go输出Ingress/WasmPlugin经已安装Higress CRD严格server-side dry-run接受。测试模板与OCI digest是控制夹具，未创建对应Ingress/WasmPlugin，未拉取或运行该插件。McpBridge目录仍沿原BundleWriter接口，持久BundleCatalog与实际批准Resolver/插件产物尚待接线，不能据Schema通过宣称路由已发布。

## 审阅控制器构建/部署

Windows已有Go1.26工具链跨编译Linux，避开旧WSL跨NTFS缓存复制。构建参数为GOOS=linux GOARCH=amd64 CGO_ENABLED=0、任务内GOMODCACHE/GOCACHE，输出只含operator二进制。随后从干净已提交源码再构建并记录完整HEAD/二进制SHA256。Docker上下文仅operator和本目录Dockerfile；基础busybox1.37缓存镜像固定上述实际RepoDigest，不下载模型或另建集群。

```powershell
$env:GOOS='linux'; $env:GOARCH='amd64'; $env:CGO_ENABLED='0'
# 指向已有Go1.26缓存：GOROOT/GOMODCACHE/GOCACHE/GOTOOLCHAIN=local
& ./.cache/go-windows/bin/go.exe build -o artifacts/wsl-operator-native/operator ./cmd/operator
```

WSL中对该小上下文docker build，再用原kind二进制load docker-image --name maas-wsl。operator-review.yaml来自原MAAS11公开清单，仅替换镜像占位符；原SA/RBAC范围保持，复用现有maas-operator-webhook Secret，不读取/交付私钥。应用前再次确认不存在其他运行控制器；不覆盖他人Deployment。正式状态以最终交付评论、get pod和原CR.status为准。

cmd/operator默认nil适配器保持，liveness使用已有busybox wget健康检查，readyz继续失败（本次实测HTTP500）。因此预期进程Running但Pod Ready=0/1，CR观察代次更新并显示DependencyMissing/Callable=false。它是可运行的审阅控制器，不是正式MaaS完整安装包或单模型调用验收；不能关闭readiness探针制造Ready。

## 真实组件/替身/剩余

真实：专用kind/Higress/CRD/API-server，原控制器协调器与模板编译代码、本机Linux二进制和镜像。受控：模板单元输入与server-side dry-run计划，不持久化或授权真实来源。仍缺：真实批准Resolver/profile、插件产物及H1/H4通道、持久Bundle目录/独立publisher运行组合、H2/H3完整实例证明、Secret/validation和来源输入。不得以本地资源存在或四bool/EOF替代这些事实；未知actual/held与slot分离不变。

本轮不操作旧higress/traininfer集群，不创建新集群、不停止现有服务、不调用真实模型/GPU/付费或生产Secret；本地webhook Secret仅引用。运行的审阅Deployment由Kubernetes管理，保留供查看；需要停止本新增控制器时仅对指定kubeconfig/context执行kubectl -n maas-system scale deploy/maas-operator --replicas=0，不停止Higress或节点。后续原后端接真实发布依赖，工具链由MAAS8核定；MAAS21的完整Compose/Kubernetes产品交付由原集成负责人归并，本增量不代替其结果。
本轮最终实测：maas-system/maas-operator运行于新Pod，healthz返回ok，readyz为HTTP500，Pod Running且Ready=0/1、restart=0；external-model-example generation=observedGeneration=1、Degraded、Callable=False/DependencyMissing。原Higress三Pod仍Ready。空McpBridge/default已按独立安装清单创建，实际registries条目数0；Go产生的Ingress/WasmPlugin及共享条目只做server-side dry-run，三类Schema均通过，未持久化测试条目。

本机已运行镜像maas/operator-local:wsl-review-20261123，其构建源码head为369aade3bd0f25947f473da7c58a9ded7f594fc9（vcs.modified=false），镜像索引sha256:c40372121a644b625e790cdf3925a2246e100e29cec33950e75218976c0d427d。后续本节仅补实测文档及来源锁，不为文档刷新停止/替换此运行实例；运行来源与最终PR文档head分别记录，不能把它标为新的生产组合。