# b5e705d 原生ModelRunner结构独立复验

固定b5e705d2f0ce61d4aeda81ee7a852eb01df7cb5f，仅验证新增结构范围。原QA隔离分支新增测试；未修改SGLang/kernel或默认cap8，未合并产品PR。旧553980d、729f740及后端/D1结论保持原范围。MAAS-7/10继续in_progress。

## 实际结果与边界

- 认证代码14项（含12增量）、原始21项、调试11项hash核对通过；12份增量与固定Git字节一致。九份安装框架源码按固定锁核对。原始native3 runner hash=f32583d4f8c9c4e13f6873ed2ff8197b528a383e0785163ddcd2de82d324833d对应最终源码；native2旧成功源、probe1/native1两次观测器失败及源/日志完整保留。
- 复用持久WSL环境、同research锁、单GPU串行，离线HF/Transformers/Datasets、trust_remote_code=False、原生dummy loader。实际创建134515008个人工参数、LlamaForCausalLM/ModelRunner/CudaGraphRunner，捕获1/2/4/8。未构造Engine façade/在线scheduler/serving，未下载或加载预训练权重。
- 原生Req/ScheduleBatch/ForwardBatch的12步decode通过：B1/B3/B2/B5/B8各两步和8→3→1缩减。B3→4/B5→8 padding、padding行seq_len1/cache loc0、非默认stream、变化输入、毒化输出/scratch、固定输入buffer地址和有效KV位置均检查。保留实际input IDs/req indices/cache locations及释放集合，活跃KV正值、释放唯一且不含dummy0。
- 图结果在eager参考/下一重放前clone，逐次核对先前clone hash不变；原结果确实别名于图输出buffer。本轮图/eager最大绝对差0，仅为同实现结构一致性。12个置零和7个陈旧输出负控均被原rtol0.02/atol5e-7拒绝，未放宽容差。人工logits量级约6e-6，本例负控通过不证明任意错误向量可辨识，更不证明模型语义正确性。
- 五组原生池对账回到req8/KV512。另一个定向进程在真实ModelRunner初始化后，不调用clear，完整分配8请求/512 KV→free→再次分配，集合完全复用、无dummy0，再次free回8/512。该进程仅验证池复用，未重复12步矩阵；不外推生产取消/ACK未知生命周期。
- 从raw CUPTI独立重数四个B3区域：两次graph各378核，KV写核60个分布为主/辅助stream各30；两次eager各399核，KV写60个均在主stream。流编号本例7/144，不把编号作为契约。默认caller实际有RoPE/RMSNorm/silu，store_kv_cache为0。capture后安装的Python hook只记录eager，不声称图重放重新运行Python。
- 独立人工store探针对真实K/V非连续view shape[12,3,64]/stride[960,64,1]逐位相等；raw trace单store核，无fallback，无aten::contiguous/clone预处理。它是独立目标cache的人工probe，不是默认caller或默认图已融合；默认图仍KV双写。RoPE实际Q/K stride及alias在原始报告逐项保留。

## 环境、资源与可复现性

Ubuntu-22.04，/var/tmp/maas-10-gpu-01a1a5ba/bin/python，SGLang0.5.2/b0d25e7，torch2.8+CUDA12.8、sgl-kernel0.3.9.post2、RTX4070 Laptop。本地config/tokenizer文件hash随framework.json记录。allocator/planner均0.20，req8/KV512/context128；启动前6202MiB空闲。主进程35.27s、定向池进程15.41s，均低于600s；进程组/hook收口，自有进程全部收齐。峰值339543552字节仅Torch allocator，不代表整卡。未改系统驱动/共享环境。含hook/同步/额外参考/负控的trace仅作结构证据，不给时延、吞吐或模型收益结论。

run.py在固定源码上只加入QA观测，输出observer.py/observer.patch及原始/执行hash，执行源4a3747acb54c41d5f463f9378d7139f02d8ed8b148c1a95bcc2a086b0f06a98b不冒充原始native3。run_pool.py仅追加无clear分配/回收检查并在构造后返回；完整执行源与命令同样保留。补测原因是原五组之间调用clear，不能单凭其后复用证明free路径正确。

复现：在固定Git导出的tools/perf/operators/local_gpu完整目录和上述环境中，运行run.py --source <固定源码目录> --output <全新QA目录>；其cache路径须为新的QA自有目录，使用原research锁。随后run_pool.py --source <固定源码目录> --output <另一个全新目录>验证无clear池复用。summarize.py从已运行原件独立核对12步/19负控/trace/history与池结果。输入原件、执行代码、hash、命令/PID/输出和历史失败随附件交付；不执行或联网补权重。

下一批成熟KV/RoPE应在capture前接入或显式重捕获，先证明动态locations/复用、非连续view和多stream等价及图内真实kernel命中，再剥离观测开销建立干净A/B。默认cap8保持。完整获准预训练权重、模型质量、Engine/serving基线、nvcc/Sanitizer和生产验收均不在本次通过范围；本地GPU结构研究不等待平台E1。
