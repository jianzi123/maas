# 高级工程师怎样设计框架接口

有了算子和状态机，下一步是把并发、资源所有权与恢复规则写成可以实现的模块边界。接口的价值在于限制错误：谁能改变状态，谁必须提供完成证据，失败后从哪里恢复。本章接口名称是教学草图，不替换项目已确认 API、票据或事件。

## 推理运行时的最小组件划分

建议先定义五个内部责任：Ingress 解析与排队；Scheduler 唯一推进请求调度状态；KV Manager 管理页表、预算和回收；Worker 执行 batch；Output 管理采样结果和流式背压。鉴权和预算仍由 Go 真源执行，运行时内部排队不产生额外业务准入。

可以用这样的只读描述连接组件：

~~~python
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestBinding:
    request_id: str
    attempt_id: str
    model_revision: str
    config_revision: str

@dataclass(frozen=True)
class BatchPlan:
    submission_id: str
    worker_incarnation: str
    phase: str
    request_bindings: tuple
    token_positions: tuple
    page_bindings: tuple  # physical page + allocation generation
    shape_signature: tuple

# 教学接口草图，无实现
# scheduler.plan(snapshot, limits) -> BatchPlan | NoWork
# worker.submit(plan) -> SubmissionAccepted | SubmissionRejected
# worker.poll_completion() -> Completion | None
# kv.retire(allocation, device_completion_evidence) -> Retired | Quarantined
~~~

frozen=True 只阻止给字段重新赋值；若字段里放了可变 dict/list，内容仍可能被改。真正的 BatchPlan 还需要不可变子对象或受控拷贝，以及提交前的 shape/长度/页归属校验。上面的 tuple 只表示设计意图，不能当完整输入验证。

SubmissionAccepted 只代表提交被接收，不代表 GPU 已完成。Completion 应对应准确的提交、Worker 启动代次和分配代次；缺输出、重复输出、旧 owner 输出和部分完成要有明确处理。仅凭 request_id 复用一个旧回包，会把重启前的结果混入重启后的请求。

让 Scheduler 持有调度状态的单一写入口，可降低多个 callback 同时完成/取消同一请求的风险。Worker 进程不直接修改业务账本；输出线程也不绕过 Scheduler 释放页。实际可采用单线程事件循环或受约束的锁设计，关键是明确所有权、队列上限和跨进程消息，而不是默认所有状态都靠一把全局锁。

## 先定义状态转移，再选线程模型

运行时请求至少需要区分 queued、prefilling、decode-ready、running、stop-requested、device-quiescent 和 output-closed 等事实；不必机械照搬这些名字，但必须保留相应区分。业务终态属于另一状态机，不能让 output-closed 自动等于 succeeded。

考虑三个同时到来的事件：客户端取消、GPU batch 完成、输出队列写失败。事件处理应按 owner 与提交身份序列化；取消后禁止新调度，已在途完成仍用于安全回收，但不得重新开启输出。最终业务事件通过原协议去重提交。不能因 cancel callback 和 completion callback 都认为自己“最后执行”，就释放两次同一页或结算两次。

Batch 里一条请求失败时，其他条是否仍有效，取决于错误边界。输入校验错误应在提交前定位；设备级错误可能影响整个 Worker。无法证明某一段 KV 仍可靠，就不能仅把 failed token 跳过后继续生成。重算、隔离、终止和重试各有质量、来源、预算与可恢复性限制，必须显式登记。

## 输出背压和取消必须占据设计位置

假设 GPU 每轮产出多个请求的 token，而客户端读得很慢。无限输出队列会耗尽 host 内存；直接让 GPU 执行线程阻塞写 socket，又会拖慢整个 batch。应使用有界队列、独立传输与清晰的满队列策略，记录排队字节、年龄、取消和实际停止时间。

任何丢弃策略都不能静默丢 token 后假装成功。停止接收更多输出、发起取消、等真实停止证据和结算是不同动作。期限与公平性要覆盖排队、计算和输出阶段；重试也不能让旧 attempt 继续占 GPU 后又创建新来源 attempt。

基本回归应以可控制事件顺序的 fake Worker 验证：completion 在 cancel 前后各一次、重复 completion、旧代次 completion、无 completion、队列满、Worker 重启。不要用大量随机 sleep 代替可重放的并发场景；再用受控真实组件验证设备、进程和网络边界。

## CUDA Graph 为什么会反过来影响调度

CUDA Graph 的 capture 把一段 GPU 工作流程记录起来，replay 重复执行这段流程；它没有缓存模型输出，输入与 KV 仍需正确更新。Graph replay 需要满足捕获时的执行与内存条件。动态 batch、不同长度、页表更新、某些 backend 或精度路径都可能导致 padding 或 fallback。框架要明确定义 shape_signature、可捕获范围、输入缓冲的更新方式和其生命周期，不能只暴露 graph_enabled 一个开关。

例如 capture 集合原为 batch 1/2/4/8，实际 batch 常是 3。选择 padding 到 4 可能省 launch，但增加无效计算；新增大量 capture shape 又占显存。第二章虚构 KV 预算若从 2048MiB 被 graph 多占 384MiB，页数、逐出和可服务批量都会变化。优化 Graph 必须同时观察命中、fallback、准备 CPU、padding、峰值显存与有效吞吐。

已有成熟 Graph 配置应作为主 baseline；eager 可作机制消融，不应删除生产已有优化后再宣称收益。冷捕获和稳态分别统计，失败或不支持的样本也留在数据里。

## TP 和 MoE 把哪些故障放大了

rank 是参与一组并行计算的进程编号。Tensor Parallel 把一层计算分到多 rank，可能需要 all-reduce 等 collective；Expert Parallel 根据路由把 token 发到专家，再合并结果。它们改变 kernel shape、消息、缓冲和同步，不只是“多加几张卡”。

设计前先画物理拓扑与 rank 映射：节点、GPU、互联、进程和通信组。每 rank 分别核算权重、KV、activation、graph、通信 buffer；最紧的 rank 决定容量。为每条关键消息登记 dtype、字节数、发送/接收位置和依赖，防止将不同 rank 的不同序列号 collective 混合。

故障策略要涵盖一个 rank 显存不足（OOM）、collective 超时、进程重启和部分 group Ready。重启其中一 rank 是否还能继续旧请求，需要模型状态和通信协议证明，不能仅因 Pod 又 Ready 就认定可恢复。跨 rank 完成证据和资源隔离不足时应关闭该执行路径。

通信优化关注关键路径暴露时间和整体 G。把 all-reduce 移到另一个 stream 后仍需正确依赖；减少同步却读到未完成结果不是优化。MoE 还要保留专家路由、溢出策略和所有 token，不能丢掉慢专家来改善吞吐。TP/EP/PD 等架构变化先写 ADR，再进入获准环境实验。

## 画出一次 TP 的真实矩阵与消息

取 X 为 [M,K]，线性权重 W 为 [K,N]，TP=2。按输出列切 W=[W0,W1] 后，每 rank 算 Y0=XW0、Y1=XW1，局部输出各为 [M,N/2]。后续若按头继续计算，不一定立即 all-gather；应沿真实 backend 看输出的消费者。

若下一层输入也按列分成 X0/X1，并把输出投影权重按输入行分成 W0/W1，则各 rank 得到局部和 Z0=X0W0、Z1=X1W1，最终 Z=Z0+Z1，需要相应归约。把归约删掉得到的是不完整结果，不是更快的等价实现。MLP 中列并行扩展、行并行收缩也可用这种方式推导。

这还不能推出“KV 占用直接除以 2”：查询头与 KV 头、复制策略和实际 backend 会影响布局。每 rank 应记录自己真正持有的头数与 buffer。MoE 则要先按专家路由重排 token、记录每组 M，再执行 Grouped GEMM，最后恢复原 token 顺序；重排/dispatch/combine 的时间与临时空间必须进入范围。

作为接口练习，为一个 [M,N] 的归约输出标注字节数 M×N×element_bytes、依赖它的 kernel 和完成事件，再对照 timeline。它是逻辑消息体量；实际 collective 经过多轮通信和协议开销，不能直接等同链路传输字节或真实带宽。

## 部署框架的接口要把计划与副作用分开

部署侧可分为读取/解析、纯计划、持久意图、资源执行、证据采集、活动切换、排空清理。纯计划函数便于在无集群环境检查版本和归属；真正写入必须由受权适配器实施。

~~~text
ObservedSnapshot:
  CR identity + generation + resourceVersion
  approved dependency versions
  immutable revision inputs
  durable publication state
  inventory identities + actual observed resources
  receipt / validation / drain evidence

Plan(snapshot) -> bounded ActionIntent[]
PersistIntent(command_id, payload_hash, owner_fence)
ExecuteOne(intent, current_authority) -> observed evidence | unknown
Recover(command_id, payload_hash) -> original durable outcome | pending | conflict
~~~

本地纯函数不能伪造“批准依赖”，执行器也不能凭计划中的 bool 就信任外部资源。网络调用不能放在持有核心账本锁的长事务中；将副作用拆分会引入中间态，因此必须设计重入、补偿或关闭路径。分布式系统没有因为画了一条“事务”箭头就获得跨系统原子性。

高级评审应要求每种 Action 写出：稳定身份、允许前置状态、权限、超时含义、查询方式、重复策略、持久恢复位置和禁止补偿。尤其不能把“响应超时”一律当没发生，也不能删除金融记录来补偿一次发布失败。

## 可观测性本身也有成本和权限

热路径建议使用有界标签和采样：request/trace 用于受限逐请求记录，模型/活动修订用于聚合。不要把每个 request_id 都变成无限增长的指标标签；不要为定位 KV 命中记录用户完整 token。跨 rank 时间线需说明时钟与采样边界，跨层耗时分别保留本地测量。

采样至少要覆盖队列、batch 组成、prefill/decode、KV 分配/逐出/重算、Graph 命中/fallback、通信与输出背压。部署侧记录解析、调度、拉取/加载、group Ready、网关采用、验证、激活、排空和清理。性能图能说明哪里花时间，状态和账本证据才能说明这次调用是否正确。

本章的完成物是一页接口图、一份资源归属表和一份故障矩阵。下一章给出可分阶段实现的范围，防止把“做一个推理框架”变成无法验收的长期口号。
