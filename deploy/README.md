# MaaS 部署包（MAAS-8）

本目录提供平台 Helm Chart、配置 schema、无集群静态验证及运维手册。交付为**可评审装配包**；真实集群安装、Higress H1–H4、Secret agent、受保护 validation、SelfHosted/GPU 与 A01–A34 运行验收尚未执行。

基线：默认分支 `86f5408`；接口核对 MAAS-3 `4f3eb9358f26ebab637a549b795651171d3b924f` 的 Operator、迁移和权限定义，以及 MAAS-2 v0.4、OPS01–OPS08。该提交的 Operator 未装配生产 adapter，readyz 返回 DependencyMissing、metrics 关闭。业务内核目前是 Go 库，无可部署 main；Chart 不改变此行为。

默认关闭工作负载；启用需显式提供 digest、引用和接口。`values-internal.yaml` / `values-hybrid.yaml` 是环境输入模板；`tests/fixtures` 是**合成渲染数据**，不得用于安装。API group 未批准，Chart 不安装 CRD、不读取集群、不创建 Secret/数据库/权重、不启动迁移 hook。

本地检查（Python 3.10+；不访问 kubeconfig、不写目标）：

```bash
python3 -m venv .venv-deploy
.venv-deploy/bin/pip install -r deploy/checks/requirements.txt
.venv-deploy/bin/python deploy/checks/verify.py --helm helm
.venv-deploy/bin/python -m unittest discover -s deploy/checks -p 'test_*.py' -v
GO111MODULE=off go test ./deploy/probe
```

Windows 可在已有 WSL 内运行相同命令，或通过 --helm 指定本机可执行文件。检查器仅执行 helm lint/template 与本地解析。检查结果见 `evidence/verification.json`。

见 [运维手册](docs/runbook.md)、[环境门槛](docs/readiness.md)、[依赖锁定清单](dependencies.lock.json)。控制台镜像、业务入口和真实适配继续由原前后端负责人交付。