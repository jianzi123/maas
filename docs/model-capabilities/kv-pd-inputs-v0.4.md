# MAAS-9 KV/Prefill-Decode 输入与职责自查 v0.4

本轮结论：**保留现有平台架构，局部补齐引擎适配与比较输入，复用该版本已有调度/缓存机制。** 新增可运行的页需求、协议和质量方法检查，没有实现另一套KV allocator、逐token调度器或业务账本。计划禁执行、待批准；没有真实模型/GPU/性能结论。

## 1. 单一比较版本

| 对象 | 固定身份与用途 |
|---|---|
| 源码/比较基线 | SGLang v0.5.6 / **7ae368efde14f0b2abe769a5fbb99b8154b2a9b7**，复用MAAS-10源码样本 |
| 性能输入 | MAAS-10工程卷v0.9 / **72d64f9fd38b2b732c204543ed32f70816cbd207**；8份原源码hash本轮全部重新获取匹配 |
| 部署候选另列 | MAAS-9 v0.3的v0.5.18 / 71de97b264b04dcd514cf904003028aefe9775c8，不能混用行号/输出或当同一A/B |
| 模型metadata | DeepSeek-R1-Distill-Qwen-7B / **916b56a44061fd5cd7d6a8fb632557ed4f724f60**，Qwen2ForCausalLM、GQA、BF16候选；未下载权重/tokenizer词表 |
| 平台协议 | 票据v3、终态3.0、ObservationEnvelope1.0；D1/3.1保持消费者迁移待批准 |

算法本轮给MAAS-10/架构师的明确比较输入为 experiments/kv-pd-v0.4.json。校验器拒绝把71de部署候选冒充7ae比较基线。它不代表双方已批准部署/真实实验；后续若共同选择v0.5.18，须重核对应函数和参数，再生成同条件基线。

15份官方源码原始SHA256/字节数及AST函数位置在 experiments/sglang-v0.5.6-source-map.json。只读取文本/AST，不import SGLang、torch或Triton。MAAS-10的PagePool/教学调度器继续作为参考，本轮不复制或改写。

## 2. 现有引擎已处理的机制与适用边界

本轮限定collocated prefill/decode、普通GQA、TP1、无投机/PD分离/HiCache卸载。其他分支必须另追，不能据此宣称全引擎安全。

| 固定函数/位置 | 已有行为 | 返工需保留的基线 |
|---|---|---|
| Scheduler.abort_request:2344 | 等待队列与running分开；普通running请求设置to_finish，再经后续decode/完成清理；匹配使用rid前缀 | “取消立刻free所有在飞KV”不是此路径行为。caller须用原runtime/group/boot及完整rid映射，不能直通客户端任意前缀 |
| event_loop_overlap:992 → result_queue/batch.copy → process_batch_result_decode:314 | 保留前后batch结果；copy_done非空时先synchronize，再检查finish/release | 不可从反例中删掉已有同步。copy_done为None、不同stream/backend或额外异步工作须另追生产者，本轮不证明全设备路径 |
| release_kv_cache:466，mem_cache/common.py | 先cache_finished_req，再处理overallocated部分 | 请求结束不表示全部页立即回free池；正常prefix驻留不是泄漏 |
| RadixCache.cache_finished_req:429、inc_lock_ref:571、dec_lock_ref:585、_collect_leaves:751 | 区分cache/request引用；路径锁引用保护；逐出叶子必须lock_ref=0 | “共享prefix无保护”不是合理基线。free/evictable/protected分开，不能重复释放/计数 |
| RadixCache._page_align_keys:423、cache_unfinished_req:475 | 共享key完整页对齐，部分尾页另处理 | MAAS-10教学PagePool的部分页COW/generation接口不是SGLang原API；本轮按整页prefix＋尾部重算 |
| PrefillAdder.rem_total_tokens:382、ceil_paged_tokens:425、_update_prefill_budget:439、add_one_req:570 | allocator空闲＋可逐出cache、offset、页对齐输入/chunk和输出估计；加cache锁后复查；不足可不接纳/页对齐切chunk | “没有页/token预算”不成立。new_token_ratio/CLIP与chunk策略不是全输出硬预留；下文保守包络不冒充原调度算法 |
| ScheduleBatch.retract_decode:1587、Scheduler.update_running_batch:1900 | decode压力有回退/调整入口 | 实验须报retract/重算开销，不能使用无回退弱基线 |
| PagedTokenToKVPoolAllocator.alloc_extend:459、alloc_decode:512及kernel | 新页数按seq与prefix页数差计算，可续写本请求已有部分页 | 不能一律ceil(新增tokens/P)；下文为算术负例，未运行Triton kernel |

固定源码：
[Scheduler](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/managers/scheduler.py)、
[结果处理](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/managers/scheduler_output_processor_mixin.py)、
[RadixCache](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/mem_cache/radix_cache.py)、
[PrefillAdder](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/managers/schedule_policy.py)、
[allocator](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/mem_cache/allocator.py)、
[release](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/mem_cache/common.py)。

**判定：**淘汰“普通取消立即free”“prefix无保护”“没有chunk/page预算”这三种弱基线描述；本轮未复现此版本use-after-free或调度缺陷。allocator局部无显式generation不推出ABA，必须看真实对象所有权、stream顺序、结果队列及最后引用。若新原型引入跨worker迟到回调/独立异步回收，应构造保留这些已有机制后仍失败的交错，再研究必要状态/同步。refcount、epoch、CUDA event、普通COW本身不计创新。本轮不提交创新算法或专利结论。

## 3. 模型shape与页需求

仅对该模型config的28层、4 KV heads、head_dim128、BF16元素2字节、TP1普通GQA：

    每token KV字节 = 2(K/V) × 28 × 4 × 128 × 2 = 57344
    每页几何字节 = 57344 × page_tokens
    长度n延长到m的新页 = ceil(m/P) − ceil(n/P)

这不是整卡显存测量，不含权重、activation、Graph、workspace、碎片或其他布局；不能直接除TP或套MLA/SWA/MoE。server_args在backend规则后有page_size=1的fallback，其他路径会选64/128等；P16只是未批准研究参数，不是后端/GPU兼容证明。

| 场景 | I合成渲染后token | O合成输出cap | I+O保守包络，P16页数 | 无额外分配的最大已提交数学长度 |
|---|---:|---:|---:|---:|
| S | 256 | 128 | 24 | 383 |
| M | 2048 | 256 | 144 | 2303 |
| L | 8192 | 512 | 544 | 8703 |

首份输出在prefill后采样，其KV到下一次decode才写，因此没有额外预取/投机/重算时最大已提交数学长度I+O−1。**真实allocated不等于committed**，overlap/投机/后端额外分配另计。I=16,O=1,P16时两种包络分别2页/1页，已加入off-by-one负例，不能靠口径变化制造节省。

已有17个token再加1个，P16新页=0；已有16个再加1个，新页=1。ceil(新增1/16)=1在前者错误。共享prefix h只复用floor(h/P)×P：h17复用16、尾1随本请求重算/持有，不假设部分页COW。两个M请求若确实同组/同一token前缀h1536，则96共享页＋2×48私有页＝192页；各自私有或不同组则288页。必须证明model/template/token身份与真实命中，不仅看文本相同。

这些是输入包络，不是PrefillAdder录取模拟。实际需采每rank free/evictable/protected、committed/allocated、seq/prefix/extend、有效chunk/input预算、new_token_ratio、Graph余量、retract/evict/recompute。chunk候选1024/2048/4096沿E2方法；保持page对齐、输出cap/质量/offered load，不缩短答案/降并发换收益。饥饿和短/长延迟由MAAS-10共同窗/全sent分母验证，页算术不证明调度改善。

## 4. context/模板/取消缺项

原metadata的131072位置、tokenizer声明16384、BOS差异、think前缀仍未通过真实加载解决。本轮未执行分词器，I只是合成“渲染后token长度”，不是字符换Token。原4096 context提案不能覆盖L的8704保守包络；须验证context/tokenizer/模板后显式调整实验条件，不能静默截断。

取消需关联原engine rid、runtime boot、组/rank、batch和原allocation，分别记录：动作发出、原rid退出、最后引用device工作结束、prefix引用状态、同组后继容量。A08两秒动作、GPU停止、页可复用、平台slot、财务held分别验。另一副本成功不证明原组恢复；释放slot不退未知Token/金额。源码路径、trace或EOF都不是平台关闭证明。ExternalAPI内部页/计算停止证据缺失时保持unknown，不套本GQA公式；Codex渠道继续独立待定。

## 5. 可运行的协议/质量方法

仓库根目录：

    python -m unittest discover -s tools/model_capabilities -p "test_*.py" -v
    python tools/model_capabilities/kv_pd.py --output <task-output>/kv-pd.json
    python tools/model_capabilities/kv_pd.py --source-root <源码缓存目录> --output <task-output>/source.json
    python tools/model_capabilities/kv_pd.py --require-runtime

最后一条预期exit2，不产生/覆盖成功报告。只读本地输入，不能覆盖输入文件，不调用模型/网络或GPU。SSE支持UTF-8跨字节、CRLF和多data行，检查封闭Schema、稳定id/model、合法finish、唯一DONE；拒绝EOF冒成功、error后DONE、DONE后内容、重复DONE及finish后新内容/第二finish。262144字符事件界限沿现有消费要求；4MiB capture上限只是本离线工具限制，不是新增生产策略。

8题质量方法只用gold/错误/截断的合成答案检验规则，actual_model_scores=null。Q07仅解析AST，不执行生成代码。协议结果为completed_shape_only/error_shape_only，不证明commit、计量或取消。D1/3.1不自动成为当前写协议。

## 6. 职责自查与最小重构建议

已读MAAS-1职责交接、MAAS-12 v1.3全文、MAAS-2 v0.4及v0.4.2-draft.1/2319eb6最小补充、MAAS-9 v0.3独立复核、MAAS-10 v0.9。工程截点：PR #2 API读回821269b、#3 52a24c0、#4 aef53ee；#1 API连接失败，其分支Git远端/本地代码均核实4d45c6f。未重跑这些产品测试。

| 优先级 | 具体判断及最小动作 | 归属/兼容 |
|---|---|---|
| P1职责稿 | 旧“已有端点/不含私有引擎”措辞应更新为v0.4私有模型能力、SGLang/LWS输入及A01–A34协作，不自动授权部署/GPU | Mika维护角色配置，本轮未改配置。算法主责能力/质量，性能主责基准，运维主责部署，后端主责适配/账本，QA独立验收 |
| P1局部接点＋补功能 | 4d45c6f的internal/release/compiler.go中SelfHosted仍输出NONDEPLOYABLE ConfigMap；ports.go的Resolution未提供完整runtime编译结果。建议保留发布状态机/inventory，补窄RuntimeCompiler输入：批准引擎/权重/模板/并行/placement与资源摘要 | 原后端沿MAAS-11实施，架构定共享接口。本轮给输入，不改控制器或把缺GPU推成架构错误；ExternalAPI保持兼容 |
| P1输入修订 | 比较版本和部署候选分离；补模型shape/page、协议/质量入口，禁止metadata/schema自动标verified | 本轮已在算法目录实现；原来源、预算、slot不变量不动 |
| P2触发后研究 | 若真实profile显示同条件饥饿/重算不可接受，或保留stream/引用保护后仍复现错用页，再交最小反例/补丁与否证实验 | MAAS-13研究主责、MAAS-10性能对照；不另建生产调度/账本或复制教学模型，不把常规机制当创新 |

总体建议**局部重构/补接口**，保留Go/MySQL、Higress、ModelRelease/Operator/LWS路线。同构TP1当前足够表达候选；异构PD/MoE/EP须按实际模型与授权另交版本方案，不简单放宽乘法校验。研究不阻塞MVP整合。

## 7. 交接与未执行

MAAS-13可用固定调用链、已有机制和弱反例淘汰理由；MAAS-10可用同一7ae输入、S/M/L、页/尾部/前缀边界，性能仍用其原冻结J02序列。本包六项混合顺序仅是验证输入，不替换原200请求负载。架构/后端/运维可用RuntimeCompiler最小输入和身份/template/context锁定项；QA可运行本目录方法回归。

仍缺获准checkpoint/许可/完整tokenizer模板、镜像digest、GPU/显存/拓扑/后端page配置、真实rid/device完成与同组容量观测、质量/SLO/额度价表及目标授权。复用已交真实业务内核；真实Higress/Secret/validation和完整调用链按实际证据验收。未执行实际引擎/模型/权重/GPU、取消页复用或性能比较，未认定创新成立。新未公开研究方案由MAAS-13内部交付，本轮代码只含成熟公式和受控输入。