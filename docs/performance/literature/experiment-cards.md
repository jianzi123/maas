# 文献实验卡：本轮为设计状态

三卡均execution_enabled=false；既有本地GPU授权不变，本轮只交阅读/设计，不把尚缺实现的实验入口包装成可执行命令。原始结构化内容见[experiment-cards.json](experiment-cards.json)。

## E-LIT-01

**观测/空闲节奏能否重复触发图重放快慢状态**

nvidia-smi查询或查询造成的空闲节奏对已观察漂移有可重复贡献；不是已证明根因。

| 字段 | 具体要求 |
|---|---|
| 原文 | B03；B06 |
| 实现缺口 | 现bench_kv_interleaved每块前调用telemetry；尚无cadence开关，不编造可运行新CLI |
| 固定项 | 同一进程/原生模型seed/dtype/输入/图DAG与指针；相同capture顺序/轮次/调用数；native与mature分别分层 |
| 唯一干预 | telemetry/空闲策略；预先固定3水平：块前查询、cluster前查询、无查询但按预先记录查询时长匹配空闲；禁止按测后快慢挑参数 |
| 矩阵 | {"batch": 3, "input_length": 12, "decode_length": 13, "captured_batch": 4}；{"batch": 5, "input_length": 12, "decode_length": 13, "captured_batch": 8}；{"batch": 8, "input_length": 12, "decode_length": 13, "captured_batch": 8} |
| 设计/覆盖 | 3个策略按预置轮转次序交错；每cluster10块×10调用，所有慢态/超时保留；仅策略级比较，不将重复块当独立样本 |
| 数值门禁 | 沿原完整logits/30层实际写槽finite等价门禁；正确性与profile不进入热段 |
| 观测 | event_with_host_gaps_us；host_enqueue_us；thread_CPU_us；wait_us；wall_sync_us；实际空闲/查询时长；区块/进程身份、超时、丢样覆盖；固定图correlation/DAG另窗口核对 |
| 否定条件 | 反转策略后快慢变化不随策略重复，或效应小于同策略区块漂移，则不支持查询导致漂移；查询与匹配空闲效果不同才进一步区分查询活动与空闲；仍不证明具体驱动机理 |
| 停止条件 | 锁忙即退出，不排队抢其他GPU；低于1GiB空闲/资源超限/600s/数值错误即停止，不产性能成功结论；DAG或输入变化则该块仍保留但不能合入同条件效应 |
| 不利/未知结果 | 不支持假设也是交付；不得宣布WDDM/频率/CPU/驱动是根因或宣称成熟KV加速 |

资源统一GPU0/原research锁、0.20、req8/KV512/context128、600s、≥1GiB空闲、单GPU串行；当前只读复算命令在JSON中，future_GPU_invocation=null。


## E-LIT-02

**固定scratch与实际分段，仅改变空CTA发射范围**

在实际分段/stride/stage2不变时减少纯空CTA，可能减少工作发射成本；不保证短KV收益。

| 字段 | 具体要求 |
|---|---|
| 原文 | B05；P02 |
| 实现缺口 | 现run_split_cap6同时重建scratch/metadata且含L512–2049，不能原样作为当前ctx128/KV512的纯空CTA实验；需新增独立launch-grid对照 |
| 固定项 | physical scratch cap8和stride；actual num_kv_splits/chunk boundaries；stage2 kernel参数/归并范围；模型精度/输入/有效slot及mask |
| 唯一干预 | stage1 launch grid的split轴范围8→6；只接受所有样本所需分段<=6且未删除任何非空块的cell |
| 矩阵 | {"batch": 1, "KV_length": 32}；{"batch": 4, "KV_length": 64}；{"batch": 4, "KV_length": 128}；{"batch": 8, "KV_length": 64} |
| 设计/覆盖 | 预先计算S_i/C_i并记录分段指纹；任何S_i>6或边界改变的cell拒绝该候选，记录不适用，不切换另一算法混入同因果表 |
| 数值门禁 | FP64 oracle与候选均finite，沿既有split脚本rtol=atol=3e-3；V/KV非目标槽及mapping正确；不调整容差追求通过 |
| 观测 | 准备时间单列；stage1/stage2/总raw及graph时间分层；actual split/chunk/stride/stage2指纹；实际CUPTI grid与核、峰值scratch、失败/覆盖 |
| 否定条件 | 任何被删块非空即正确性否决；总时长无改善或stage2/准备/尾部抵消则记无收益；scratch/实际分段改变则失去纯空CTA因果资格，另列多因素变体 |
| 停止条件 | 沿统一资源caps；需要更大长度时先另列后续资源窗口，不直接运行旧矩阵；任何数值/映射失败停止计时结论 |
| 不利/未知结果 | 短KV无收益符合假设适用边界；默认cap8不变 |

资源统一GPU0/原research锁、0.20、req8/KV512/context128、600s、≥1GiB空闲、单GPU串行；当前只读复算命令在JSON中，future_GPU_invocation=null。


## E-LIT-03

**RoPE+KV在真实caller捕获前融合，验证save语义后才测成本**

用已有成熟融合API去掉RoPE后单独store，可能减少读写/核；库语义通过不能证明caller正确或有收益。

| 字段 | 具体要求 |
|---|---|
| 原文 | B06；P02 |
| 实现缺口 | 库探针已通过，但LlamaAttention.forward尚未透传FusedSetKVBufferArg；需要仅研究目录的opt-in caller并重捕获 |
| 固定项 | 同一层/真实loc/来源KV池；neox模式、FP16、Hq9/Hkv3/D64、真实stride960；已安装sgl-kernel0.3.9.post2与SGLang0.5.2；cap8及资源上限 |
| 唯一干预 | 同一caller中成熟RoPE+单独store vs成熟RoPE融合cache写；只有证明同次写缓存后才save_kv_cache=False |
| 矩阵 | {"batch": 3, "decode_length": 13, "context_limit": 128, "captured_batch": 4}；{"batch": 5, "decode_length": 13, "context_limit": 128, "captured_batch": 8}；{"batch": 8, "decode_length": 13, "context_limit": 128, "captured_batch": 8}；{"batch": 1, "decode_length": 128, "context_limit": 128, "captured_batch": 1} |
| 设计/覆盖 | capture前安装，late绑定作负控；prefill/eager/decode各自核save路径；padding slot0单列，不把dummy写当真实非目标槽；默认/非默认stream验证依赖而非固定stream编号 |
| 数值门禁 | 库Q/K FP64 rtol=.001/atol=.002，V逐位；原生logits沿已有rtol=.02/atol=5e-7，误差分布全部报告；任何非finite拒绝；模型质量仍未验 |
| 观测 | 完整logits与30层实际写槽；Q/K原地别名与V视图；真实非目标槽哨兵；实际图中融合kernel命中且无重复store/漏写；不支持输入写前拒绝；图输入地址及池回收 |
| 否定条件 | 只有eager变化而图未变，或fallback/重复store，则不认定融合进入图；save=False缺正确层/槽写入或真实非目标槽破坏即否决；漂移仍未控制时不评稳定成本收益 |
| 停止条件 | 数据值验证不得引入热路径min/max.item主机同步；缺可信映射/冷门禁则不执行候选；dtype/scale/layout/loc类型不支持须在任何QKV/cache变更前拒绝；资源/锁/时间上限同前 |
| 不利/未知结果 | 无收益/不支持/图未命中均保留；不升级环境、下载权重或改变产品默认 |

资源统一GPU0/原research锁、0.20、req8/KV512/context128、600s、≥1GiB空闲、单GPU串行；当前只读复算命令在JSON中，future_GPU_invocation=null。
