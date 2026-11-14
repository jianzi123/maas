# 同一仓库快照的构建来源

当前推荐入口是 `python scripts/assemble-workbench.py --output <不存在的新目录>`。它导出当前HEAD一次，完整保留backend、console、deploy、tools和test；输出清单中的各组件仓库commit完全相同，不再用不同分支覆盖目录。

## 代码锁与交付提交

先把所有源代码提交为代码提交C，再运行 `python scripts/lock-unified-source.py`。生成器只写build-sources.lock、runtime-interface、dependencies.lock、identities四份deploy元数据，随后单独提交为交付提交L。这样不把最终提交SHA写入它自身；C与L属于同一条历史，L的所有运行代码字节与C一致。

完整backend/console清单均锁到C。组装HEAD L时，验证C是祖先、两者差异仅为四份锁，并核对完整输入字节。输出workbench-sources.json记录实际仓库L及tree、代码锁C、组件共同的L和完整摘要。编译/服务所见代码来自同一快照，未跟踪本地文件和缓存不进入上下文。

后续改代码后必须先提交新代码再更新锁；包括deploy中的运行代码。不能只改摘要、冒称旧QA覆盖新版本，或删除默认工作台代码来对齐旧清单。独立QA目标和证据提交保留其原范围；当前合并候选没有因此获得整体QA或生产批准。

`inspect_sources.py`比较当前代码的完整清单。旧source_context.py仍可复现历史组件导出，但不是当前推荐组装入口。此前0559/f445与30cf/e564的证据保留为历史，不宣称其覆盖当前交付树。

候选状态保持integrated-unmerged，deploymentApproved、productionWiringVerified及生产ready标志保持false。生产预检应继续拒绝缺实际合并、镜像、身份、Secret、网关和环境输入。此变更只统一代码和构建来源，不写目标账户、不构建/发布镜像或部署。
