# 单模型运行组合与演示验收

本轮基于统一分支 agent/MAAS-10-offline-metrics 的8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a建立隔离增量。旧Chart/工作台/权限证据保留原SHA，不作为当前在线事实。当前未提供获准模型profile、真实网关扩展产物和请求证据，组合检查返回拒绝。

## 可重建输入

single-model/combination.json只记录一个逻辑模型的alias、sourceType、批准profile/approval引用，入口/执行环境/日志/停止说明引用，Higress gateway/controller、H1/H4 Wasm、H2 Envoy reporter、H3实例agent、Secret agent的版本、镜像或Wasm digest、有效配置digest及证据引用。配置摘要只能覆盖非秘密有效配置，不能对Key/DSN等低熵秘密作hash。SelfHosted另要求engine、weights-tokenizer、lws-controller，并复用来源卡中的GPU/拓扑/容量输入；不下载权重或新建GPU环境。ExternalAPI不要求GPU。

数据库Secret/DSN不在此清单重建；继续由dependencies.lock.json中的databaseIdentities和Chart core.databaseSecrets引用。核心/Reader/Operations/payload使用既定环境名；publisher继续通过显式工厂参数，不虚构环境变量。操作完成投影有受限写集，不称纯SELECT。Secret正文、原始DSN及session不进清单、日志或评论。

检查命令：

```sh
python -m unittest discover -s deploy/checks -p test_single_model.py -v
python deploy/checks/single_model.py --ref HEAD --values deploy/charts/maas-platform/values-internal.yaml --output .cache/single-model-report.json
```

内部工具按指定Git提交导出快照，调用scripts/unified_sources.verify验证同一code commit、祖先关系和完整源码清单；随后实际读取该快照的build-sources.lock.json、dependencies.lock.json、identities.json及runtime-interface.json，记录四份SHA256，复用原预检与Secret绑定检查。它不执行lock脚本、不修改来源锁、不发请求。代码改变而未刷新四锁时拒绝sources.invalid。更新流程仍是先提交代码、再运行python scripts/lock-unified-source.py并单独提交四锁。

ready仅表示离线输入/引用完整。observedCallable及requestEvidence须来自后端/QA实际运行记录，填写字段不构成可信回执或运行验收；真实Go/MySQL门禁仍最终决定准入。该检查不尝试解释凭证正文、证明签名或替代后端证据校验。

## 启动、日志与清理

1. 从待验收精确SHA执行python scripts/assemble-workbench.py --ref <SHA> --output <新的独立目录>，保留生成的workbench-sources.json及四锁摘要。不混用个人分支、旧镜像与最新前端。
2. 根npm run dev仍为本地管理工作台：使用私有临时MySQL/API-server、loopback及明确测试适配，不能用来声称Higress在线。当前生产Operator及发布适配缺口继续按runtime-interface及原预检拒绝。没有真实组合时停在此处，不以stock ai-proxy或直连上游绕过Go/Higress门禁。
3. 单模型在线启动前，后端须提供实际可消费的受保护推理入口/配置、发布屏障、插件与Secret本地通道、预算和profile。本组合文件由运维记录确切镜像/Wasm/配置版本及日志位置，与实际进程核对；当前这些值未知，不编造Docker/Helm安装命令。
4. 如仓库提供.multica/environments.toml，使用运行时CLI的env start管理对应声明；尚未声明时不自动建立长期服务。本轮没有请求持久演示URL，没有新启服务。未来需要长期演示须记录TTL、日志和stop方式；目标集群/付费或外部发布须对应授权。
5. 最小验收顺序：创建平台Key→三维预算/profile绑定→每模型CR发布→全部接流实例/boot代际receipt→专用受保护validation→经Go/Higress一次调用→查询原request_id的终态和可获取usage。记录publication/epoch与响应request_id、操作ID及日志证据位置。未知Token/金额保持null/held；取消、传输安全结束、生成停止、slot恢复与预算分别取证。失败不自动跨来源回退、重放生成或把丢失usage填0。
6. 收集证据后，以原管理入口关闭新准入，按原publication/slot排空、保留未知财务held、UID/inventory清理；不因Pod消失或grace到期退款。临时工作台按现有Ctrl+C/stop流程停止自有实例，保留清理返回记录，不误停其他任务服务或Multica daemon。

## 本轮验证范围

七项合成正反用例验证组合字段和缺口分类；统一基线实际完整源清单为backend514/514、console68/68匹配，离线组合有120项缺口而拒绝。这些不是120个产品故障，包含既有未批准依赖与缺运行输入。后续新提交/后端交付应重新导出检查，不能将本轮截点永久固定。未执行真实网关/插件、数据库有效权限、镜像构建、目标安装、模型/GPU或在线端到端；演示启动依赖仍交原后端/算法/QA共同提供。
