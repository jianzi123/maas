# 环境门槛与验收分层

本轮只授权仓库部署目录和无目标写入检查。以下状态可以评审；真实部署须提供具体目标授权，生产及对外发布另行授权。

| 层次 | 可得证据 | 当前结论 |
|---|---|---|
| Chart/schema/渲染 | 本地 lint、合成 values、权限/引用检查 | 见 evidence/verification.json |
| 探针程序 | loopback 合成 200/503/重定向/拒绝连接 | Go 单测，不能证明真实 Operator 就绪 |
| 二进制/镜像 | 当前 Operator 的接口已读源码 | 未构建镜像；core/console 的实际启动接口待交付 |
| K8s/Helm | 服务端 dry-run、RBAC、CEL、证书和升级/回滚 | 未执行 |
| 业务发布 | 真实 H1–H4、全实例 receipt、固定绑定及受保护 validation | 未装配，保持不可调用 |
| SelfHosted | 确切模型/许可、GPU、完整 LWS 组/显存、质量和性能 | 未提供目标，未执行 |
| 备份/恢复 | 同恢复点账本/发布域、fencing、Redis见证重建 | 未演练 |

先补 `dependencies.lock.json` 的目标/批准版本/来源、镜像或工件 digest 与私库映射、运行门槛证据。锁清单是审核记录，不是运行真源。目标显式列 modelSources；ExternalAPI 单独装配不要求 GPU/LWS/权重，SelfHosted 保留全部条件。字段填 verified 不能替代实时门禁；运行仍由 Go/MySQL 及真实证据判定。当前预检应失败：

```bash
python deploy/checks/preflight.py --values deploy/charts/maas-platform/values-internal.yaml
```

只读预检拒绝未知字段、内联秘密、非digest镜像、未批准 API group、未就绪组件、无效网络/公网旁路及待锁依赖。示例值不是环境证据。Higress 的真实外部出口由网关安装负责人管理，引用名不证明策略生效；CNI 对所有组合策略的加法语义、NAT/hostNetwork 例外和实际拒绝需目标验证。

API group 确认后原后端须统一修改 Go/schema/CRD/webhook/客户端，再交匹配镜像。当前二进制不能因 values 改 group 直接支持新域。当前 CR 全集群缓存需要 ClusterRole 只读；namespace外无写权限。若要求彻底 namespace 隔离，须由原后端先支持 scoped cache；本 Chart 不伪造不存在的 flag。

授权测试阶段的最小材料：

1. 唯一 cluster/context/namespace、访问范围及测试时段；安装/复用清单和原 Helm owner，不 force 接管共享组件。
2. 目标 K8s/Helm/Higress/Envoy/Wasm/LWS/引擎/驱动/存储矩阵及 digest；批准镜像渠道和独立迁移/运行身份。
3. 仅内网或混合出口、TLS/mTLS、服务端证书 SAN、Secret UID/版本/agent 本地通道；密钥正文走安全渠道。
4. 最小耐久 Key/三维预算/slot/request/唯一结算、真实 receipt 和受保护 validation；具体模型/来源及调用额度。未知 Token/金额仍为 null/held。
5. RPO/RTO/保留期/备份加密和恢复目标，排空及升级窗口。没有成员决定不采用历史100次/日或5并发。
6. SelfHosted 另具模型许可/权重引用、GPU/互联和质量/性能方案。ExternalAPI 不创建 GPU 资源；该阶段推进不删除完整 A26/A34 验收。

独立测试依 A01–A34 收集安装/复用、缺依赖拒绝、跨来源/跨模型权限拒绝、证书轮换与实例扩缩容、排空/UID迟到清理、迁移/恢复等证据；不把 Chart 成功或 Pod Ready 记为 Callable。