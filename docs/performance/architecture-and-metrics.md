# 请求链路、术语和指标

## 一次调用经过哪里

    客户端
      → Go入口（平台Key、文本/模型校验、预算上界计划）
      → 私有Higress
          → Go最终授权
              → Redis速率许可
              → MySQL同事务：Key/修订/预算/slot/request与耐久见证
          → Higress实际固定来源选路/适配
          → 私有SGLang或获准ExternalAPI
      → Go转发内容并唯一终态结算到MySQL
      → 合法DONE/完整成功结果

外层Go和Higress span包含子调用等待，不能把inclusive duration直接相加。正常DONE在耐久终态提交后交付，最后内容到DONE的尾部可能包含结算成本。

控制面为ModelRelease CR→Go Operator→候选runtime/publication→真实依赖receipt/验证→活动修订。K8s对象存在不是可调用证据；CR不保存Key、秘密或实时账本。MAAS-11 mysqlstore是发布屏障和inventory库，不是另一套调用预算/usage实现。

## 新人必须会解释的术语

| 术语 | 项目里的含义 |
|---|---|
| prefill | 处理已有输入，形成生成所需状态；长输入可能占用较大计算/峰值显存 |
| decode | 后续逐token生成；要区分模型本机token与客户端收到的内容片段 |
| KV cache | attention相关缓存；具体布局取决于MHA/GQA/MLA、精度与并行策略 |
| Radix前缀缓存 | 复用相同token前缀的计算状态；不是保存答案直接绕过预算 |
| publication/activation_epoch | 一次不可变发布与其活动屏障；回滚也产生新上下文 |
| reserved/known/held/released | 在途预留/已知使用/未知保守占用/已释放差额，不能混成actual |
| slot | 跨副本容量名额；终态后可能仍隔离，释放slot不退款 |
| effective throughput | 质量及适用SLO满足的成功请求数/共同观察时间 |

普通MHA/GQA的KV初算可用2×层数×KV heads×head_dim×元素字节/token；不能直接套MLA，也不能未经验证按TP度数平分。最终看每rank实际权重、KV、activation与graph占用。

## 核心公式与缺失

| 指标 | 公式/要求 |
|---|---|
| 客户端可见TTFT | 首个非空content事件完整收齐时刻−实际sent；role/空delta/usage/心跳不算 |
| 计划TTFT | 同一首内容时刻−scheduled；发生器排队单列 |
| 服务端first_chunk_ms | Go入口至首内容delta的原业务口径，和客户端TTFT分开 |
| 可见TPOT代理 | (末内容时刻−首内容时刻)/(冻结tokenizer计数N−1)，N≤1为null |
| 引擎TPOT | 引擎本机逐token时刻的间隔；和visible_proxy分开，只有chunk不能报ITL |
| 成功E2E | 客户端合法成功终止−sent；raw EOF/流内error/缺DONE非成功 |
| 吞吐 | 成功或已知实际token/T；失败/拒绝仍在sent分母，尾部/pending明确 |
| 有效吞吐 | 成功、质量通过、TTFT/E2E及适用TPOT达标数/T；必要SLO未知不能判达标 |
| 分位数 | index=(n−1)q线性插值；小于200样本只作描述 |
| 预算守恒 | reserved+overrun=known_used+unknown_held+released，逐维/原周期/币种核验 |
| 准入集合 | admitted=五类已终态之和+pending/recovery |

未知是null，真实0保留0；全部未知不产生0 Token吞吐，known子集合计同时报告覆盖率。cache/reasoning是子集，不能再加到total。金额用atomic十进制整数字符串，按币种/冻结价表分组。

## 时钟与身份

共同吞吐window只接受同一可解释client clock_scope；每request还须匹配自身client observation。相同标签不证明真实同步；NTP墙钟相近不等于跨进程monotonic可相减。server/engine保留各自本地时长，不加入客户端scope集合。

当前版本：票据v3、request.finalized 3.0、独立ObservationEnvelope 1.0。诊断envelope不产生授权、结算、退款或关闭证明。request必须关联原CR UID/generation、release revision、publication/epoch、实际路由摘要和冻结价格；不能用当前CR替换旧在途请求的上下文。

## 证据不能跨级解释

人工时间戳算出的4rps是synthetic；本地HTTP fixture测出的吞吐是controlled_local_http。两者都不能代表Go/Higress/MySQL/SGLang性能。后端的真实MySQL发布存储测试也不能外推为完整调用账本、生产网关或GPU验收。

共享契约以[架构v0.4](../contracts/MAAS-2-architecture-v0.4.md)、[预算v0.3](../contracts/MAAS-2-architecture-v0.3.md)和[验收C01–C08](../../tools/perf/docs/acceptance-v0.3.md)为准。
