# P25-AA 4bed4b4 独立CPU复核：AA-CPU-01确认，重复性尚未测量

固定候选4bed4b4be2ca294b9305cfb28fe1ab03f6164ec0；采前实现03a31e1、执行dea6485a4fa62426f610e0f15463513e63e880f6、修复8d0e7e99bf5ba8294a38079c100b2d5291552c57分别保留。QA新增从统一基线最新实际提交建立qa/maas-7-aa-cpu；旧ELIT-QA-01的独立16/32关闭范围、产品验收和旧GPU结论均不重派、不扩张。

**本批39个唯一CPU用例：38通过、1失败。AA-CPU-01已由函数和真实worker验证CLI独立复现，待原性能作者修复。** 没有GPU执行、资源查询、共享research锁、--execute生产启动、模型加载或第二资格窗口。作者18/22测试方法未运行或计为独立成绩；仅借用其明确标记的纯CPU数据生成器构造复杂身份元数据。

## 原失败报告与来源

28结果项清单、15冻结producer文件与执行Git blob、15份修复CPU源码与固定候选hash一致。冻结分析器真实CLI退出2，重新输出与原qualification逐字段相等。原件128计划块/1280计划调用，实际0块/0调用、128 missing/0 invalid；32配对全部未观测，A/A′差、比值及范围为null。本报告匹配率记null，不写成“实测0/64匹配”或“别名差0”。工程false来自父启动失败及缺测，不是对A/A重复性的实测否定。

原父日志JSON解析错误位置228发生在锁/资源查询/worker之前。按冻结源码与存档lease独立重建的末尾5c6e包得到同一JSON错误，字节与已交重建件相同；它仍是重建包，不是截获stdin。第一轮QA读取原log误用Windows默认GBK，遇混合日志字节失败；原始字节与首版审计保留，改为ASCII错误位置的字节核对，没有改日志或产品。实际尝试仍1次/1.7387928s/exit1。

## 真实CPU管道与报告保护

所有新生产验证CLI仅使用execution_enabled=false计划。真实subprocess.PIPE数据由共享encode_lease生成，真实--validate-lease-only调用共享read_lease；自有sitecustomize阻止torch/sglang/pynvml/aa_runtime导入、共享research锁打开和nvidia-smi查询。正常LF+EOF接受；旧5c6e、空、无LF截断、JSON截断+LF、多frame、额外数据/额外LF均拒绝。迟到额外控制数据仍拒绝，延迟EOF的合法单包在EOF到达后才接受，耗时保留在QA墙钟，不假装未等待。

正确LF但不送EOF时read_lease的read()会等待；此例由QA监督器0.4s限时停止并wait/communicate收齐，分类为控制通道超时，不是验证器已拒绝，也不是产品或GPU失败。原lease-only解析器本身不提供读取超时。本地Windows管道已独立运行；本轮没有重跑作者WSL管道，不能把本机通过外推所有平台。

无效包未生成新成功报告，已有成功哨兵文件未变。原离线分析器已有输出的exclusive写入也以FileExistsError拒绝覆盖。实际命令/字节/exit/stdout/stderr/PID和自有child收集记录分别交付，不以stdout空白推断通过。

## AA-CPU-01最小反例与期限

合法lease为整数ns：total600/stop_new540，driver已用10000000000，soft剩529000000000、hard剩589000000000。合法REF job的launch0、soft529000000000、hard589000000000通过；只把soft改为550000000000而hard仍589000000000时，validate_job仍接受。真实aa_worker.py --validate-only同样exit0、validated=true/GPU_imports=false。期望拒绝，独立用例保持failed；这只证明soft上限校验缺失，不证明实际父窗口已经超时。

定位aa_worker.py:7–15：验证launch<soft<hard和hard≤lease.hard，却没有soft≤lease.soft。请原性能作者补齐soft/hard与原lease对应关系，保持原600/540起点和剩余预算、合法soft正控及HOLD同一lease；回交新SHA后仅定向复测。QA不修改被测实现、不重开窗口或补造A/A结果。

hard抬至600s、lease软/硬重置、late launch、REF带bank及HOLD缺bank等拒绝正反已核。HOLD合法正控保持原lease内容/hash，而不是把JSON复制后的Python对象地址当契约；首轮这个QA地址断言错误及37项35过/2失记录保留，修正后37主用例36过/1失，另两项补用例通过，最终39唯一用例38过/1失，不累计重复执行次数为场景总数。

迟到启动字段必须在原soft之前，HOLD的launch耗时不重置600/540。代码审查同时保留界限：生产driver从原start计算hard剩余，lease有1s保守预留；生产parent的本地start位于read_lease之后，真实跨Windows/WSL控制传输扣时未由本轮执行验证。CPU管道的延迟接受不能当期限时效性签收，超出预留的传输耗时与soft归属需在修复设计中明确；本报告不据此断言实际窗口已超时。

## 身份、生命周期与未测范围

计划/source/window/process/phase、lease/bank/binding/input hash、跨clock、晚bank与别名callable/graph正反检查通过。复杂状态采用纯CPU合成fixture；即使合成64条端点都匹配，也必须engineering_repeatability_qualified=false，不作实际模型/caller/同图/stream/scratch/池、padding或跨进程输入的GPU签收。

自有纯CPU子进程的失败exit7与超时kill/wait均收齐；停止前比较刚读回daemon PID且仅操作自己启动的精确PID，无按名称终止。对这些执行通道失败，原分析器仍保留全部128计划/32配对，差值与比值null。它们只证明测试替身的收集/分母行为，不证明真实POSIX SIGUSR1/强制停止、WSL子孙树或GPU worker收尾全部正确。本轮没有进入该生产路径。

## 复现与下一步

verify.py --source <固定4bed4b4完整local_gpu目录> --output <全新QA目录> --protected-pid <当前multica daemon status返回PID>运行37主用例，本候选因AA-CPU-01预期QA退出1。followup.py --source <同源> --root <该QA目录>补真实CLI及HOLD缺bank/分析器不覆盖两项，输出final-checks.json。audit_original.py --source <同源> --output <全新目录>重算冻结原件；它仅离线读取历史enabled原plan，不执行它。

附最终/首轮CPU结果、所有生产验证CLI和CPU替身/失败件、原始冻结包、重建包、disabled plan、最小AA-CPU-01 job、28原件及源hash。修复仍交原性能作者，独立关闭后另按具体新阶段决定是否授权修复版资格小窗，不能把此批剩余时长转为自动重试。MAAS-7/10继续in_progress，旧34/64、Full0/18、未知收益、E-LIT-02/03、cap8、权重/全局环境/权限与MAAS-15原范围保持。
