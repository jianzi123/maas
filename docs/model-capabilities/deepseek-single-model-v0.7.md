# MAAS-18 DeepSeek单来源适配输入 v0.7

本轮只收敛首个ExternalAPI来源，供架构/后端/QA审定并实施。沿用已确认DeepSeek优先方向，**提议 deepseek-flash＋显式non-thinking＋纯文本Chat Completions**；精确模型/站点/模式尚无批准记录，提议不是成员选择或调用许可。私有部署、SGLang及GPU研究保留原任务/授权，本阶段不增加候选或重做旧检查。

基线为本次远端读取的统一分支 agent/MAAS-10-offline-metrics / 8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a；原a7b6564已是祖先。原分支成果保留，新增工作在隔离增量分支。MAAS-18要求同一Go/Higress/唯一结算链完成声明/发布、Key/预算、浏览器流式、停止/错误、原request_id与非空/未知用量；此文不把输入核验等同闭环已通过。

## 1. 现有批准与本轮复用

读取MAAS-9已交v0.6两卡、MAAS-18说明和本批MAAS-2交接。原卡EXT-01–06共34字段的approved_value均为null；本包 approval-inputs.json逐字段保留名称、原责任、阻塞操作、批准引用缺项及原附件SHA256。null只表示本次所读记录未提供，不断言别处绝无批准。没有读取Owner配置、API Key、账户余额或环境变量秘密；没有调用供应商/models或生成端点。

不重复请求首期范围或DeepSeek优先方向。Mika只需汇合已存在的记录，必要时补以下四组具体输入：

| 缺口组 | 对应原字段及原责任 | 阻塞动作 |
|---|---|---|
| 精确来源/获准模型与模式 | EXT-01全部；EXT-02的profile_id_revision_approval、profile_expiry_invalidation；成员/Mika确认，MAAS-9核能力，MAAS-3/8绑定site/endpoint/source_id | 不选择真实上游或登记可调用profile；动态网页型号不是账户准入 |
| 上下界和真实adapter语义 | EXT-02其余字段；MAAS-9/2审定，MAAS-3实现、QA复验 | 不开放相关硬预算/最终结算或将clean EOF夹具变成可信终止 |
| 安全渠道与版本身份 | EXT-03/05/06；MAAS-8给非秘密引用与运行范围，MAAS-3装配原工厂/真实Higress/Secret/validation与DSN身份 | 不取凭证、不执行生产发布/验证；原对象存在或202不代表Callable |
| 价表、额度与停止条件 | EXT-04全部；成员给记录/上限，MAAS-9/3核分类与数学，运维注入验证Key引用 | 无获准供应商调用次数/Token/金额、期限/并发/超时，故不执行真实样本 |

最低需要给记录ID或任务链接；Secret只提供批准的namespace/name/key或安全渠道引用，不给原值。已有本地GPU研究授权不扩大本表的真实API费用/平台目标环境授权。

## 2. 本次官方核验事实（不是运行批准）

七个官方文档快照的时间、字节数、SHA256见 deepseek/document-evidence.json，实际抓取UTC时间在该文件；没有查询账户API。浮动网页没有可伪造的immutable服务commit。

- 模型目录/价格页当前列 deepseek-flash 与 deepseek-v4-pro；本轮主提案只用前者。网页将deepseek-flash映射为DeepSeek-V4.1-Flash-1017，目录示例context_window=1048576、max_output_tokens=393216。它们是文档声称的能力，不是本账号可用型号/有效上界；服务别名可漂移，旧别名可能已重定向到新模型/价格。[Models](https://api-docs.deepseek.com/api/list-models/)、[版本/价格](https://api-docs.deepseek.com/quick_start/pricing/)
- Chat的model/messages、max_tokens及stream形状可作为本接口适配起点；thinking默认开启，必须在可信adapter显式设为disabled，不依赖供应商默认。非thinking提案禁止tools/搜索/多模态/额外自动功能，公共ChatRequest仍只允许已有model/messages/stream/max_tokens/temperature；thinking和stream_options只在可信层固定。[Chat](https://api-docs.deepseek.com/api/create-chat-completion/)、[Thinking](https://api-docs.deepseek.com/guides/thinking_mode/)
- 文档max_tokens范围1–393216，平台现行公共上限4096；真实有效上限仍取平台与批准模型上限的较小值，必须明确传给上游，不能遗漏后接受上游更大的默认输出。输入/输出总长度受context约束；字符近似换算不是可信Token上界，旧tokenizer demo也不能自动证明当前服务模板/版本。[Token口径](https://api-docs.deepseek.com/quick_start/token_usage/)
- 输入cache hit/miss合计为prompt；prompt_tokens_details.cached_tokens与prompt_cache_hit_tokens是别名，二者同时存在须一致。reasoning_tokens是completion子集；新safety_tokens同样已包含在completion，不再加到总数。non-thinking提案若出现非零reasoning或reasoning_content，先作为模式漂移拒绝，不把模式名当事实。额外server_tool_use非零意味着出现本阶段未覆盖的费用路径，拒绝/失效而不是忽略。[Usage](https://api-docs.deepseek.com/api/create-chat-completion/)
- 单价区分输入缓存/未命中及输出，网页还区分峰谷时段，价格可调整。运行价表必须冻结批准币种/定点精度/source/model/有效期/时段和最坏类别价格；本轮price_snapshot=null，不把网页美元数或TST测试价装成实际价表。[Pricing](https://api-docs.deepseek.com/quick_start/pricing/)

### 上下界审定条件

input_upper_tokens/output_upper_tokens与bound_verified均未批准。若日后以硬context C作为全部计费输入的保守I_up来源，须先证明该准确模型/模式的所有计费输入均被C涵盖，且无工具或隐藏附加调用。O_up须覆盖全部计费输出并由实际adapter保持cap；不能只约束可见答案。即使接受I_up=C，也不可擅自假设I_up=C−请求max_tokens，实际输出可以比cap短；原Go计划按独立上界相加可能保守过预留，应如实展示，不改数学去制造可用额度。

预算仍为I+O，cache/reasoning/safety子集不重复加。金额用互斥类别加和后一次向上舍入，预留取最坏分类价；峰谷跨界、价表到期和供应商版本漂移需由价格/profile有效区间及准入失效策略处理。必要分类缺失且异价则金额未知，不能擅自选便宜价；实际可知Token可按原规则独立结算。所有这些只是审定条件，本轮不把任何文档数字填入approved或BoundVerified。

## 3. 拟审定的单来源协议

| 项目 | 本来源事实/拟定规则 | 当前核对与尚缺 |
|---|---|---|
| progress/final | DeepSeek文档中，include_usage=true时中间usage为null，最后无新内容的非空choices finish分片携最终usage，随后DONE；不使用SGLang的usage-only分片 | 23向量已可执行。任何非null进度usage视作来源/profile漂移，不以单调17→19推定最终，也不悄悄套cumulative_until_finish |
| error | HTTP非200单列；HTTP200中的顶层error或流内error锁存，后续DONE不能恢复成功；不自动重试、hedge、重定向或跨来源回退 | 源检查器覆盖；真实错误净化、动作/诊断与一次终态由原后端/QA闭合 |
| 结束 | 必须有合法stop/length finish、DONE及实际被接受的流结束，并在本请求有效deadline内、没有取消/错误；尾随data或第二finish在同一wire中拒绝 | 所有生产first/idle/total/post-final-drain数值仍null。工具中的clean和100ms是夹具，不是实际可信观察/默认值 |
| keepalive | 文档有SSE注释/非流式空行；它们不是token或可见首内容，不能延长总deadline | 文档的“尚未开始推理10分钟则关闭”是供应商排队规则，不能当平台总超时或GPU停止证明。[Rate/keepalive](https://api-docs.deepseek.com/quick_start/rate_limit/) |
| 取消 | A08保留2秒内发出取消/关闭动作；供应商是否停止推理/收费仍unknown，未知usage保持原held | 需要原R、publication/实例/原slot tuple及真实传输证明；slot释放不退款，后继请求成功不证明原供应商任务退出 |
| 重复 | 同一wire第二finish一律拒绝，即使计数相同；内部已持久终态同event/hash幂等、异payload或换event冲突409 | 区分源线协议与内部幂等；不能为了复用旧向量放宽已发公共结束顺序 |
| 非流式 | 容忍合法JSON前空行，但要求固定模型/原响应ID、单assistant文本choice、合法finish和usage结构；顶层error不能当成功JSON | DS20–23覆盖正常、error、429和取消；没有真实模型发包 |

### 与统一基线代码的最小差异

8dbf99e的 internal/kernel/usage_authority.go 已有final_only和cumulative_until_finish及冲突检测、缺policy时diagnostic-only，现有策略实现应直接复用。relay_forward.go对同一分片先observe usage再normalize/finish，符合候选final与finish同片的处理顺序；它也已拒绝同流finish后choices和DONE后data。

**拟选final_only仅是必要条件。** 它把“收到的usage”视为final，无法独自证明该usage位于本来源合法finish分片；真实adapter必须先验证源shape及模式，再交给内核。还需显式核cache双别名一致性、safety子集和非零工具费用：当前parseUsage只读nested cached/reasoning，不能由这一段代码推导别名/工具费用已检查。是否由受控adapter先完成这些校验或给原parser最小增量，由MAAS-2/3审定；本轮不复制账本或修改内核。

公开成功Usage仍投影原成功终态，diagnostic不进账，错误/EOF/取消/截止不能补成功DONE。迟到在已提交终态之后只审计，不重开请求；这和“同一尚未成功提交的原wire在DONE后继续发送data”不是同一情形。原v0.5允许后边界观测仅审计是离线规格，不能拿它绕过当前relay的同流严格检查。终态3.0/Observation1.0保留，D1/3.1未切换。

## 4. 最小质量/兼容入口

本包 deepseek_milestone.py是严格离线检查器，没有网络客户端/Key读取/模型调用入口。质量输入minimum-quality.json只留Q01算术、Q02实体JSON、Q06 Unicode，先用合成gold/截断负例检验评分规则。拟真实最小质量集为3题×流式/非流式两模式；这6次只是样本提案，allowed_validation_call_count_and_spend仍未批准，实际执行次数为0。

真实阶段必须通过同一Go→Higress入口，保留原request_id、模型/模式/profile、实际采样/输出cap、正常finish和原终态Usage/预算查询。length算截断、不作正确完成；EOF/取消/错误单列，不暗中加cap补测成通过。生成答案/正文不写常规日志，只在受控合成样本证据中保存最小必要内容。

复现（仓库根目录）：

    python -m unittest discover -s tools/model_capabilities -p "test_deepseek_milestone.py" -v
    python tools/model_capabilities/deepseek_milestone.py --output <task-output>/deepseek.json
    python tools/model_capabilities/deepseek_milestone.py --source-root <本轮公开文档缓存> --output <task-output>/source.json
    python tools/model_capabilities/deepseek_milestone.py --require-approved-inputs

最后一条预期退出2，不产生/覆盖成功报告；它不提供运行许可。默认只读本包JSON、原公共Schema和既有方法，不安装依赖、不重跑旧KV/CPU/GPU或全仓审计。各向量保留完整HTTP类型/原绑定/原始UTF-8 SSE或JSON、人工预期和模拟时序；actual_provider_run=false。报告不输出凭证或正文。

## 5. 本轮验收与下一步

本轮可独立完成：官方事实快照、34字段批准清单复用、23个单来源协议向量、质量方法正反检查、与真实Go实现逐项差异及严格缺证据门禁。**尚未共同批准adapter或执行真实调用。** MAAS-2/3及原QA需要确认：来源最终标记→现行UsagePolicy修订映射、真实有界终止与首次原因、双别名/额外费用处理、profile/价格失效及原证据门槛。Mika汇合缺失输入后再进入MAAS-18对应获准真实验证；不让本输入复核阻塞可独立的Higress/身份/控制台受控装配。

本次新增隔离分支以8dbf99e开始，代码与四锁按标准流程分开提交；所有批准/部署flag不变。精确SHA、运行命令/退出码、原始日志和未执行项随delivery-verification提供。当前本机原生Go为1.23.1，目标模块要求1.26.0；本轮没有为算法输入重复安装/构建工具链或把v0.6已有两项Go测试当新结果。Python专项运行是本轮新增实证，不是SQL/HTTP/浏览器/供应商/质量效果验收。