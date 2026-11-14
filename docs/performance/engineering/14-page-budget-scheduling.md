# 页预算下的完整调度 对照与负结果

本章补齐MAAS-13 S1所需的算法输入、数据结构、接纳/切块规则、失败边界和可执行对照。复用已有引擎机制建立基线，不将常见页预算、老化、轮换或COW重新命名为创新。当前结论是：CPU算法正确性通过，年龄公平参数在本负载截止条件下的净收益主张被否定。

## 固定源码事实与对照范围

上游源码从官方精确提交重新获取，与MAAS-13原source-lock及MAAS-12 v1.4保存的SHA256逐文件相符。六个文件涉及两版schedule_policy/scheduler与allocator，原文保留在本地输入目录，交付锁定文件与获取命令，避免混用版本。

| 版本 | 具体入口 | 已存在的机制 |
|---|---|---|
| v0.5.6 / 7ae368e | PrefillAdder:320、rem_total_tokens:382、_update_prefill_budget:439、add_chunked_req:454、add_one_req:570 | 当前/总token预算分离、分页向上取整、输出估计、chunked请求延续、页对齐截断 |
| v0.5.18 / 71de97b | PrefillAdder:504、ceil_paged_tokens:831、_update_prefill_budget:857、add_chunked_req:997 | range式请求接口、额外page overhead、SWA/Mamba等条件预算；不与旧版等同 |
| v0.5.18 / 71de97b | scheduler:1185、3241 | 动态chunk依赖enable配置与PP条件，使用已有profile/predictor，失败可禁用 |

探针实际抽取原AST，不改方法体。固定输入剩余32、chunk16、页16、输出cap16：旧版总偏移16，新版总偏移32；最后一个16位置chunk的旧总偏移32，新版48。不同版本计入page overhead，不能把一版预算值拿到另一版实验。

非整页chunk预算17的探针还显示ceil计费可使剩余chunk预算为负；这只是continuation函数的原行为，不等价于完整新请求接纳路径或引擎漏洞。

AST探针设置ordinary非混合allocator/cache、Mamba gap=0、无delayer和合成Req range。这只验证指定host分支；没有执行SGLang调度主循环、Torch、CUDA、模型或PP。CPU比较器中的adaptive是“按等待数量平分剩余chunk预算”的显式代理，不能冒充上述PP预测器。当前完整SGLang成熟策略的性能对照仍待授权环境。

来源：[旧版策略](https://github.com/sgl-project/sglang/blob/7ae368efde14f0b2abe769a5fbb99b8154b2a9b7/python/sglang/srt/managers/schedule_policy.py)、[新版策略](https://github.com/sgl-project/sglang/blob/71de97b264b04dcd514cf904003028aefe9775c8/python/sglang/srt/managers/schedule_policy.py)、[新版调度器](https://github.com/sgl-project/sglang/blob/71de97b264b04dcd514cf904003028aefe9775c8/python/sglang/srt/managers/scheduler.py)。这些是固定研究样本，不推荐直接部署历史版本。

## 容量从字节预算落实到每一个页号

实验假设普通全层KV每位置24576字节、页大小16、KV预算805306368字节，得到2048个物理页。其余权重/Graph/workspace预算尚未由实际硬件确定；不能称本机GPU可容纳此模型。

Pages实际分配主机页ID、generation、valid位置数与owner集合。合成共享前缀长33，占3页并由cache引用常驻。完整前两页只读共享，第三页追加前COW。释放一个请求不会删除cache或其他请求owner；没有owner的私有页归还free。

对输入I、输出cap O、可共享前缀P和页B，保守私有预留为：

~~~text
R = ceil((I+O-1)/B) - floor(P/B)
cache_pages + sum(active_or_unrecovered R) <= capacity
actual_used_pages <= cache_pages + sum(R)
~~~

floor(P/B)只扣除完整共享页；半满尾页未来要复制，因此仍在R里计入私有页。cache尾页自身已经计入cache_pages。算法对本负载不做跨请求不可信复用、不动态逐出cache，也不改变业务Token/金额预留。

追加n个位置的即时增量=新增逻辑页数＋共享部分尾页的COW页。准备前整体检查free数量；OOM不先拆原引用。测试对121组prefix/append长度独立核对公式，并检查共享尾页内容长度和归属不受污染。

## 数据结构和目标约束

Entry保存固定输入/输出上限、arrival_round、shape、prefix_key和可选故障规则。Request保存prefill/generated/decode进度、页表、接纳/首输出/末服务/结束轮次、私有预留和状态。first_output_round是Worker逻辑事件，不叫客户端TTFT。

每轮有token位置预算、线性activation字节代理、max_batch_items和max_active。有效位置预算E=min(batch_tokens, floor(activation_budget/bytes_per_position))。非final chunk需使新的前缀边界页对齐；final尾部可以不足一页。

本实验activation模型是显式可替换的占位约束，无法表达真实Attention workspace、Graph、峰值activation或rank差异。真实实现须从目标模型、backend、shape和并行配置取得资源函数，再检查同一约束。

## 算法伪代码与状态顺序

~~~text
for logical_round in [0, horizon):
    在同步边界处理已到期取消，释放对应主机页与内部预留
    读入已到达但尚未接纳的请求，队列超上限者记 rejected
    按 arrival/id 遍历接纳：
        个体最坏KV或最小对齐chunk不可行 -> 明确拒绝
        活跃数/总预留不足 -> 等待
        age_fair 的老请求等容量 -> 停止接纳后续新请求，等待已有请求排空
        可行 -> 预留完整R，attach共享前缀
    选择本轮工作：
        decode按最久未服务顺序
        prefill：到龄者先按最久未服务；其余按短剩余量
        为可行prefill保留至少一个对齐进度及一个batch条目
        若一轮无法容纳两阶段，则交替给decode/prefill机会
        分配剩余位置预算与chunk，并校验activation/条目上限
    为整批工作分配实际页，推进合成位置与输出数
    先记录释放前峰值，再处理完成/失败
    缺回收证明的失败 -> unrecovered，保留页和预留
~~~

prefill最终一次前向产生首输出；后续O−1次decode消费新位置，输出cap不缩短。此处直接推进长度，数值算法另由原CPU工程卷验证。同步轮次结束后才释放页，真实异步完成和取消规则沿第13章闭环，不把“轮次完成”替换成GPU事件证据。

## 饥饿保证依赖哪些条件

已接纳请求数有界、输出有限、每条有可行chunk、没有未恢复资源锁死时，轮换decode与到龄prefill可持续取得进度。prefill_age是优先级阈值，不承诺请求恰在该轮前完成。只剩一个batch条目或预算无法同时容纳两阶段时，显式交替，避免一直保留prefill预算导致decode饥饿。

等待大请求达到admission_age却容量不足时，阻止新小请求越过它接纳，让现有请求排空。代价是可用碎片可能暂时闲置、总体完成数下降。若现有资源处于unrecovered，或持续过载超过队列上限，算法无法承诺无界到达流的等待上界；保持拒绝/未完成记录，不能靠释放未知页或降低输出cap解困。

每轮扫描待接纳/活跃请求，排序约O(Q log Q+A log A)；预留和队列有界。物理页记录量O(capacity)，请求表O(input_entries)。当前用于可解释CPU验证，未作为引擎热路径补丁。planning_cpu_ns只包围取消/接纳/选择，不包含分配、执行或完整不变量审计，报告明确这个范围。

## 固定负载 调参与配对

原J02文件保持原字节：200条，S/M/L=120/60/20；S为256/128，M为2048/256，L为8192/512。输入长度仍是合成目标，未用冻结tokenizer或模型执行。planned_offset_ms除以10仅映射到逻辑round，不能将结果解释成毫秒。

独立12条校准集对静态chunk64/128/256调参，目标先要求完整完成，再最小化逻辑完成轮次。选择256后冻结，不在测量J02上选最好者。CPU比较有调优静态、预算自适应代理、age_fair、关闭age/接纳屏障的no_age消融。保持相同容量、activation、输入/输出和到达顺序，三次重复交替正反执行顺序。no_age同时去除prefill老化与接纳屏障，属于联合消融，不能单独归因两项机制。

两场景为clean和faults。故障组固定请求取消轮次、在第三次服务注入失败，并让一条缺回收。由于chunk不同第三次服务发生的已处理位置不同，故障组只核验恢复/分母，不作净性能归因。

三次是确定性CPU复验；逻辑结果相同，不产生独立模型性能置信区间。实际规划耗时按配对run报告原始值和中位数，受host噪声影响，不能宣称GPU或端到端更快。

## 本轮负结果与采用决定

固定4000逻辑轮截止，200条分母全部保留：

| 策略 | clean完成 / pending | 物理页峰值 | faults完成 / pending / unrecovered |
|---|---|---|---|
| 调优静态256 | 194 / 6 | 1996 | 183 / 5 / 1 |
| 自适应CPU代理 | 192 / 8 | 2005 | 181 / 7 / 1 |
| age_fair | 161 / 39 | 1977 | 156 / 33 / 1 |
| no_age消融 | 192 / 8 | 2024 | 180 / 8 / 1 |

故障组另有取消与已知失败，counts逐项相加等于sent200；不能只比较表内三项。未观察到首输出的请求仍在shape分母，p95配覆盖率一起报告；不拿条件分位数掩盖缺失。完整状态与逐请求数据见附件JSON。

age_fair对部分服务间隔有改善，但长请求接纳屏障与小quantum牺牲本截止下的完成率。因此当前参数组合不能作为净收益方案推进；保留算法与否证证据，不声称新机制或创新成立。下一轮若评审允许，可单独测试关闭接纳屏障、提高quantum与多目标约束；不得一次把负载或资源也改掉。

## first_chunk_ms 的采样交接

固定后端[e1bd502:relay_forward.go:295](https://github.com/jianzi123/maas/blob/e1bd5020887d092feb892992476bb810512a274e/internal/kernel/relay_forward.go#L295)在normalizeChunk后，只判断first是否为空就赋时间，之后才writeChunk。role-only、choices空、空content和finish-only事件均可能没有用户内容；首次写失败时也需明确计时语义。

现有analyze.sse_metrics对合成事件5ms角色、10ms无choice、15ms空content、30ms非空content、60msfinish，实际得到client_content_times=[30]。源码条件的Python复现给legacy first=5；全无内容时提议content测点为null。这是固定源码条件与客户端解析反例，未运行Go relay或替原后端打补丁。

交原后端的修补要求：先确认first_chunk_ms的既有定义，若保留为Go非空内容写边界，则加显式content谓词并确定成功写/flush观察点；若需保留所有协议首片，则保持其语义并新增经架构评审的独立测点，不能静默改名。两条都不等于客户端收到内容的TTFT；Worker首输出在自身clock_scope单列。

回归应覆盖role/usage-only/空delta/finish-only、首写失败、SSE分片/UTF8、多data、内容后取消/EOF，并保留最终usage和DONE只在唯一成功终态确认后的规则。未知actual、held、slot和固定来源保持原协议。

## 可直接复现的命令和真实门槛

命令集中在[工具README](../../../tools/perf/scheduling/README.md)。CPU比较、源码准备/AST探针、采样反例各有独立入口与新输出文件要求；源码hash变化会拒绝探针，避免运行漂移版本。

真实引擎实验execution_enabled=false。进入下一阶段前须明确：精确引擎/依赖/镜像、获准模型/权重/tokenizer/template/dtype、GPU型号/显存/数量/互联/rank、实际KV/activation/Graph预算、当前调度与动态预测器配置、负载到达/质量/绝对SLO、请求/Token/金额/GPU/墙钟上限和停止/清理规则。平台E1另需实际Go/Higress/Secret/validation装配及相同业务约束。

当前交付为性能工具和可审算法/负结果，产品后端/共享契约不修改，MAAS-13创新判断继续由原负责人结合真实引擎对照收口。
