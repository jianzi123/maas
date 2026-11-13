# 固定来源的构建上下文

| 来源 | 固定提交 | 范围 |
|---|---|---|
| 默认分支 | 925d8c55be9ce823d100bf90a5c78cf19ea66d58 | 已合入历史基线 |
| 后端 PR #6 | 0559fa46b4a728d6f542daf19532e794f8549b31 | 草稿未合入；含有界本地服务宿主 |
| QA 业务核心 | ac94a373ec0a61c5fd4dc5380a7985a4fb47840f | R1–R3 受控范围；独立证据提交50354a705c03383d0102d0d437119afd7ffed8b3 |
| 前端候选 | 30cfce951df8a858810a035efe51846a75a4ade6 | 整个 console 目录；不在默认分支中 |
| 部署增量基线 | 43308837df5a2710f2027d320cdb93a4392285de | 本增量实际部署提交由交付评论及构建来源附件记录 |

0559 对 ac94 的差异仅 README.md、docs/local-service.md、scripts/workbench-service.mjs。独立 QA 范围不自动扩大到后续宿主或前端候选。本轮不合并远端 PR，不操作原后端已保留的工作台。

`build-sources.lock.json` 清点后端完整 Git 导出中排除 console/deploy 后的173份文件，和前端候选整个 console 的64份文件。包含全部 Relay/结算/采样改动、角色/迁移、go.mod/go.sum、脚本、前端源/依赖/测试文件；不再只依赖旧36份选定摘要。部署目录作为独立覆盖层，摘要见 verification.json 与交付包。清单不含私有缓存、node_modules、.git、构建产物或运行凭证。

## 组装和验证

先把上述完整后端和前端 SHA 分别 `git archive` 导出到两个全新目录。然后在本部署提交运行：

```bash
python deploy/checks/source_context.py --backend-root <后端导出> --console-root <前端导出> --output <不存在的新构建目录>
python deploy/checks/inspect_sources.py --backend-root <新构建目录> --console-root <新构建目录>
python deploy/checks/candidate_wiring.py --backend-root <新构建目录>
python deploy/checks/permissions.py --backend-root <新构建目录>
```

组装器先逐文件核对源输入，拒绝缺失、改字节及未列入清单的额外输入；再复制后端非 console/deploy 文件、前端完整 console，最后复制当前 deploy 代码/配置（排除 evidence 与 Python 缓存）。输出目录必须不存在，拒绝覆盖任意已有目录，也不会停止/修改服务。这样前端已删除的旧 `.env.workbench` 不会残留。

本轮对后端原树直接声称前端30cf做负例：client.ts等共同文件字节不同，也有缺失文件和旧额外文件，具体路径以报告为准；正确覆盖后必须全部通过，不能把35/36称完整一致。`source-inspection.json` 检查111份选定接口/前端文件；`assembly-inspection.json`另检查全部237份上游源输入及最终树，两个检查范围分别记录。

预检同时核对完整来源清单摘要、backend/console/QA核心修订、publisher角色模板摘要及四条DSN引用。候选仍未合入，deploymentApproved和productionWiringVerified仍false，不能手改merged来冒充实际合并。

## 镜像与当前本地实例

Dockerfile.operator、Dockerfile.console的上下文均使用上述新目录。GO_IMAGE须是支持go.mod中Go1.26.0的批准digest，GOTOOLCHAIN=local避免构建时隐式换工具链；NODE_IMAGE/RUNTIME_IMAGE也须独立批准并锁digest。前端沿候选package-lock构建，Go模块沿后端go.mod/go.sum；无生产core配方/镜像来源时继续阻塞。此次没有构建镜像或镜像digest，不推送仓库或部署。

当前 http://127.0.0.1:4179 工作台由原后端启动并保留；本轮不停止、替换、重启，也不清理其缓存/数据。宿主ID/PID/TTL等动态事实以原启动目录的 `.cache/workbench-service/status.json` 和对应任务最新记录为准，不能使用本部署工作目录推断服务状态。`node scripts/workbench-service.mjs status|stop` 必须在原启动仓库操作。这里仅说明已有操作，不在本轮执行stop。

候选构建上下文含前端30cf，不等于正在运行的0559实例已包含该候选。原后端14项浏览器和Mika健康检查是原范围证据，本轮未复跑或累加。metadata管理演示、局部D1、Chart渲染均不代表真实推理/生产身份、Higress/Secret/validation或A01–A34整体验收。
