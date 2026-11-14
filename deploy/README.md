# MaaS 部署包（MAAS-8）

沿 PR #5 更新的平台 Chart 0.2.2、配置门槛、静态控制台打包和运维手册。默认925d8c5、后端候选0559fa4、QA核心ac94a373和前端候选30cfce9分别锁定。完整构建输入/整目录覆盖步骤见[固定来源组装](docs/source-assembly.md)。当前为可评审装配包；目标安装、真实H1–H4/Secret/validation、SelfHosted/GPU与A01–A34尚未运行验收。

cmd/control-api已消费独立Reader/Operations/payload连接，新角色模板由原后端提供；publisher/生产入口仍待实际装配。管理入口仅loopback bootstrap，不提供生产健康/推理监听。Operator仍缺真实adapter，readyz失败、metrics关闭。详见[当前装配差异](docs/current-assembly.md)及[身份/故障恢复](docs/database-identities.md)。

默认关闭工作负载；示例输入和tests/fixtures为合成渲染，不能用于安装。Chart读取runtime-interface.json验证编译group，并拒绝把control-api用作生产core；预检另校验源码、六项迁移摘要、恢复输入及生产适配事实。文件/状态字段不能替代真实运行门禁。API group尚未批准，CRD/共享Higress/LWS/数据库/Secret/权重仍由各原安装方独立管理。

本地复现（Python3.10+、现有Helm、Go；不读kubeconfig、不写目标）：

```bash
python -m pip install -r deploy/checks/requirements.txt
python deploy/checks/verify.py --helm helm
python -m unittest discover -s deploy/checks -p 'test_*.py' -v
GO111MODULE=off go test -count=1 ./deploy/probe ./deploy/console-server
python deploy/checks/inspect_sources.py --backend-root <固定后端导出根目录> --console-root <含console目录的固定前端导出根目录>
```

Windows可用 `--helm-command "wsl -d Ubuntu-22.04 -- helm"`。静态结果见evidence/verification.json、source-inspection.json与suites.json；原52a24c0证据保留在evidence/history，计数不累加。

`images/Dockerfile.console` 打包实际console/dist与非root静态服务器；API及开发会话路径不回SPA。构建上下文须包含固定前端源码与本deploy目录，所有base image显式给digest；镜像本轮未构建。正式Go生产适配/会话仍待原后端交付，不以静态页面就绪替代Callable。

见[环境门槛](docs/readiness.md)、[运维手册](docs/runbook.md)、[依赖锁定清单](dependencies.lock.json)。目标集群/模型/付费调用与公开发布继续按原授权门槛。
四条连接的 `core.databaseSecrets`、角色模板和源码必须对应；未合入候选、缺配置/证据/消费变量、共享身份、Reader写角色、过期来源清单和publisher模板摘要均被预检拒绝。R3真实default role/hook正反证据引用QA50354a7的ac94受控范围，本轮只做部署检查；历史117/25、工厂单测及QA业务结果不计作新验证。当前原后端工作台保持运行，本轮不操作服务或共享数据。
