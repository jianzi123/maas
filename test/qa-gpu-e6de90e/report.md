# e6de90e SGLang Decode/KV 独立 GPU 复验

本批固定 `e6de90ef16c64e97d2fd645e78367709abf9e2b3`，沿原 QA 分支接续，仅改独立测试目录。**本次后端张量受控范围通过；优先成熟库、保留教学原型的取舍成立。未签收 Engine、模型质量或生产收益。** 与后端 R1–R3、D1 及 A01–A34 完整要求分别记录。

2026-11-13：Ubuntu-22.04 / Python3.10.12 / torch2.8.0+CUDA12.8 / SGLang0.5.2、固定b0d25e7 / sgl-kernel0.3.9.post2 / Triton3.4.0 / CuPy13.6；RTX4070 Laptop、36SM、CC8.9，驱动581.29；g++11.4.0。复用现有环境，未安装/替换共享依赖、系统驱动或模型权重。

## 来源、数值与安全边界

- 36份交付增量与固定Git字节一致，72份作者证据hash一致。六份安装SGLang源码与固定锁一致；成熟wheel八个文件与交付hash及本地RECORD一致，只证明安装包自洽，不冒充上游commit证明。
- 另写CPU FP64逐head参考，不调用被测reference/gather/LSE：**32项数值/逐位KV检查通过，4项D80明确unsupported**。覆盖FP16/BF16、GQA、D64/80/128、尾部、打散slot、当前/非默认stream、未引用池NaN毒化。attention容差0.003/0.02；KV按uint8逐位相等。
- **6项独立非默认stream图检查通过**：capture后改变Q/K/V、毒化输出和目标KV，再重放并对照CPU参考。原check_decode_graph另20项通过；run_mature_kv三进程自带的图输出门禁均通过。计数彼此有覆盖，不合并成一个“总测试数”。
- 成熟路径直接调用torch.ops.sgl_kernel.store_kv_cache，D80/480字节行在FP16/BF16和两种stream中明确拒绝，无静默ATen fallback。D80的unsupported仅针对该成熟op支持契约，不指SGLang原始attention或原型均不支持。
- 一次性子进程绕过bind边界检查，按预期exit42，错误context退出后不复用；父任务退出0且后续进程正常。**未运行Compute Sanitizer，不作为内存安全认证。**

QA只重定向原五个脚本中写死的构建路径，patch随附件保存；kernel、被测oracle、shape、参数和七轮×30调用保持原值。自有g++/ATen主机扩展＋NVRTC设备编译、注册与当前stream路线实际通过；nvcc SDK/.cu静态构建仍未验证。

## 三组独立性能进程与CUPTI

split、原型融合、成熟三方对照各三个独立进程，seed20261113/14/15，共九个性能进程全部退出0；每进程7轮交错×30图调用，四种shape全部保留。QA数值门禁/原图检查/错误父任务也均退出0。正常任务均在600s内收齐，图240s、错误父180s/子120s上限；每进程前后有显存/频率/温度/功耗和compute-apps快照。空闲显存均满足1GiB门槛，allocator0.20（错误子0.05），batch≤8、sequence≤4097、总token≤20000。allocator不等于整卡强隔离；共享桌面GPU未锁频。

各组首进程独立采CUPTI，另从三个raw timeline按同步标记区间**重数27个区域**，与源报告计数一致。split两种cap均是stage1+stage2；原型图backend在30调用下120→90个kernel。成熟eager三调用KV为3个核、backend为9个核，实际出现store_kv_cache_128x2；未为成熟图采90节点证明，不把原型图计数套给它。采样时长不进A/B，不臆造DRAM/occupancy计数器。

汇总器首版误将成熟trace前缀写成mature/，实际为mature_control/，产生StopIteration。已保留首版和错误说明，只修QA标记解析并重算已有trace；GPU未重跑、未删样或更改oracle。

下表是各独立进程的7轮中位数，B/A仅为同研究、同进程的描述性比值；不跨研究比较绝对时间，不声明显著性：

| study/cell | variant A (3 process median us) | variant B | B/A |
|---|---|---|---|
| split/short | cap8: 12.629/28.809/12.595 | cap1: 28.843/14.985/14.985 | 2.284/0.520/1.190 |
| fusion/short | original: 24.235/24.201/24.235 | fused: 16.794/16.794/16.794 | 0.693/0.694/0.693 |
| mature/short | mature: 16.691/16.589/16.725 | prototype: 16.862/16.794/30.208 | 1.010/1.012/1.806 |
| split/long | cap8: 172.305/120.866/121.549 | cap1: 752.060/705.161/706.082 | 4.365/5.834/5.809 |
| fusion/long | original: 114.893/132.642/128.649 | fused: 76.595/125.440/109.807 | 0.667/0.946/0.854 |
| mature/long | mature: 76.459/123.221/76.322 | prototype: 76.629/76.971/108.851 | 1.002/0.625/1.426 |
| split/mixed | cap8: 52.838/118.374/52.873 | cap1: 364.612/557.329/347.546 | 6.901/4.708/6.573 |
| fusion/mixed | original: 70.212/104.994/70.281 | fused: 57.310/56.969/57.310 | 0.816/0.543/0.815 |
| mature/mixed | mature: 159.573/138.342/91.409 | prototype: 173.739/71.543/57.344 | 1.089/0.517/0.627 |
| split/batch8 | cap8: 102.912/86.835/51.200 | cap1: 335.292/188.382/204.937 | 3.258/2.169/4.003 |
| fusion/batch8 | original: 106.086/85.333/167.390 | fused: 55.296/55.296/136.090 | 0.521/0.648/0.813 |
| mature/batch8 | mature: 55.569/89.873/73.933 | prototype: 55.398/91.853/128.034 | 0.997/1.022/1.732 |

长KV cap1相对cap8为4.365/5.834/5.809倍，方向复现。原型融合研究的long三个进程本轮均快于原双写；**未重现作者首进程约21%退化**，作者该原始负结果单独保留，未要求相同小数或方向。成熟三方研究中原型相对成熟的long第三进程退化约42.6%，mixed比值1.089/0.517/0.627，short第三进程约1.806、batch8第三进程约1.732；原型缺乏稳定跨shape优势。全部单轮值、异常大值和telemetry保留，不挑样、不以三进程证明总体收益。

## 交付与后续

原始命令/PID/退出码、每轮样本、三份CUPTI、来源hash、构建hash、独立参考与图结果、unsupported、故意设备错误日志及汇总首版随附件交付。九个性能进程和全部自有门禁进程均前台收齐；末次compute-apps为空，无QA实验进程遗留。自有构建缓存保留以复现，不清理或写入他人环境。

MAAS-7/10保持in_progress，A01–A34完整要求仍未签收。本地GPU研究已获授权并实际执行，不等待平台E1；本次未重跑后端R1–R3/D1，不改产品或合并PR。QA代码沿原隔离分支推送；当前无gh/可调用GitHub写入工具，本轮交可审提交与bundle，不新建重复产品PR。

下一研究批次仍由原性能负责人沿实际断点推进：batch8 cap8实际split6的空CTA假设→成熟KV/RoPE真实caller、capture/stream、动态locations等价性及long退化→完整获准权重后的ModelRunner/Engine/serving基线。QA不代改被测实现。nvcc SDK、Sanitizer、完整Engine/模型质量、生产身份/Higress与平台整体收益均未验；权重下载待原确认，不随本轮自动启动。