# E-LIT-01 0.22 独立离线审核：原件完整、因果0/18，新增拒绝缺口

固定实现4fbb921d6e394c378a9b8b34a082473fa3ca3e94、采前锁/执行checkout6477d5dc4980f76e5a6551bf6616c237b4a55544、结果6933fedbea4a80f23962971e3e610ad87afc46be及交付5f8bd5d83968f9ed5e674593bb8d19078c4575ad。QA从统一agent/MAAS-10-offline-metrics当前8dbf99e建立增量分支，原cf8cf1c/f9884b0等关闭范围保持。本轮只运行CPU离线审计，不导入CUDA框架，不重跑1080块或任何旧GPU/平台矩阵。

**实际原件可核对完整；Full因果匹配资格0/18。原分析器另有ELIT-QA-01/P2：门禁的全部向量被删除后仍写成功报告。** 不能将原件检查通过等同于拒绝门禁完整通过、单独query/idle根因或稳定收益成立。

## 原件、冻结与分母

认证两包SHA与delivery manifest匹配；30增量与固定Git、62证据清单逐字节/hash核对通过。执行6477d5d的六份冻结源码与plan/source hash一致，采前/采后祖先关系核对。canonical plan ab0ac451d9d4beffd6a879ff04bcdcd4000a256ec3194b710f5e7dabca49d9c9、文件SHA c42a4755b426fe964b7423ffb6cf4001e75f42bc52bf9ff018de6184a58c52c7一致。未把事后交付SHA写成采时版本，也未修改目标/计划或容差。

从原始ledger逐ID独立复算108cluster、1080唯一实测块、10800调用；真实缺测0/无效0，Full540/Bare540。每cluster总10块、N/M各5、每块10调用。triplet、rotation、策略位置、pair/slot、variant、clock/run、runtime/cell hash及实际调用数逐项核对。Full完整cluster wall（100计划调用）与除100的单位调用成本分列，cluster wall排除边界归档I/O，但下一块gap保留该时间；Bare仅诊断。

R01/R02独立clock不跨域相减。每次runtime冻结≤cell冻结≤本cell第一次完成/提交，calibration查询均早于runtime冻结；每变体10次校准的中位total_gap产生冻结target，calibration hash准确。除每cell起始明确记录的event_warmup_completion外，逐行previous_done与前一done完全一致，包括cluster边界；没有重置以提高匹配。

436次query＝40校准＋396策略，均由原始queries.jsonl的独立query_id链接到calibration或block。原始nvidia-smi CSV保存在每个query.result.csv字符串中（8字段），没有另一个queries.csv文件。逐一核CSV行/字段、返回码、query起止/duration与账本一致；没有把nvidia-smi墙钟与perf_counter混为同一时钟。

## 独立匹配与状态向量

从previous_done/ready/submit/enqueue/done重算完整gap、ready前缀、wall/enqueue/wait及sleep请求/实际区间，用冻结target和max(250000ns,0.05*target)重新计算全部gap_match字段，未信任matched标志。

- query_block：72/360。
- idle_matched：342/360。
- Full严格组：0/18（三策略均完整，且query_block/idle各10块全匹配）。
- query_cluster不进入逐块匹配率分母；其所有成本、首块boundary gap与误差仍归档。Full按N/M展开不是新的独立组。

全部按run/Full-Bare/B/策略/N-M/首块与组内块分层的误差中位/尾部、108个完整cluster成本在results.json，不筛除超差/慢块或约2.449s异常。0/18不表示无合格块、无测量或效果为0；只是不足以识别单独查询/idle原因。host观测gap不是物理GPU idle，B3/full校准外推其他scope/B、轮转carryover、没有连续状态遥测与桌面未知负载均是限制。

26门禁记录按run/cell/phase独立索引，104次NPZ引用、12个run内去重文件路径全部读回，实际FP32 logits/FP16全30层K/V的key/value、shape、finite和raw hash核对，N/M逐位一致。参数全量hash及模型配置跨进程一致。相同内容hash不是同一次采集事件；原件没有每门禁独立monotonic时间戳，本轮只根据run/cell/phase与锁定采集代码验证引用，不伪称重新执行GPU门禁。

## 测试与ELIT-QA-01/P2

受影响16项原协议CPU回归独立通过；原CLI对跨clock、NaN、篡改matching、重复block四个真实元数据变异均非0退出、无成功报告。隐藏R02的CPU派生案例仍1080计划、540 measured/540 missing；不与真实缺测0混淆。

新增最小反例只改R01/gates.json第一条：snapshots={native:[], mature:[]}，门禁身份/status及其他原件不改。实际CLI退出0，写出成功analysis，仍标1080 measured/108 complete clusters。期望为非0且无成功报告；因此拒绝契约未通过，QA总状态needs_fix。真实原件104引用完整，此反例不否定已核原件或旧QA范围。

定位analyze_kv_cadence.py:148–163：没有验证每个variant必须恰好包含logits和KV两份向量，zip空列表无比较即通过。请原性能负责人在本单修复，QA不代改实现。关闭条件：门禁键/向量数、角色、实际dtype/shape均按协议完整验证；空/单侧缺失/不对称向量均拒绝且不写成功报告，正确原件仍可核验；历史plan/hash/容差/0/18不改写。修复与历史来源兼容应显式处理，不静默改变旧冻结数据。

复现reproduce_empty_gate.py --source <固定0.22工具目录> --evidence <认证证据目录> --output <全新目录>。本候选该QA反例入口预期退出1，oracle.json保留原CLI退出0与unexpected-success.json。完整audit.py也以needs_fix/退出1报告该缺口；不能把它记作全部QA通过。

首轮QA因将CSV误设9列（实际8）失败，首版保存，修正解析后全新目录离线复算；没有改变被测源码、原始记录或阈值，也没有GPU重跑。

## 交付及下一窗口

运行audit.py --output <全新QA目录>（工作目录含elit-input/code、elit-input/evidence、固定5f8bd5d导出的elit-source及Git仓库maas）；16项协议回归日志、四拒绝/缺测用例、新失败oracle、最小反例、所有原件hash与误差分层随证据交付。原件hash与输入未改；独立测试在统一基线增量分支，代码后按标准流程单独提交四来源锁，不修改研究/产品实现。

下一模板小窗由原性能负责人另定协议hash：真实前热块后bookkeeping/边界I/O/prepare/query→参考校准→冻结→独立holdout→主比较，scope/B/N-M/首块角色分列。不能重置previous_done、反填R01/R02 target、放宽旧容差或追好样本；模板继续不代表就保留未知，不直接重跑108cluster。E-LIT-02可读stage2门槛、E-LIT-03同次同层同槽后save=False门槛、cap8默认及权重/平台范围不变。MAAS-7/10继续in_progress，本轮未签收单独query/idle原因、稳定收益或Engine/serving质量。
