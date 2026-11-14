# 实验记录：<ID/日期/负责人>

状态：planned / executed / rejected / blocked。结论必须与证据级别匹配。

- evidence_level：synthetic_fixture / controlled_local_http / controlled_platform / real_model
- 授权引用、环境/目标范围、调用/Token/金额/GPU/墙钟上限：
- 假设、主指标、适用格、批准SLO/质量门槛：
- base/treatment的唯一差异，预计改善机制与可能退化：

## 固定条件

| 类别 | 实际值或null/不适用，以及证据引用 |
|---|---|
| 代码/协议/依赖 | commit、票据/终态/观测版本、工具链及lockfile |
| 模型/runtime | source、权重/tokenizer/template摘要、引擎镜像/commit、有效配置hash |
| 发布/价格 | CR UID/generation、release revision、publication/epoch、路由摘要、冻结价表 |
| 资源 | 每GPU/节点/rank/互联、CPU/内存、驱动/CUDA/backend；相同资源对照？ |
| 请求 | 输入/输出cap、实际EOS长度、U/H与prefix hash、C/到达序列/seed/fixture hash |
| 观测 | client共同scope/窗口、server/engine本地scope、采样/丢样与归一化证据 |
| 业务规则 | Key/三维预算/slot/rate/恢复规则；不得放宽换吞吐 |

## 执行与结果

固定复现命令（不得附Key、秘密、票据或真实正文）：

    <command>

| case/配对run | sent/admitted/success/failed/rejected/pending | TTFT/TPOT/E2E及缺失覆盖率 | 有效吞吐/资源/OOM | 证据文件/hash |
|---|---|---|---|---|
| | | | | |

按原窗口/币种/价表逐维对账reserved+overrun=known+held+released。准入集合与终态/pending核对。unknown/0分开；cache/reasoning不重复加总；slot释放不等于退款。controlled_local_http没有真实业务admitted/账本，明确不适用而非伪造。

## 判断与清理

- 是否满足预先批准的主指标、质量与正确性？缺必需证据不得写“通过”：
- 成对差异、区间方法/假设、退化格；证据不足写探索/未证实：
- 取消/传输关闭/engine abort/slot释放四个时点及未知项：
- 停发原因、未发/在途/隔离/held、线程或自有测试进程的清理结果：
- 回退修订/方式；未执行与剩余风险；复核人/下一责任人：
