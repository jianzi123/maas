# 6517a15 cap6切片独立GPU复验

固定6517a152d67f21ce3fcb11bddf76cf79b3e6c42c，仅新增cap6切片。上一批729f740、后端R1–R3/D1保持原范围。三独立性能进程全部退出0；本次受控backend张量范围通过，Engine默认cap8未改，不签收模型收益。

认证附件原件15个增量与固定Git、29个证据hash核对通过；原decode_path/run_decode与e6de90e逐字节不变。恢复环境/var/tmp/maas-10-gpu-01a1a5ba：Python3.10.12、torch2.8.0/CUDA12.8、SGLang0.5.2/b0d25e7、sgl-kernel0.3.9.post2、Triton3.4、RTX4070 Laptop。逐项记录system-site包和venv本地包；六份安装源码匹配锁，成熟包.so/RECORD一致，缓存开发wheel完整378988054字节、SHA256 fddc3a23e0ba9252381cdefaee20ebfb2722d0ea07648dde73dc7c8e1933e339独立复核通过。pycryptodomex仍缺失；可运行Decode不证明Engine依赖完整。旧/tmp环境和恢复环境分列，不比较绝对时延。本轮附件下载成功，无未核ZIP。

另写CPU FP64逐head参考，不复用被测gather/LSE/reference；四格×FP16/BF16×cap8/6共16组数值与uint8逐位KV检查通过。每组在非默认stream捕获raw/backend，改变Q/K/V、毒化输出及目标KV后重放，32次改输入图检查通过。raw图复验前由backend图写入新KV；无空图或旧输出替代。

同research锁/var/tmp/maas-10-gpu-01a1a5ba/gpu0-research.lock保护所有GPU子进程，未删锁/绕锁。QA自有/var/tmp缓存；原性能脚本逐字节执行，不改被测kernel/oracle。三个独立进程seed20261114/15/16，每进程9轮交错×40调用/图，首进程另采CUPTI。每进程timeout600s，启动前空闲约6.1GiB、allocator0.20，B≤8/最大L2049/总token≤20000。频率/温度/功耗/显存与每轮样本保留，未锁频，无显著性结论。四个自有门禁/性能子进程均收齐，末次compute-apps为空。

从QA raw trace独立重数16区域：每次raw仍2核，每图80核；stage1实际grid [8,3,8]→[8,3,6]，192→144个发射CTA。L1024双方实际splits=[6]*8、chunk=[192]*8，非空CTA144为固定源码与实际split的推导，非硬件计数器。scratch149760→112320字节及stage2循环上界也改变，所以不能把全部差异孤立归因于空CTA。

以下比值仅同一恢复环境、同进程cap6/cap8的9轮中位数；每轮原始值全部保留，不把轮次当独立实验：
| case / scope | cap6/cap8 (3 process medians) |
|---|---|
| b8_l512 / raw | 0.9983/0.9904/0.9959 |
| b8_l512 / backend | 0.8287/0.9998/1.3591 |
| b8_l1024 / raw | 0.8721/0.8535/0.8748 |
| b8_l1024 / backend | 0.8647/0.7061/0.9231 |
| b8_l2048 / raw | 0.9297/0.4542/0.8882 |
| b8_l2048 / backend | 0.8602/0.7296/0.9656 |
| b8_ragged / raw | 1.8708/0.8800/1.3963 |
| b8_ragged / backend | 0.5998/0.9280/0.8951 |


L1024 raw三进程均改善，backend亦改善，具体比值见表，不强求作者百分比。L512 backend第三进程退化约35.9%；ragged raw第一/第三进程退化，全部保留。L512 raw本轮未复现作者小幅退化，作者原始负结果另存。2048/ragged分段改变，不归入仅空CTA切片；桌面GPU波动明显，不筛除异常大值或据此推广cap6。

复现：在固定6517a15导出的完整tools/perf/operators/local_gpu目录和恢复环境中，运行run.py --source <固定源目录> --output <全新QA输出目录>。run.py使用固定QA cache目录，二次复现须选新的QA自有cache路径并记录差异；保留同research锁。再运行summarize.py <QA输出> <全新汇总目录>重算分布和trace。源代码、环境/源码与wheel摘要、原始输入/每轮样本/CUPTI/命令/PID/失败和来源附件在本次证据ZIP，包内manifest可校验。

本地GPU研究已授权，不等待E1。下一批仍由原性能负责人验证真实Engine capture/replay、动态batch/padding和成熟KV/RoPE caller命中/等价性后评估条件化cap；完整权重待原确认。本批未下载权重、运行ModelRunner/Engine/serving或验证模型质量；nvcc SDK/Sanitizer和生产收益不在通过范围。MAAS-7/10继续in_progress，A01–A34完整要求不签收。
