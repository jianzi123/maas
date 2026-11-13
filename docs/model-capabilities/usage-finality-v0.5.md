# MAAS-9 v0.5：Usage进度、最终收据与调度输入

本轮交付三份来源profile、30组完整上游SSE合成向量、3组独立终态重投预期、固定源码函数探针，以及4组decode优先的页约束输入。目标是给MAAS-2/3/QA闭合ALG-D1/P1提供可执行输入；**本轮不修改生产adapter、账本或共享契约，不能据离线通过关闭P1。**

当前分支正常合入统一项目 **925d8c55be9ce823d100bf90a5c78cf19ea66d58**，保留原e614af8及全部产品提交历史。四个产品PR已合并的事实来自最新MAAS-3交付和远端默认SHA，不沿旧PR重复实施。925d8c5的relay.go、relay_forward.go、types.go与原821269b无差异；P1函数没有progress/final输入的静态限制仍在，不将其外推为已复现真实错账。

## 1. 真实源码/文档能证明什么

| 来源 | 具体位置与行为 | 本轮证据/限制 |
|---|---|---|
| SGLang v0.5.6 / 7ae368efde14f0b2abe769a5fbb99b8154b2a9b7 | serving_chat.py:579/634，continuous_usage_stats可给内容分片附当前累计usage；646起输出finish分片，usage=None；703–718独立choices=[] usage分片；724输出DONE | 原函数/配置源码存在，不是该账户模型实际发包。progress和final可使用同一个UsageInfo形状，数字本身无最终性 |
| 同版本UsageProcessor | usage_processor.py:45–84，流式聚合父计数并以I+O生成total；所查函数签名/构造未提供独立reasoning计数 | 本包AST仅执行固定函数类，输入12/5得到17、最终12/7得到19。值对象由测试stub代替；未导入模块或启动引擎。protocol.py的默认reasoning=0不证明真实推理消耗为0 |
| SGLang v0.5.18 / 71de97b264b04dcd514cf904003028aefe9775c8 | utils.py:91确定include_usage与continuous开关；serving_chat.py:711/758/786附进度，1691–1729独立最终usage与DONE；usage_processor.py:58–126独立处理reasoning子集 | 另一个来源profile，不能与v0.5.6算术/调度行号混比。source样本中reasoning是顶层字段，cache在prompt_tokens_details |
| DeepSeek Chat官方文档，当次快照 | stream_options段：最后finish分片携usage，choices有一个元素、不再产生新内容，之后DONE；中间usage为null或缺失，未说明continuous进度模式 | 只支持文档依据，不是不可变供应商服务版本或账户合同。精确模型、模式、终止/等待及硬上界仍待实测与批准。不能套SGLang的独立usage-only规则 |
| 两个SGLang版本的异常分支 | 源码有流内错误数据后继续yield DONE的路径 | 错误须latched，DONE不能洗成成功。平台归一化/唯一结算仍原后端负责 |

原文入口：
[SGLang v0.5.6流式生成](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/entrypoints/openai/serving_chat.py#L487)、
[v0.5.6 UsageProcessor](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/entrypoints/openai/usage_processor.py#L45)、
[v0.5.18流式生成](https://github.com/sgl-project/sglang/blob/71de97b264b04dcd514cf904003028aefe9775c8/python/sglang/srt/entrypoints/openai/serving_chat.py#L1492)、
[v0.5.18 usage开关](https://github.com/sgl-project/sglang/blob/71de97b264b04dcd514cf904003028aefe9775c8/python/sglang/srt/entrypoints/openai/utils.py#L91)、
[DeepSeek Chat](https://api-docs.deepseek.com/api/create-chat-completion/)。

9份当次原文的SHA256/字节数、固定commit、AST锚点和下载时间见 finality/source-evidence.json。两个UsageProcessor原字节样本及Apache-2.0许可随包提供，可独立重跑函数算术。其余源码完整缓存只用于可选哈希复核，不是默认运行前置。函数探针没有pydantic/torch/SGLang模块执行或真实模型结果。

## 2. 四个不同维度，禁止互相代替

    原请求/来源/profile绑定
       → 数值/子集有效性
       → 此来源的progress或final标记
       → 该来源逻辑终止边界及当前原因
       → 原Go/MySQL唯一终态事务
       → 从成功终态投影公开最终Usage

单调性仅用于判断已声明的累计进度是否倒退，**不能从17→19推导19为final**。累计模式不等于增量；没有profile不能猜字段含义。finish_reason不等于usage已经完整收齐；DONE也不能证明账务提交或设备停止。原请求、publication、profile修订必须从可信上下文关联，而非客户端自报final字段。

| 输入 | 本工具预期 | 给原后端/QA的最小断言 |
|---|---|---|
| 正常progress17→19，然后获证final19及正常边界 | final_candidate，进度2次、最终1次 | 不把进度变化误判成冲突，不按chunk累计17+19；不能在来源final marker前成功结算 |
| 只有17→19进度，即使finish和DONE齐 | usage_unavailable | 不选最后19当最终收据；未知维度沿原3.0/profile保守处理，不由diagnostic替代 |
| final19重复final19 | 一个相同candidate，可有重复观测 | 原事件持久化按同event/hash幂等，不重复扣量 |
| final19→final20或同父数cache4→5/reasoning3→4，发生在边界前 | protocol_rejected | 不能用“非递减”或最后值获胜放行；不重调模型。D1/3.1具体异常结算仍未切换，沿当前3.0/v2规则与架构决定 |
| 已观察final，随后EOF/取消/截止，正常边界未被接受 | interrupted，不输出可结算candidate | 真实首次原因/实际值/未知held按原规则；不把任何进度或未闭合final提升为成功账务事实 |
| 来源流内error，后来DONE | protocol_rejected | 不补成功DONE，不让错误后的标志恢复成功 |
| 原逻辑边界后才到的进度或冲突观测 | late_observations单列，原candidate不改 | 已提交终态不重开、不补第二failed/held；迟到只审计。工具未证明数据库已有终态 |
| 已持久化request.finalized同ID同hash重投 | T01幂等ACK预期 | 真SQL事件唯一键及写集须原QA验证 |
| 已持久化终态异hash或同request换event_id重投 | T02/T03内部409、零变更预期 | 不为409再造failed终态或追加held，不混同上游final冲突 |

final_candidate只是来源序列方法检查结果；production_authority=false、ledger_writes=0。它不返回账务实际值、退款或slot释放指令，不证明真实receipt/发布屏障、身份/新鲜度、价格/预算cap或生产adapter获准。归一化候选只保留计数字段或null，cache/reasoning为父计数子集，不再加到total；原始异常值在向量中保留，报告不输出正文。

本包的DONE_then_accepted_transport_end是**离线规格输入**：逻辑DONE之后还要求测试sidecar的transport_end=clean，取消/截止覆盖候选。clean由夹具声明，工具不会把真实socket EOF转换为此权威事实。后端必须实现批准profile的真实终止观察、有界等待/截止、原因竞争和耐久边界；本轮没有给生产设置等待数值。逻辑边界后的数据计late audit，不可把这一离线规则直接接入relay来提前提交成功。

## 3. 受控profile与公开契约

finality/profiles.json的三个条目全部pending、execution_enabled=false；它们是源码规格/测试输入，不是ModelRelease或新公共API。上游include_usage、continuous_usage_stats由可信适配配置档固定，公开ChatRequest仍拒绝stream_options及用户自报final/publication/validation用途。生产开启需成员/架构批准的准确来源、版本、模型、模式、选项、选择数、计费类别和失效/终止规则。

范围仅单choice文本Chat。未知增量模式、工具/多模态、供应商unexpected progress、错误finish、来源ID/model错配及数值矛盾拒绝或留unknown；不自动回退其他来源。v0.5.6下reasoning_path=null，v0.5.18与DeepSeek分别映射各自真实字段；缺cache字段不当0，合法0向量单列。两个来源的终止shape不互换。

现行终态保持3.0，ObservationEnvelope1.0；D1/3.1维持提议，本文不新增missing_reason枚举或改共享Schema。ALG-D1/P1只有在批准profile、真实adapter识别、原relay/ledger断言和独立QA通过后才可关；本轮只交源码/可执行向量，不能自关。

## 4. Prefill/Decode接续：保持明确版本与最近已实现方法

本轮复用e614af8的模型、page/shape、template/context和取消限制，不重跑已交240种KV交错或重做页池。MAAS-13首项已淘汰“通用refcount/代际/完成事件”创新主张；剩余S1尚无完整公平算法或GPU对照，本轮不把输入探针称为已完成S1。

- **共同源码比较pin：**v0.5.6 / 7ae368ef，真实路径Scheduler.get_new_batch_prefill→PrefillAdder→allocator；保留页对齐、cache lock/recheck、running输出估计、mixed decode扣减及retract。v0.5.18 / 71de97b2仅另一部署候选/协议规格，任何跨版本调度实验须重核函数/参数。
- **最近已有CPU参考：**MAAS-10 runtime v0.10 / 6e8b90e5b67da79015b09dc2af16a254660ad8dc（本轮Git远端SHA已核对）。runtime_core、runtime_worker、scheduler_lab、kv_lab四个文件的附件字节摘要进入scheduling-inputs.json。它已有保守调度、页池/Manual与CPU线程Worker、输出背压闭环；不是新的SGLang公平策略或GPUbaseline。保持原目录/主责，不复制实现。
- **模型/shape：**固定7B蒸馏Qwen2/GQA/BF16/TP1；权重/tokenizer未加载。每token57344字节几何量、P16的S/M/L满输出包络24/144/544页沿v0.4；P16未批准，真实backend页大小/Graph/workspace/activation待量测。131072与16384 metadata及BOS/think模板冲突未解决；L的8704输入加输出不能偷偷截成4096。
- **新增4个可运行约束输入：**先算已选decode的实际新页及token数，再考察prefill候选的ceil((l+c)/P)−ceil(l/P)，从free扣inflight reserve；protected不加入free。同样两个空闲页，若一页已reserved，就可能无可行chunk。已有部分尾页可续写，不一律ceil(c/P)。
- **输出边界：**feasible_chunks只做显式合成整数前置检查，不接纳请求、不驱动GPU，不建公平队列。没有activation/执行时长/资源事实时，整数可行不等于可运行；持续过载、长请求最小份额、无可行chunk背压/饥饿逻辑仍由MAAS-13完整算法及MAAS-10同条件静态chunk/自适应方法对照验证。原J02 200请求序列和全sent分母不改。

同组prefix物理唯一页、私有尾部重算、当前allocated与committed、最后device引用、同组后继容量仍按v0.4分层。平台slot、引擎页与财务held不混用；进度usage不证明任何容量/页回收事实。

## 5. 复现入口与交付边界

仓库根目录（已有Python及jsonschema依赖，无需安装引擎）：

    python -m unittest discover -s tools/model_capabilities -p "test_*.py" -v
    python tools/model_capabilities/usage_finality.py --output <task-output>/usage.json
    python tools/model_capabilities/usage_finality.py --source-root <本轮原文缓存目录> --output <task-output>/usage-source.json
    python tools/model_capabilities/kv_pd.py --output <task-output>/kv-pd.json

默认路径只读取本包输入及两个固定算术类样本；可选source-root校验9份源码/文档原文hash，不自动联网。报告失败exit2、不新写成功报告；拒绝覆盖输入。所有向量synthetic/actual_provider_run=false，质量评分仍null。source样本仅AST抽取UsageProcessor class，模块import和顶层执行未发生；Fields stub不是pydantic运行证明。完整向量保留HTTP状态、content-type、原绑定、原始UTF-8 SSE、transport disposition和人工预期，收件人可独立复跑。

30项流内用例、3项终态投递预期、4项资源前置向量及原有profile/quality回归均可复用；方法数和断言计数重叠，不累加为运行场景。PR/提交、真实执行命令、逐项结果和文件摘要随交付报告附后。

**下一步原责任：**架构收敛每个批准adapter的终止标记/有界等待和当前3.0异常处理；后端沿原relay接入phase-aware识别并保留receipt-before-forward与唯一结算；QA按同SHA验证progress/final/EOF/取消/截止及终态冲突实际SQL零副作用。算法提供来源事实和向量，未接管这些实现。P1未闭合前真实模型继续故障关闭。模型/GPU、完整tokenizer/context、真实网关/凭证/validation、版本digest、质量/SLO与额度价表仍缺，未报告真实性能、兼容或质量提升。