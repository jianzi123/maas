# Chat / Agent 最小开发与部署接续（MAAS-8）

核对截点：统一分支 agent/MAAS-10-offline-metrics / 8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a。MAAS-20由原后端实现Session/Run/Agent核心，MAAS-5实现Chat；本轮不并行重写会话库或发明API/环境变量。实际源码变化后按新SHA重新核对，下列缺口不等于已批准的运行参数。

## 目前真正可消费的入口

| 项目 | 已有源码/行为 | Chat/Agent接合条件 |
|---|---|---|
| 本地入口 | 根npm run dev→scripts/dev.mjs→既有WSL/本地workbench；cmd/workbench带localworkbench标签 | 当前是管理会话/示例发布，不能说明Chat持久化或Agent循环已运行 |
| 管理HTTP | cmd/control-api/main.go强制loopback、显式短期session与Origin；Reader/Operations/payload消费原独立DSN | 没有新Session/Run路由、事件订阅或Agent配置消费者；不增加猜测的环境项 |
| HTTP时限 | cmd/control-api/main.go及cmd/workbench/main.go：ReadHeaderTimeout=5s、ReadTimeout=10s、WriteTimeout=15s、IdleTimeout=30s | 15s全响应时限不适合直接宣称支持长期事件订阅；须原后端按新路由单独实现有界事件流/取消与写deadline |
| 数据库 | kernel.Migrate、mysqlstore.Migrate各1/2/3及既有迁移身份/窄读角色，见原手册 | 当前没有Session/Run/Message/Event/Checkpoint迁移或专属角色，不能将现有账本角色直接授权新表 |
| 静态页面/代理 | internal/webconsole与deploy/console-server；Ingress的/api、/v1到Go，/到console，无已确认的新Chat路径 | 跟随批准后的API路径/同源会话接线；不把API失败回退SPA，不新增随机代理前缀 |
| Agent组件 | MAAS-20当前新建、后端正在单流实现 | 注册器、工具白名单、限额、恢复入口等待实际代码；首期只读/纯计算工具由内核默认拒绝未知工具 |
| DSH sidecar | 当前没有受控sidecar消费者、锁版ADR或进程协议 | 不安装DSH、Cordis或通用插件；如后续ADR采纳，必须锁commit/digest、RPC schema、身份、超时和停止责任后接合 |
| 探针 | /maas-probe及Operator loopback健康；Operator readyz依赖缺失，metrics关闭 | Chat/Agent新增依赖必须由真实启动器/就绪函数报告，不用进程存活或存储Ping证明模型可调用 |

以上为本轮读取代码所得；没有改共享后端服务器超时。未来事件接口即使仍位于/api，也须核网关/入口对buffering、compression、心跳、idle/write/overall deadline和断连的实际行为，不能仅加一条Ingress注解假设生效。Higress上游推理时限和UI事件订阅时限分开，不能为了长Chat流放宽模型硬截止。

## 已提供的本地事件流探测

```sh
python -m unittest discover -s deploy/checks -p test_event_stream.py -v
python deploy/checks/event_stream.py --url http://127.0.0.1:<明确端口>/<后端已批准订阅路径> --events 2 --idle-ms 1000 --observe-ms 5000 --output .cache/chat-agent-events.json
```

端口/路径必须由实际后端交付；此处没有可复制为真实服务的虚构URL。该工具只GET指定loopback HTTP端点，不扫描地址、不创建session/run、不提交消息、不执行工具/模型、不自动重连或跟随重定向。loopback-only限定对应本轮本地验证授权；目标TLS/mTLS/生产网络另按已批准通道验证，不能关闭TLS验证绕过。

如实际路由需要现有session，使用--headers-file指向安全渠道提供的本地JSON文件，仅允许Cookie/Authorization/Origin；不把内容传命令行/源码/评论。它只读文件，不创建、修改或删除凭证。--cursor透传Last-Event-ID仅用于后端明确采用SSE cursor语义的接口；原生事件协议尚未审定时，不以此工具定义公共契约。游标作为关联标识仍须访问控制。

工具拒绝非200、非text/event-stream、压缩body；按空行分帧，多行data为同一事件、comment为心跳计数。达到所需data帧数即主动关闭响应和socket；EOF不足帧、超时、行/总字节上限返回失败。默认上限是探测器测试值，不是Agent/生产SLO。输出不含URL、body、header原值、event id或cursor，只含HTTP状态、事件/心跳/字节数与接收时长。

成功仅说明这次GET观察到了所需帧数。它不解析事件业务schema，不证明代理链路flush/no-buffering，不证明游标回放幂等、原Run恢复或取消执行；这些要用真实MAAS-20/QA轨迹独立验证。客户端关闭连接只证明探测器释放连接，不等于模型/工具已停止或财务held已释放。观测时限覆盖body，连接/响应头另用idle timeout；不将长时间无事件当作业务成功。

## 后端交付后的最小装配核对表

1. **持久层与身份**：确切迁移版本/文件摘要、schema变更兼容、Session授权上下文/数据保留及独立runtime/migration角色。存储必须保留有序event、checkpoint、未决tool_call及原子状态推进，runtime不执行DDL、不读取迁移凭证；复用MySQL和既有连接工厂，不另建计量账本。原账本tombstone、request、未知held和slot保留规则不变。
2. **模型及工具策略**：真实配置消费入口、批准profile/tool_calls能力协议版本、ModelClient的Go/Higress路径、每子request唯一预算结算、步数/时间/工具timeout/输出大小/累计预算限制。工具名/version/schema/权限和批准政策须来自可审注册表；不把模型参数作为授权，不默认shell/文件/MCP/子Agent或外部副作用工具。
3. **流与恢复**：批准Session/Run/API/事件cursor的路径和schema、单session并发策略；只重放已持久event，重连不能重启模型或工具。暂停等待批准、重复/过期批准、取消传播、执行实际终止分开记录。重启后从原checkpoint及原tool_call身份续接，未知副作用保持待确认，不自动重试不确定写入。
4. **启动与关停**：原后端交可编译入口/命令与受控ModelClient参数后，运维更新实际Chart/env/Secret引用，不只填写metadata。就绪分别检查会话存储/迁移、工具策略、模型依赖；普通Chat可服务与某模型Callable分别报告。停止先阻断新run、取消/排空当前任务，保留checkpoint/event及未决执行，等待可信事实再清理；临时验证使用专属目录、PID、日志，按记录句柄关闭，不停止他人服务。
5. **日志与验收**：关联session/run/step/tool_call和每子request_id、publication/epoch；禁止记录消息正文、工具敏感输入/结果、session cookie、Key/DSN/完整错误body。事件回放本身不产生新的usage。按实际sink配置访问/保留期，不捏造RPO/RTO。首期受控模型+真实只读/纯计算工具结果与真实批准来源分开取证。

当前没有.multica/environments.toml；未因本轮创建长期服务或给出持久URL。将来如仓库声明环境，用运行时CLI的env start/stop按TTL管理。当前现有workbench运行不被本轮停止或替换。

## 来源锁与当前验证范围

本轮按代码提交→python scripts/lock-unified-source.py→四锁独立提交交付，PR目标为统一分支，Merge commit保留祖先。复用scripts/assemble-workbench.py导出固定快照及workbench-sources.json；不从后端个人工作目录拷贝未提交代码、旧前端或手填sourceCommit。

新增测试在专属短期loopback HTTP服务器验证传输/脱敏/边界，测试在同一次前台调用关闭服务器、线程及连接；不是MAAS-20应用启动或真实Higress/模型验收。模板/Secret没有变动，不重跑历史Helm安装或把旧结果记本轮。Agent入口/迁移/事件schema/策略到达后，再按确切SHA补Chart、权限、真实持久化重启/回放与取消验证。生产账户、目标集群、付费资源、模型权重和外部工具不因本轮工具测试开放。

## 已到达的后端最小建议（非已实现接口）

MAAS-20评论01a1f1dc-439a-7380-899d-21e70f901f12提出原生Go核心、/api/agent/v1、单session单活动run、提交client幂等key、单run单调持久cursor、JSON/SSE同一事件内容，以及text-v1/tools-v1显式能力。checkpoint遇到模型在途或副作用工具结果未知进入needs_confirmation；首批工具为整数计算与受授权模型目录读取。后端记录Harness参考commit为2e39e70496aa02986ca6a820c5d497e816b69d7e，本轮仅引用其交接记录，没有独立验证该参考仓库或引入sidecar。

上述仍由MAAS-2核定字段/路径并由MAAS-20交代码。现有Ingress /api前缀在路由层可容纳建议路径，但监听/认证/事件超时/游标传递及服务端取消尚未验证。单调cursor不自动等于Last-Event-ID输入；CLI的--cursor仅在实际服务明确消费该头时使用，否则先使用无游标的GET观察。没有相应迁移/运行consumer到达前，不将这些建议写成环境变量或已批准生产策略。
