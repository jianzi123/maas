# MAAS-17 删除恢复边界

`delete-recovery-probe.test.ts.in`是审查者在48da810合成Response/jsdom上的原反例；没有Go/模型调用。它验证权威原Delete已查明Succeeded、原CR404后是否有安全的新人工动作出口，并以Unknown＋404继续锁定作对照。

运行 `npm run test:known-boundaries`。当前预期一过/一失、退出1，原断言没有放宽；它不是默认套件的通过项，也不代表生产数据发生过该序列。具体恢复规则仍由架构/原前端/独立QA确认，不得对任何404或身份错配泛化解锁，不重放旧操作。

统一代码先保留这个未闭合项，后续修复沿同一分支接续，不再从旧前端分支覆盖目录。完整已知范围见docs/unified-status.md。
