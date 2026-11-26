# 正式ModelClient消费输入 v0.9

本轮在统一远端`4402c456a155646ee4111e5f4a1f285621c11273`（PR19已合入）续接，保留原v0.7/v0.8/`037be34`完整祖先，不回到8db重做方案。算法只改`tools/model_capabilities`及本文；正式ModelClient、App、Relay、Service、数据库、公开AR-1契约均由原MAAS-20/2维护。本轮不是生产客户端的第二实现。

## 可直接消费的产物

| 文件 | 消费方式与边界 |
|---|---|
| `http-vectors/consumer-map.json` | 原45向量ID/规范摘要→具体源解析/ModelClient/Service/序列化断言；原向量未改 |
| `http_tool_vectors.py` | 45向量经真实loopback HTTP/SSE读回，仍复用v0.8严格状态机；每次POST保留请求、原child绑定、body摘要和实际回填 |
| `http-vectors/consumer-cases.json`、`consumerprobe/`、`run_consumer_probe.py` | 实际Go导出接口的12组消费断言：tools/text能力门、原Registry/Schema/两真实工具正反例。目录数据生产者为受控注入，不读真实账户 |
| `http-vectors/feedback-case.json`、`provider_messages()` | 原AR-1内部UUID→供应商source_call_id的回填oracle及拒绝断言；未接正式prepare |
| `http-vectors/runtime-input-gaps.json` | 复用EXT-01–06的逐字段输入与仅剩真实验证缺口/责任；不创建第二批准源 |

`turn_reader`是v0.8回放器新增的受控输入接缝；默认离线行为保留。HTTP测试服务只绑定127.0.0.1/随机端口，结束时关闭并join全部线程；无可配置外部URL、代理、重定向、凭据或重试。每个响应实际以1/5/2/13字节写出并flush，客户端逐字节读，覆盖UTF-8分片。`_controlled_binding`仅夹具字段，**不能作为正式上游body字段**；后端应在可信调用上下文/原request和票据中绑定。

独立8项真实传输控制：429、302不跟随、错误Content-Type、有界body、客户端关闭、持续心跳下绝对总截止、idle超时、无重定向目标请求。原45向量中的fixture end/cancel/time标签仍只是受控元数据；另8项才包含实际HTTP时间/关闭行为。客户端关闭不证明供应商任务退出或slot/预算可释放。未以HTTP200/DONE给出任何结算权威性。

## 当前正式实现与具体差异

| 已核位置 | 已实现事实/可复用 | 本轮给MAAS-20的具体消费动作 |
|---|---|---|
| `internal/app/models.go` Resolve/Supports/prepare | 只有text-v1，agent/tools拒绝；原publication/Profile/Key/Plan/ticket/body/原子request绑定已在正式路径 | 工具profile与显式模式需在同一prepare/受保护路径装配，不直接连供应商；不删text-v1能力门 |
| `internal/agentruntime/kernelmodel/relay_model.go` | Supports对tools-v1返回ErrCapability；Generate在Prepare前拒绝；writer读取公开文本流 | 正式工具payload需要架构核定的版本化桥，不能先被文本序列化丢掉再猜工具调用。Go探针验证原门而非实现工具解析 |
| `internal/agentruntime/service.go` Drive | 整批Lookup/permission/selectedTool/Canonical/Schema在工具执行前完成；现有protocol.Canonical已拒绝嵌套重复键，不是新缺陷 | 源侧先完整拼接再交RawMessage；不要先decode成map抹去重复键；原有批次校验继续复用，不接管Loop |
| 同上 Call与Message持久记录 | 返回的供应商Call.ID随后成为Call.SourceID，Call.ID换内部UUID；assistant/tool Part.CallID都为内部UUID | **下一请求必须经Step.Calls把内部ID映射回SourceID**。不能直接把Part.CallID当provider tool_call_id；完整历史亦须匹配原run/source/profile/参数和completed结果 |
| 同上 Usage/TerminalConfirmed | 原child终态权威成立后可先保存Usage，后续工具参数错误不抹掉已消费；OutcomeUnknown进入needs_confirmation | `Response.TerminalConfirmed`只能来自原耐久终态。HTTP/SSE候选usage不能直接填为账本投影；finish=tool_calls只结束本模型child，下一child另ID/准入 |
| `internal/kernel/relay_forward.go` | 原finish/DONE/EOF/usage冲突和取消原因锁存，最后原Finalize；公开文本子集严格 | 版本化tools桥必须贯穿原准入/正文签名/计量与有界终止；不能只改最外层客户端或放宽旧公共Schema |

另一个实际不匹配：v0.8的`sum_ints`/`echo_text`是oracle示例工具，正式Registry是`bounded_arithmetic@1`与`list_visible_models@1`。前者正式参数要求a/b/**op**，返回字符串`"40"`；原示例`{"sum":40}`不能原样当正式结果。后者按可信Principal读目录，无`text`参数，不能把echo样例冒称该工具。CP08/09明确拒绝旧名和缺op；CP05用正式两工具与真实Schema运行，目录结果仅是受控可见模型。

回填oracle要求完整assistant请求后恰好每调用一条tool结果；只有完成记录可回填，未知/外run/外source/歧义/修改参数或结果均拒绝。它不提供执行权限，也没有数据库幂等/恢复证明。正式实现需从可信原Session/Run/Step读取这些关系，不能信任浏览器提供的call_records。

## 最新来源核验与真实验证缺口

官方资料本轮重新抓取于**2026-11-26 UTC**，四页完整字节/捕获时刻/SHA见`http-vectors/source-evidence.json`。本轮仍只提议DeepSeek ExternalAPI，文档`deepseek-flash`映射`DeepSeek-V4.1-Flash-1017`，工具指南展示显式`thinking.type=disabled`的函数工具请求/结果流程；这是当前文档事实，不是账号型号/不可变服务版本或工具profile批准。[型号/价格](https://api-docs.deepseek.com/quick_start/pricing/)、[工具](https://api-docs.deepseek.com/guides/tool_calls/)

Chat页仍定义按index拼接函数arguments、最终finish同片usage与DONE；未见可依赖的`parallel_tool_calls`参数或真实并行保证。本轮双调用交错只是受控形状；生产执行顺序/数量、来源最终性/取消保证须在准确profile批准。[Chat API](https://api-docs.deepseek.com/api/create-chat-completion/)

本轮新增的时间差异：价格页明确自2026-11-18北京时间12:00起，**模型触发的服务端搜索/抓取不再按次收费，其返回上下文仍计模型Token**；独立Search/Fetch API收费另列。原v0.7“未覆盖的非零server工具费用”是历史观察，不能当当前计费保证。本轮仍拒绝未声明server工具，理由是超出已选函数工具能力/上下文批准，不能仅因“不另按次收费”自动开放；网页价格和1M/384K文档上限均不写入已批准价格或BoundVerified。[当前计费说明](https://api-docs.deepseek.com/quick_start/pricing/)

真实调用仅余的可执行输入：①准确获准账号/站点/model/显式mode、工具capability/profile/adapter修订及有效期；②全部计费输入/输出的可信上界、真实final/有界结束观察、生产first/idle/hard/end_wait和批准价表/币种/精度/有效期；③平台Key/上游Secret/Higress TLS和票据/producer身份的**非秘密引用**及实际publication/source绑定；④允许请求数/Token/金额/窗口/停止条件与验证目标环境。沿原EXT-01–06/I01–I06给批准记录或渠道即可，不重复询问已确认的DeepSeek优先方向，不读取Owner秘密。本轮未查/models、余额或真实调用端点，真实供应商调用0。

Harness继续仅固定参考`2e39e70496aa02986ca6a820c5d497e816b69d7e`，没有安装DSH、将DSH会话当provider或切技术栈。Go/Higress/MySQL唯一准入计量、unknown-held与slot分离保持原边界。

## 复现和接续

现有Python+jsonschema；Go使用**已有Go1.26缓存**，无新安装。仓库根目录：

    python -m unittest discover -s tools/model_capabilities -p test_http_tool_vectors.py -v
    python tools/model_capabilities/http_tool_vectors.py --output <output>/http.json
    go build -p=1 -buildvcs=false -o <output>/consumer-probe ./tools/model_capabilities/consumerprobe
    python tools/model_capabilities/run_consumer_probe.py --binary <output>/consumer-probe --output <output>/consumer.json

另对本轮新增turn_reader接缝执行原tool_calls专项回归；不重跑旧全仓/GPU/安装矩阵。准确SHA、最终运行命令/退出码和原始报告在delivery-verification.json随包。Go探针不是正式Service.Drive/SQL集成；HTTP服务不是生产Higress/mTLS/供应商。正式bridge接好后由原后端/QA在同原子request/计量链上消费矩阵验证，不能把本包的53项转登记为生产ModelClient已支持。
