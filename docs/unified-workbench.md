# 统一工作台与 publisher 本地装配

在原 PR #6 分支仓库执行（Python 3.12+、PyYAML、Node 22.12+；Windows 使用已有 Ubuntu-22.04 WSL2）：

```sh
python scripts/assemble-workbench.py --output .cache/workbench-unified
cd .cache/workbench-unified
npm run dev
```

打开 http://127.0.0.1:4179。首次安装和构建需要数分钟。输出目录必须不存在；已有目录改用新名字，避免覆盖旧工作。前台 Ctrl+C 清理临时数据；需保留本地服务时，在此输出目录按 `docs/local-service.md` 启动隐藏宿主，最长8小时。

组装复用运维 e5647a2 的原 `source_context.py`，先核对完整0559后端与30cf前端源输入，再覆盖当前提交的后端增量；console始终完整来自30cf，不继承旧 `.env.workbench`。`workbench-sources.json` 记录后端完整SHA、前端30cf、运维e564与逐文件SHA256。运维旧锁仍描述0559，不能把新的本地组合声称为已更新的部署批准。

本地构建显式传入 `NODE_ENV=development`、`VITE_LOCAL_CONTROL=true`、`VITE_CONSOLE_FIXTURES=false`，沿前端候选现有DEV入口连接同源Go临时会话。它仅作用于本地构建；正常生产 `npm run build` 不提供本地会话安装页面。

Key页可创建、修改显式预算并撤销；发布页可查看已有示例，编辑 `upstreamModel` 为 `local-example-v2` 进行更新，再暂停/恢复、读取保留修订、回滚、下线与查询原操作。创建新发布时点“新建外部 API CR”，把输出目录的 `workbench-example.json` 内容粘贴到编辑框提交；重复创建先换metadata.name和spec.modelAlias。该样例只含本地惰性引用，不是供应商配置。请求/用量页读取实际账本空态。

本次实际启动路径 `cmd/workbench` 在自有临时MySQL中，用安装连接执行原迁移和仓内角色模板，然后分别使用core、publisher、history、payload、operations五个身份。安装连接不传给业务handler。publisher经 `mysqlstore.OpenPublisher(ctx, explicitDSN, cluster, evidencePort)` 创建；缺DSN、root、未启用原default role或缺证据端口均拒绝，不回退core/operations身份。工厂始终开启原同事务operation完成hook，不创建用户、不迁移、不GRANT；临时账户安装只在localworkbench入口内。运行错误不回显DSN。

真实角色完整有效权限仍由安装审核，工厂的default role检查不替代审计。运行中的缺权限错误沿原事务回滚，不忽略hook；ACK未知仍沿原CommandID恢复，不重放生成。原R3 Activate/ACK独立证据保留ac94范围；本轮新增factory装配/关闭/cleanup/原Pause完成及拒绝SQL验证独立记录。

管理装配不提供真实Higress/Secret/validation、adapter批准或目标集群生产身份。`cmd/operator`仍缺获准生产适配器，不能从本地管理metadata制造Callable。真实推理保持503；GPU研究和局部D1均不代替真实调用链验收。

验证入口：`node scripts/workbench-smoke.mjs --url http://127.0.0.1:4179` 对已启动同一实例操作并保留服务；不带 `--url` 则自建临时实例并清理。浏览器脚本会创建一个已撤销Key，创建/清理local-created CR，记录原operation查询，不触发模型调用。前端消费者异常测试使用明确标注的合成HTTP/SSE，与真实管理HTTP结果分别记录。

实际临时安装发现旧payload角色名maas_release_history_payload_reader有35字符，MySQL8.4返回1470拒绝CREATE ROLE。本轮模板及本地消费者统一缩短为maas_history_payload_reader，原SELECT列权限保持。仅修改仓内模板和自有临时身份，未改目标账户；运维来源/角色锁须跟随此名称和新后端SHA更新。TestLocalRuntimeIdentities复用原迁移与全部三份模板，验证五个独立身份及真实default role。