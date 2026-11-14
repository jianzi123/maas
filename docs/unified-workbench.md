# 同一代码快照的统一工作台

在统一集成分支的仓库根目录直接执行：

```sh
npm run dev
```

Node22.12+；Windows使用已有Ubuntu-22.04 WSL2，Linux使用amd64。程序构建当前console，编译当前Go，并启动自有临时MySQL/API-server/etcd。停止时清理本次数据；真实推理仍不可调用。端口可用 `npm run dev -- --port 4180` 指定。

需要独立的构建目录时：

```sh
python -m pip install -r deploy/checks/requirements.txt
python scripts/assemble-workbench.py --output .cache/workbench-unified
cd .cache/workbench-unified
npm run dev
```

组装只对一个本地Git提交做一次archive；默认HEAD，也可用 `--ref <交付提交>`。前端、Go、部署、算法/性能和QA文件都取自这个快照，不fetch旧分支、不替换成30cf前端。拒绝未提交的已跟踪修改、存在的输出目录、被篡改的完整输入或锁定后新增的运行代码；未跟踪文件、凭证和缓存不进入输出。

`workbench-sources.json`记录当前仓库commit/tree、全部输入摘要、各组件相同的仓库commit及单独的代码锁commit。代码先提交，再生成四份部署锁并单独提交，可避免摘要引用自身；两次提交属于同一历史，锁提交之后只允许四份锁元数据变化。新代码必须重新锁定。

```sh
python scripts/lock-unified-source.py
# 检查四份deploy锁后单独提交，再导出HEAD
python deploy/checks/inspect_sources.py --backend-root . --console-root . --output artifacts/unified/source-inspection.json
```

本地会话、Key、管理/历史/operation均复用同一Go内核。publisher使用显式窄权限连接和原同事务完成hook；core/history/payload/operations分开。安装账户只在localworkbench自有临时MySQL使用，生产工厂及实际有效权限另行验收。

已有批准便携工具时可设置 `MAAS_WORKBENCH_TOOL_CACHE` 指向含go-linux、mysql-test、envtest的只读缓存；可设置 `MAAS_WORKBENCH_GO_CACHE` 为本任务可写的Go模块/编译缓存目录。Windows支持绝对Windows或WSL路径，Linux用绝对路径。工具缓存不提供产品源码；使用它不会替换当前提交，也不修改或安装系统驱动。

Key与发布操作说明见根README。页面可载入本地示例，生成的workbench-example.json只包含本地惰性引用，不是供应商批准。运行前后用 `npm run test:workbench`可启动专属临时实例并验证浏览器管理闭环；不影响其他目录的服务。

需要终端关闭后继续使用时，按docs/local-service.md显式启动宿主；本次代码统一本身不替换现有实例。已知Delete恢复边界及生产未验项见docs/unified-status.md。
