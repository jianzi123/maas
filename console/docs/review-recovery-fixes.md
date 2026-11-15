**MAAS-5：MAAS-17 前端恢复修复**

针对 FE-O1、FE-U1、FE-S1 的后续增量，基于默认 `925d8c55be9ce823d100bf90a5c78cf19ea66d58` 正常合入原消费者修复 `30cfce951df8a858810a035efe51846a75a4ade6`。保留默认工作台模式、本地示例及原身份校验；旧 PR #4 不重开。产品修改仅在 console 内。

- 原操作 ACK Unknown 后，仅归属一致的原 operation 查询能确认结果。Succeeded/Failed 先失效旧编辑基线，重读同一 namespace/name/UID 的 CR 和 resourceVersion 后才解锁新的手动动作。Running/Unknown、404/503、错配、被替换 UID 或缺版本继续锁住；当前 CR 本身不能证明原写成功。查询和重读均不重放原写。终态已知但等待重读时明确提示，不再显示“写入结果未知”。
- 新筛选启动时清空旧用量快照；查询或分页失败时清除明细、汇总、观察时间、完整性及游标。保留错误，不显示为空查询成功。代价是分页失败后须从第一页手动查询，避免将不完整旧页误当本次完整数据。迟到的旧响应不能覆盖新查询，卸载后失效。null、held、金额和价格分组原义保留。
- finish 后带新 choices 的内容或重复/矛盾 finish 在发布回调前拒绝；允许 choices=[] 的独立 final Usage。原 R 保留用于精确回查，不自动重发生成。这是消费者加固，不重开后端 R2。

在 console 目录复验：

```
npm ci --ignore-scripts --no-audit --no-fund
node node_modules/vitest/vitest.mjs run src/review-recovery.test.ts --pool threads --maxWorkers 1 --configLoader runner --no-cache --no-fsModuleCache
node scripts/review-recovery-browser.mjs
npm run build
node node_modules/vite/bin/vite.js build --mode workbench
npm run format:check
```

`review-recovery.test.ts` 为合成 Response/jsdom 正反验证；浏览器脚本使用临时 loopback Vite、无头 Edge 和标记明确的合成 fetch/SSE，前台结束时关闭两者，输出到 `console/artifacts/review-recovery`。Linux 等环境可用 EDGE_PATH 指定已批准的浏览器路径。脚本不连接 Go/MySQL、模型、Higress 或目标集群，不取用上游凭证。

原六项评审探针通过认证附件获取，仅复制临时副本执行，不改原断言；原探针的产品证据输出目录须预先创建。作者结果、原独立 QA 和本次浏览器/合成证据分别记录。原 Go R1–R3、D1、Usage/Reader 等已交整批未重跑；本次不修改 Go、DDL、共享契约或 #5 来源锁。

最终组合仍需原独立 QA 按新 SHA 定向验收，再由运维刷新真实构建来源。生产 Callable、真实模型/非空真实用量和 A01–A34 不由本次前端修复自动验收。
