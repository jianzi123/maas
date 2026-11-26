# MAAS-20工具能力输入 v0.8

本轮交付可重放的ModelClient工具能力规格、待审Schema和协议正反样本，供MAAS-2核定与原后端MAAS-20消费。后端已有活动运行，已读取其评论`01a1f1dc-439a-7380-899d-21e70f901f12`及前端反馈；本文采用其`text-v1`/`tools-v1`显式能力建议，不创建第二套Agent服务、账本或会话存储。

## 来源、版本与批准

| 项目 | 准确输入 | 证据边界 |
|---|---|---|
| 受控来源 | `maas-controlled-tool-model` / `fixture-set-0.1` / non-thinking；source=`controlled-artifact-only`，profile=`controlled-tools-0.1` | 完整合成SSE，两种真实本地纯函数；无模型推理、供应商或Go/Higress执行 |
| 外部单一候选 | `deepseek-flash` / 显式`thinking.type=disabled` / 文档版本`DeepSeek-V4.1-Flash-1017` / Chat Completions | 延续v0.7提案。账户准确模型/站点/不可变版本与实际工具能力仍pending；不把原纯文本profile升级为工具profile |
| 官方工具指南 | [Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)；[Chat API](https://api-docs.deepseek.com/api/create-chat-completion/) | 文档展示assistant工具请求及tool角色按tool_call_id回填；模型输出参数仍需本地验证。普通函数工具由客户端执行。Beta strict另有来源，不在本提案启用 |
| 版本事实 | [Models](https://api-docs.deepseek.com/quick_start/pricing/)；捕获时间/hash见`tool-calls/source-evidence.json` | 别名/文档可变化；价格、context与生成上界沿原EXT卡批准，本轮不再建批准真源 |
| Harness参考 | [`2e39e70496aa02986ca6a820c5d497e816b69d7e`](https://github.com/deepseek-ai/deepseek-harness/blob/2e39e70496aa02986ca6a820c5d497e816b69d7e/docs/architecture.md)及同提交packages/README | 仅参考可替换模型/工具/会话/循环边界。DSH是宿主应用，DSH CLI会话不能作为MaaS模型provider；未安装DSH或其插件 |

固定Harness与后端本轮选择一致。原生Go ModelClient/ToolRegistry接口可继续复用MaaS鉴权/取消/唯一预算；引入DSH sidecar还需额外会话/身份/预算适配，首期无必要。本轮不修改架构ADR或引入其shell、MCP和子Agent实现。

官方Chat页本次只明确tool_calls数组与分片index，没有`parallel_tool_calls`请求参数/并行保证。本包验证交错的两调用**受控形状**，本地工具按index串行执行；不宣称供应商真实并行能力，不额外发送未列出的参数。若首期adapter选择限制每轮一个调用，应在批准profile配置并拒绝超出数量，不静默丢掉第二个调用。

## 最小工具回合契约

机器Schema为`tools/model_capabilities/tool-calls/turn.schema.json`，标识`maas.model-tool-turn/0.1-draft`，映射后端建议的`tools-v1`。它只是内部归一化回合提案，**不自行发布公开API或RunEvent**。MAAS-2拥有`/api/agent/v1`等路径/事件的最终核定；当前纯文本ChatRequest/Chunk和票据v3、终态3.0、Observation1.0均未修改。

1. 每模型回合绑定session/run/step/child_request/source/profile/model_revision/mode及原upstream响应ID。每个新模型子请求有新的request_id，发起前由原运行服务持久登记；父run只关联/聚合。owner/权限来自可信上下文，不允许模型或请求body提升权限。`text-v1`、未知来源和缺工具批准时，在上游尝试前拒绝，不自动换来源或降级隐藏tool_calls。
2. assistant消息为`role=assistant`，工具请求包含`id/type=function/function.name/arguments`。arguments是原始JSON**字符串**，按choice.index=0与tool.index分开拼接；第一片带id/type/name，后续只追加arguments。不得从半包参数执行工具、以名字归并两个调用、替换ID/名字或覆盖已收到参数。UTF-8跨字节分片先完整解码；限制原wire、每调用参数、调用数及输出字节。
3. 在合法`finish_reason=tool_calls`、DONE与有界可信结束之后，校验整个调用批次。重复ID、负/稀疏/越界index、非法或重复键JSON、NaN、Schema错误、未知/未授权工具均停止；本包不自动重试模型、不编造工具结果。先校验全部调用再执行首个，避免有效第一项掩盖非法第二项。真实工具若有副作用，审批/执行记录/未知结果恢复由原内核实现，本包只运行纯函数。
4. 完整assistant工具请求保留到下一次输入，然后按确定index顺序追加`role=tool/tool_call_id/content`。ID必须一对一匹配原未决调用，每调用恰好一结果，全部回填后才能开下一模型回合。工具结果是数据，不能转换成system指令；浏览器也不可把工具结果渲染为可执行HTML。样本工具为整数相加与受限字符串回显，不读取文件/秘密或执行生成代码。
5. `tool_calls`是**当前模型回合**的结束，Agent还要继续。最终回答使用stop且无未决工具；length为截断，参数即使看似可解析也不执行。aborted/content_filter/insufficient_system_resource、顶层error、取消、EOF、总截止及同wire的重复finish/DONE后data均不能恢复为成功。工具已完成后用户停止，保留已完成工具/原子请求，禁止下一次模型尝试。
6. 沿v0.7所捕获DeepSeek来源规则：中间usage为空，最终同finish片携usage，不套usage-only形状。单调增加不证明最终；缺失usage为null，真实0与未知分开。工具调用生成参数属于该子请求的计费输出；工具结果重发属于下一子请求输入，不额外重复加一份“工具Token”。两回合报告按原子request_id保留独立快照，父run不重复结算。
7. **工具有效性与模型计量分开**：完整模型请求后才发现未知工具/参数无效，不抹掉已经产生的模型usage，也不因工具执行0次退款。Schema和本离线快照没有账本写入权限。真实最终性、硬上下界和故障usage由批准adapter及原内核裁决；未知held/slot/取消动作/实际退出的区别沿原契约。实时工具选择不会提高模型来源或工具执行权限。

实际生产first/idle/hard/end_wait、步数/累计调用/Token/金额、工具超时/输出、registry版本/权限及批准有效期必须显式登记。样本`2工具/3模型回合/256参数字节/512输出字节/1000ms截止`仅为测试限制，不能搬成生产默认。重连/GET事件回放不得再次执行模型或工具；未知写入不可自动重放。**本包不实现或证明SQL检查点、审批、恢复、取消传递与幂等执行**。

## 向量与实现消费映射

| 向量 | 本轮方法证据 | MAAS-2/20/QA后续真实消费点 |
|---|---|---|
| TC01/02/36/38 | 完整工具回填、两调用交错、结果为数据、普通Chat | ModelClient归一化→原ToolRegistry→第二子request→最终答复 |
| TC03–15/33/43/44 | 参数JSON/Schema/字节上限、批次原子校验、ID/结果关联 | 工具选中并不等于授权；不得早执行或编造回填 |
| TC16–18/40 | progress/final/冲突、未知与0、独立子请求usage | 保留原Go唯一结算，未知/部分汇总与真实终态权威性另验 |
| TC19–26/31/32/39/41 | EOF/取消/截止/截断/错误/重复终态 | Run取消请求≠执行退出；模型/工具在途与恢复按原记录裁决 |
| TC27–30/34/35/37/42/45 | 不支持/未授权协议、来源/版本漂移、未知扩展、伪造历史与request复用 | tools-v1批准桥；当前text-v1拒绝，来源固定、参数秘密与身份隔离 |

TC36只证明回显内容保持tool角色，不能证明模型抗提示注入。TC02不证明供应商并行。工具回放是纯本地函数真实执行配合合成源；SSE碎片测试是完整capture的UTF-8/参数拼接测试，非线上流式/网络取消或网关测试。

## 复现与缺口

仓库根目录，现有Python+jsonschema环境即可，不安装模型栈：

    python -m unittest discover -s tools/model_capabilities -p test_tool_calls.py -v
    python tools/model_capabilities/tool_calls.py --output <output>/tool-calls.json
    python tools/model_capabilities/tool_calls.py --require-real-approval

最后一条应退出2且不覆盖报告。原v0.7纯文本检查器继续原严格语义，回归仅重跑受本轮依赖关系影响的17项专项，不重做旧KV/GPU或全仓审计。五份官方抓取的URL/时间/字节/hash保留；文档hash检查只证明该缓存字节，不证明账户能力或语义无误。

待补：准确模型/站点/显式模式与工具能力profile批准、tools-v1公开/内部桥的共同签收、真实final/有界结束证据、registry/Schema/权限与恢复限制、完整计费上界/价格/额度/安全引用。原EXT-01–06/I01–I06继续唯一登记已有输入，不读取Owner秘密。原后端可独立推进受控ModelClient/工具与事件实现；本输入复核不要求等整单设计，也不能替代MAAS-18真实链路或模型质量验收。
