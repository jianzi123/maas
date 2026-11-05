# MAAS-10 / MAAS-11 受控开发集成

## 基线与历史

本次集成以远端当前默认分支 `agent/MAAS-10-offline-metrics` 的
`86f5408e100de6c276a2af543051098c3d4d5669` 为 PR base，合入
`agent/MAAS-11-controlled-release` 的
`67b46d1081622dce8f8704ceb94eb6e3e19350ef`。
两个来源最初分别初始化，之前没有共同祖先。

隔离分支 `agent/MAAS-11-integrate-controlled-release` 使用保留双方历史的
merge（`--allow-unrelated-histories --no-ff`）；未改写原提交、移动原分支、
修改仓库默认分支或合并 PR。代码目录没有重叠，合并无文本冲突。
这里选定的是本 PR 的集成起点，长期主分支名称仍由项目另行确定。

MAAS-10 离线工具位于 `tools/perf`，MAAS-11 Go 模块位于仓库根目录。
根 README 增加两个交付的入口，`.gitattributes` 保留两套架构契约快照
的原始字节，避免原控制器的全局 LF 规则改变性能工具的来源哈希。
未合入其他实验分支或修改业务逻辑。

## 本次验证（2026-11-05 UTC）

| 检查 | 结果与边界 |
| --- | --- |
| 原始源码字节比对 | MAAS-10 的全部 17 个文件不变；MAAS-11 除 README 和 `.gitattributes` 外的 29 个文件不变 |
| `go test -json ./... -count=1` | 23 个顶层测试，含子测试共 39 项通过，0 失败 |
| `go vet ./...` / `go build -buildvcs=false ./...` | 均通过 |
| 离线 Python 测试 | 41 项通过，含契约来源哈希、固定夹具、预算占用和修订关联检查 |
| 离线分析 CLI | 合成夹具报告生成成功；不是模型性能结果 |

Go 验证使用已锁定的 Go 1.26.0 / controller-runtime v0.24.1 / Kubernetes
Go 库 v0.36.0，Python 3.13.9 / jsonschema 4.25.0；没有升级依赖。
运行输出和逐文件 SHA256 通过 MAAS-11 评论附件交付。

从根目录复现（已准备锁定的工具链与依赖）：

```powershell
./scripts/test.ps1
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$env:GOTOOLCHAIN = 'go1.26.0'
go vet ./...
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
go build -buildvcs=false ./...
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m unittest discover -s tools/perf -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
New-Item -ItemType Directory -Force artifacts | Out-Null
python tools/perf/analyze.py --input tools/perf/fixtures/synthetic.json --output artifacts/perf-synthetic.json
exit $LASTEXITCODE
```

本轮未重跑临时 envtest：当前沙箱访问 WSL 返回 `E_ACCESSDENIED`，没有
将测试改为访问真实集群。原阶段 envtest 的范围仍以
`docs/verification.md` 和原始任务报告为准，不计作本轮重跑结果。
本轮 Go 单元/受控 port 测试不证明真实 API-server、MySQL 崩溃恢复、
多副本线性化、网关回执新鲜度或安全 slot 排空。

## 下一阶段交接

本次受控 MySQL 增量沿用本 PR：新增发布侧迁移、MySQL Control/Inventory、同事务核心接点和最小权限模板，详见 [MySQL 实现边界](mysql-release.md) 与 [本轮验证](mysql-verification.md)。原集成时的测试记录保持为历史；本轮数据库证据单独列明，未将真实存储测试等同于真实内核/网关验收。

MAAS-11 完整发布功能保持 `in_progress`。原后端负责人在上述集成分支
继续受控实现 MySQL 发布屏障和耐久 inventory 适配；先核对架构契约中的
CAS、epoch、tombstone、UID 和 slot 安全结束证明，并与最小调用内核
约定同事务边界及数据库权限。不得复制 Key/预算/终态账本，不得将
slot 回收等同于退款。实现应保留重启、冲突、ACK 丢失和共享资源隔离测试。

Higress H1–H4、Secret agent 与 validation 仍未装配；没有真实且新鲜的
依赖证据时继续 `DependencyMissing` / 不可调用。不得用替身补成生产 Ready。
首次真实调用仍须具备最小 Key/三维预算/全局 slot/request/唯一结算内核、
版本与模型输入、Secret 安全渠道、额度和对应目标授权。

此次集成没有部署、创建集群、启动长期服务、下载权重、使用 GPU 或
调用供应商；管理 API、Vue、Helm、真实发布以及 A01–A34 完整运行验收
仍待后续交付。
