# C08：AR-1 draft.2 实际受控装配

组合依赖：后端PR #18 head 19e43ba980f1bd9f499a92dda435b74b626bf7e9（代码39462c6a），部署PR #16 head8326e56，统一base8dbf99e。隔离树用merge保留两者祖先，不修改内核、不把未合入候选称默认分支。最终代码和四锁摘要以本轮交付报告为准。

## 真实消费与本地入口

```sh
go build -tags agentcontrolled -o .cache/agent-controlled ./cmd/agent-headless
.cache/agent-controlled --state-dir .cache/ar1-owned --owner-id 4c421973-919f-4b8a-997f-909fc6fd010a --listen 127.0.0.1:4188
```

仅在确认端口空闲及该状态目录属于本次实例后启动。owner为明确测试UUID，模型alias=demo、source=controlled-local、revision=1、capabilities=controlled；两个真实工具为bounded_arithmetic@1和list_visible_models@1，不配置供应商Key。进程参数实际消费state-dir/owner-id/listen/contract；不新增Agent环境变量。contract默认指docs/contracts/agent-runtime/ar1-draft2/openapi.json。

原POST /__maas/local-session消费精确Origin，Cookie/CSRF留客户端内存；写API带原X-CSRF-Token和必要If-Match。集成workbench时必须把同一个LocalSession和可信Principal传给NewARHandler；两个端口各自签发同名maas_session不是统一登录。本轮独立listener不声称已与前端统一宿主。

## 时限与事件

该listener实际WriteTimeout=25s、ReadHeaderTimeout=5s、ReadTimeout=10s、IdleTimeout=30s；NewARHandler的StreamWindow=20s。旧15秒描述只适用于原control-api/workbench，不覆盖此入口。ARHandler内部50ms tick重查授权/状态，但**没有周期comment心跳**；tick不能冒称客户端收到心跳。终态和needs_confirmation发送持久包络后关闭，窗口到期断流仅为订阅边界，客户端沿最后cursor GET恢复，不新建run。

JSON /events与/events/stream来自同一持久包络；SSE id=cursor，after与Last-Event-ID同时传400。原event_stream.py仍只证明有界传输，本轮verify_controlled.py额外验证真实存储、同Run子ID、快照水位、原包络重开及只读回放。没有通过修改全局超时假装完整运行。

## 持久化、权限与恢复

agentcontrolled入口用LocalStore，目录独占.owner-lock、不可变文档/fsync、.pagination-key保存在目录中，正常SIGINT退出后释放锁；重启保留原目录和同owner。不要把.pagination-key、Cookie或原始state文档加入日志/附件。崩溃锁不自动抢占，确认原PID已停止才由安装方按既定流程处理。旧model/tool在途恢复为needs_confirmation，不自动重放；本轮正常停机重开已完成Run，不代替崩溃故障验收。

MySQL真实实现/迁移已到：internal/agentruntime/migrations/001_sessions.sql和agentruntime.Migrate，单表agent_sessions_v1聚合消息/事件/checkpoint。运行只需该表SELECT/INSERT/UPDATE（可再按实际SQL收敛UPDATE列revision/document）；无需DELETE/DDL或业务账本写。Migrate是显式函数，不是新增CLI、也没有自动启动迁移，现有agent-headless只消费文件目录而不消费DSN。生产迁移须独立身份、同恢复点保留消息/事件/原消费/未知held；应用回滚不倒库、去checkpoint或删除分页key。

作者已用便携MySQL8.4.7运行SQL/原Admit-Finalize计量场景；Windows skip不覆盖其WSL成功记录。本轮只独立验证文件存储和listener，未对生产SQL身份/default roles做GRANT或验收，不能把作者真实SQL结果称本轮身份装配通过。

## 生产适配矩阵

| 接点 | 当前实际实现 | 生产缺口 |
|---|---|---|
| Auth | 原LocalSession与固定测试Principal | 可信安装方身份/会话与统一workbench同实例接线 |
| Catalog | localModels只返回demo及controlled能力 | 实际批准模型/profile/能力版本 |
| Reauthorize | 固定owner/revision/测试权限重核 | 当前真实授权/撤销版本 |
| Counter | JSON字节长度，仅受控模型上界 | 实际模板/tokenizer/工具包装及批准上下文上界 |
| Prepare / Usage / FailureResolved | 原kernelmodel.RelayModel和原账本接点已实现 | 安装方工厂、真实Key/profile/三维预算、Higress/来源批准；tools-v1无批准仍拒绝 |
| SessionStore | LocalStore已由headless消费；MySQLStore及Migrate已交 | 专属生产runtime/迁移连接消费入口及有效权限证据 |
| 工具策略 | 显式测试limits冻结；pure/read两工具，未知工具拒绝 | 安装策略配置与真实授权，无shell/MCP/DSH默认开放 |

## 可复现有界装配验证

Linux或已有WSL运行（状态与输出目录必须是新的）：

```sh
python3 deploy/agent/verify_controlled.py --binary .cache/agent-controlled --output .cache/ar1-ops-evidence
```

脚本自行选择loopback空闲端口，启动唯一自有PID；验证匿名401、原Cookie/CSRF、Session→Agent→两真实工具→completed、JSON/SSE包络、cursor互斥400、快照水位、读取不增加子request；SIGINT停止后同状态重开，重新登录、同Run原事件完全一致，退出后401，最后停止并检查owner-lock释放。取消只验证已完成Run的幂等终态保留，**不声称覆盖活跃取消/未知副作用或模型实际停止**。

raw证据仅HTTP状态/路径/响应摘要、非秘密关联ID和计数；会话凭证只在内存。private-state目录有分页密钥和测试文档，留本地以供复核，不打包；process.log仅此受控入口启动/停止信息。测试进程生命周期归本次前台脚本，不建立长期服务、不占用4188或改其他服务。

本次不新增Chart core启用：agent-headless无生产健康接口、Auth/profile/DSN配置未到，原Chart仍拒绝将受控服务当生产入口。DSH sidecar不安装。来源按代码提交→标准锁脚本→四锁单独提交维护；目标安装、真实模型/供应商、Higress/Secret/validation与付费仍按原条件。

最窄角色建议模板见deploy/agent/session-role.sql，SELECT/INSERT仅原四列、UPDATE仅revision/document；不含DELETE/DDL/业务账本。它尚未执行或被生产工厂消费，不能凭角色名宣称身份已安装。MySQL多用户隔离仍需应用可信Principal/owner检查，不把表级GRANT误作数据库行级隔离。
