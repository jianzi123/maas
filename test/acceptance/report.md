MAAS-7 本轮独立复验报告（2026-11-05 UTC）

结论：原 35 个数据库/受控传输场景独立复跑通过；新增 8 个 QA 场景中 5 通过、3 失败，形成两项问题，其中 usage 保留/权威性需架构收敛，超时分类差异已确认。A01–A34 均未通过完整运行验收，MAAS-7 继续 in_progress。没有产品实现改动。

## 环境、版本和证据口径

| 项目 | 本轮实际情况 |
|---|---|
| 产品基线 | PR #2：4f3eb9358f26ebab637a549b795651171d3b924f；含 PR #1：630225697b8fcdd5e4d2f3ccd2a232e4d6b5259a |
| 隔离方式 | multica repo checkout 创建独立 QA 分支；改动仅 test/acceptance |
| 运行环境 | WSL Ubuntu-22.04、Linux/amd64、Go 1.26.0、MySQL Community 8.4.7、Redis 6.0.16 |
| 临时依赖 | 从既有获准便携缓存复制至本任务 .cache；MySQL skip-networking/mysqlx OFF，Redis port=0；独立 socket/datadir |
| 合成数据 | 模型 synthetic、TST 币种/价表、预算、批准档和身份均为夹具；不代表真实默认配置或价格 |
| 静态环境 | Windows Python 3.13.9、jsonschema 4.25.0；草案 0.4.2-draft.1 |
| 协议 | 私有票据 v3、终态 3.0；D1 3.1 未切换 |
| 执行限制 | 未调用供应商/真实模型、写目标集群、使用 GPU、下载权重或付费压测 |

数据库与业务 SQL 是真实实现；原发布 13 项仍使用其历史核心/证据夹具，新增内核等 22 项使用真实核心实体表。Proofs/H1–H4/validation producer、批准 profile 和大部分 rate gate 为夹具；其中一个独立场景使用真实 Redis。relay 的 httptest server 替代 Higress。不能把这些证据外推为真实 Higress 路由、模型停止或端到端通过。

## 执行结果

| 检查 | 实际结果 | 原始记录 |
|---|---|---|
| 原发布组 13 + 内核/权限/relay/Redis 22 | 35/35 通过；最终隔离复验发布包 8.243s、内核包 19.241s | qa-mysql-baseline35.txt |
| QA 独立边界 8 项 | 5 通过、3 失败；初跑与定向复测同类差异复现。最终 oracle 明确不把 usage 分片当退款授权 | qa-mysql-final.txt |
| go test ./... -json -count=1 | 50 个通过测试事件、23 skip、0 fail，含子/父测试事件；34 个通过顶层测试，7 个包通过；cmd/operator 无测试 | qa-go-regression.json |
| 性能工具离线 unittest | 41/41 通过，4.569s | qa-summary.json |
| 草案独立静态检查 | 80/80 通过：17 份文件清单摘要、35 个原正反样例及 28 项 QA 断言 | qa-contract.json |
| 临时依赖清理 | 四个记录的 datadir 均消失；本任务 MySQL/Redis 可执行路径下无存活进程 | qa-cleanup.json |

23 个默认 skip 是无 socket 的数据库入口，不算 SQL 通过；上表 35 项另有临时真实数据库记录。父测试事件不重复计为独立场景。QA 定向运行未执行发布组，输出的 no tests to run 不算发布通过。用例耗时不是模型延迟或吞吐；本轮未测请求级 p95、吞吐、服务错误率或性能收益。

## J01、FE-R02/03 独立结论

草案 ZIP SHA256：fa855fbc97dc91edc32c0945238fcfce8dff50ed2a10ff809ad58bfa662dbfa8。原 v0.4、D1 基线、勘误及所有包内清单项保持摘要一致。独立脚本没有重跑作者的 115 项、历史 128/24 项或原建包器，也未执行 OpenAPI HTTP 装配。

- J01：创建说明已移除 100/日默认；budget_policy 及三个维度必须显式给出；合法字符串 0 与 null 区分正确，Usage/预算旧 Schema 保持一致。表单和真实管理 API 未验，不能关闭整个 J01。
- FE-R02：原 CR UID 历史、删除/替换/未知状态禁止 eligible、回滚 UID 前置的兼容形状及管理会话保护符合草案。未知写 ACK 无可信 operation.id 时保持未知、无自动重放，文档边界明确。实际历史来源、cursor 稳定性、回滚 409/503、引用审批及 K8s UID 竞争均未运行。
- FE-R03：recorded 恰一行，unknown 为零行/data_complete=false，next_cursor=null；旧普通列表、错 ID 和不合法组合由相应形状/离线语义拒绝。跨日期窗、最终拒绝/保留期权威证据、权限 401/403/404、主库 503 与原 slot allocation 投影仍需真实读端。合成语义谓词不是服务端实现。

当前基线无运行中的管理/精确查询 API，未执行 HTTP probe。已交付可直接运行的只读入口 probe_admin.py，要求通过安全渠道提供管理 Cookie、可信原 request_id 和原 CR UID；503/权限/跨日/未知写入须用批准夹具和故障条件另验。没有把 404、空列表、CR 当前状态或 slot 释放推断成原操作成功、未发送或 held 可退。

## 新增问题与复测记录

| ID / 严重度 | 可重复触发、实际结果与影响 | 最小动作及关闭证据 |
|---|---|---|
| QA-001 / P2，验收差异待架构决策 | relay 已解析 usage=输入12、输出7、总19、缓存4、推理3，随后 EOF 或客户端写失败；terminal.usage 全 null，missing_reason 却为 interrupted_before_usage/cancelled_before_usage。观测值及“确已收到”的事实丢失。Token held=140 是保守占用，本轮未证明财务扣量错误 | 架构确认该 profile 的快照是否为最终权威值及其保留位置；后端保留已收到的观测/正确原因，并在终态 3.0、受控独立观测和财务 held 的边界内处理。分片不自动授权退款；证据不足仍 held。若不采用终态字段保存，应先明确其他持久投影并调整 QA oracle，再复验，不以未经对齐的 3.1 绕过 |
| QA-002 / P2，已确认分类缺陷 | 先完成合法准入并发出首片，再到达原硬截止（夹具 500ms）；relay 持久 result=interrupted、对应 owner_lost，而非 timed_out/upstream_timeout。错误分类影响请求状态/查询及故障分析，未见额外上游重放 | 后端区分 sendCtx deadline、显式 cancel、传输 EOF；全部失败分支仍只结算一次、不发正常 DONE。复测首响应前/后截止、父 context deadline、显式取消、EOF、已有 usage、财务 held 与 slot，提交实际 SHA |

定位：internal/kernel/relay.go:234（writer 失败重置 usage）、241–245（EOF/截止分支）；独立入口 test/acceptance/kernel_cases_test.go.in 的 TestQAUsageBeforeTransportLoss 和 TestQADeadlineAfterHeaders。

最终复测请求 ID：

| 场景 | request_id |
|---|---|
| QA-001 EOF | f1ff31ce-9062-4d82-ab23-a3126002bbef |
| QA-001 写失败 | 376d6765-54ed-40a1-abc4-68a5393d3ae0 |
| QA-002 首片后截止 | 2288a1fa-3774-4d7f-9a9f-0a1c86578aa0 |
| 并发终态/旧 slot | 3a5b5a44-ffd9-43ae-8126-8ae0b8face39 |
| slot 复用后的新请求 | 03e6c7b4-6c48-4796-8608-f384e4edb115 |

通过的 QA 场景为：双 Store、预先 1 次后 10 个并发尝试仅剩 1 次成功；10 路重复同终态仅一条事件/汇总且迟到旧证明不释放新 allocation、不退 held；来源、publication、预留各自篡改均零 request/预算/耐久 rate 见证写入。Store 副本不是 OS 进程多副本，writer 失败不是浏览器，fixture 关闭证明不是实际模型停止。

## 交接及未执行范围

matrix.md/matrix.json 从 MAAS-1 v0.2 + v0.3/v0.4 逐项保留 A01–A34；没有任何完整 A 项被标通过。C02–C04/C07/C08 的部分新 SHA 实现已有局部 SQL 证据，可复用；C05/C12–C14 的真实 producer/Secret 通道、候选 validation 与 Redis 全量重建依然未闭合。P/A/S ACK 测试是 COMMIT 后 driver 注入，不是网络包丢失/DB HA；跨 UTC、OS 崩溃、备份恢复未执行。

原架构师在 MAAS-2 现有清单收敛 QA-001 及 FE-R02/03 运行门槛；原后端在 MAAS-3 原 PR #2 修复/反馈 QA-002 与 usage 保留方案，本角色按交回 SHA 独立复测，不接管实现。MAAS-8 继续主责 Helm/版本/实际 RBAC，本角色独立见证安装/升级/回滚/排空；MAAS-10 继续主责 E1–E3 和模型/GPU 性能，本轮只复用离线方法，不建立第二套性能结论。

尚未执行：真实 H1–H4/路由/Secret/RBAC/validation、DeepSeek/Codex 及真实内网模型、浏览器完整闭环、完整管理/统计 API、真实集群 Helm/CRD/CEL、GPU/LWS/SGLang、E1–E3 和任何付费压测。真实恢复与容量仍需实际证据，安全隔离不能代替恢复通过。
