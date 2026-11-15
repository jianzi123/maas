# 统一项目运行与来源

2026-11-08 UTC。四个专家PR以正常merge整合到同一代码树，完整SHA见 `config/integration-sources.json`：发布#1 `8ccf6c0`、后端#2 `bfc1f7d`、部署#3 `4327989`、前端#4 `819c35e`，另保留原默认基线中的性能分析器。没有复制账本、改旧迁移或重写原专家提交。

## 运行

仓库根目录执行 `npm run dev`，访问 `http://127.0.0.1:4179`；Windows需已有Ubuntu-22.04 WSL2，Node22.12以上。固定版本依赖第一次下载到`.cache/`并校验摘要，无需逐个专家工作目录或手工提供临时会话/DSN/KUBECONFIG。`npm ci`在根目录也可执行，前端依赖由启动器沿原锁文件准备。

启动器构建Vue工作台专用mode，启动仅本地Unix socket的私有MySQL和独立API-server/etcd；Go在同一HTTP地址装配页面、同源短期会话、原管理Handler/内核、权威历史与连续Reconciler。暂停/清理与operation完成继续使用原MySQL事务；UI的Key、预算和发布均为实际后端操作。静态页面服务与部署镜像复用 `internal/webconsole`，API与缺失资源不回退SPA成功。

“载入本地示例”提供可操作CR引用。示例允许自选alias和资源名，只有打包的两项upstreamModel元数据版本可切换；它不代表供应商或引擎已批准。registry是明确本地metadata适配，网关producer明确缺失，目录示例始终不可调用；不创建推理Pod、Higress或Secret，不调用模型。请求/用量因此是真实空账本。真实模型仍须原Higress/Secret/validation与具体来源授权。

工作台仅本地受控模式。25分钟会话到期可重新连接，原值只在Key创建时显示。Ctrl+C或父进程stdin关闭会停止Go HTTP、协调、API-server/etcd和私有MySQL并清理本次临时数据；启动器不留后台服务。生产静态构建仍用`npm run build`，明确不包含本地会话安装入口。

## 本轮实际验证

| 范围 | 结果 |
| --- | --- |
| 根目录 `npm run test:workbench` | 15项实际浏览器检查通过，pageerror=0；编译后的Vue＋同源Go＋MySQL＋API-server/etcd |
| 完整用户流程 | 自动本地会话、示例目录、Key一次展示/预算改0/撤销、创建CR、暂停/恢复、更新、原UID历史回滚、下线/原operation查询、真实空用量、390px及退出 |
| 停止与清理 | 浏览器结束后stop，子进程退出0且返回cleaned=true；旧实例数据未残留 |
| 根目录 `npm test` | 前端104通过/11个HTTP环境专用skip；全仓Go测试、vet、API/Operator/静态服务/探针构建通过。默认无DB socket的Go数据库项不冒充SQL验证 |
| 性能分析器 | 41项Python测试通过 |
| 部署预检 | 12项Python测试通过；Helm104项静态/合成渲染检查通过，internal/hybrid各18资源；未部署目标 |
| 正常生产静态构建 | build通过，产物不含`/__maas/local-session`；专用workbench构建单独验证 |

最终复验发现“原operation已记录清理完成”和“CR实际移除”存在正常异步间隔。端到端断言保留最终404，并有界等待finalizer真正移除对象，未以operation成功直接推断CR已经不存在。

原始运行结果与截图在本次任务附件及`artifacts/workbench/`，不把计数与原72/20/48或独立QA轮次相加。QA-003已由原QA在`bfc1f7d`受控范围独立关闭，保留该结论；本轮为项目装配开发者回归。真实H1–H4/Secret/validation、生产登录/部署、模型/GPU及A01–A34整体验收继续按原门槛。
