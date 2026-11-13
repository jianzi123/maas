# e6de90e Decode/KV 独立 GPU 复验

沿原 QA 分支接续，测试对象固定 `e6de90ef16c64e97d2fd645e78367709abf9e2b3`。只增加本目录，不改被测 CUDA/Triton/SGLang 实现。三组研究分开统计；与后端 R1–R3、D1 和 A01–A34 完整验收分别记录。

环境为既有 Ubuntu-22.04、`/tmp/maas-10-gpu-9bf1ab626448/bin/python`，torch 2.8.0/CUDA 12.8、SGLang 0.5.2/b0d25e7、sgl-kernel 0.3.9.post2、Triton 3.4.0、CuPy 13.6、RTX4070 Laptop。不替换共享依赖、不下载模型。六份安装源码与固定锁核对；成熟 wheel 八个文件核对 RECORD 及交付 hash，只证明安装包自洽。

准备固定提交的 `tools/perf/operators/local_gpu` 完整目录，不能仅应用 36 文件增量。认证代码/证据附件分别为 `01a1d613-072a-736a-9cb0-afdea6327992` / `01a1d613-098b-70f2-8e88-cbb637f01cdf`。运行前核对其 manifest 与固定 Git 字节。

在 WSL 前台运行（路径按当前工作区调整）：

```text
/tmp/maas-10-gpu-9bf1ab626448/bin/python test/qa-gpu-e6de90e/run_serial.py --source <fixed-source-directory> --output <fresh-QA-output-directory>
```

入口使用 QA 专属临时目录 `/tmp/maas7-gpu-e6de90e-555c69ac1872`，重复运行须选择新的 QA 临时目录并记录该路径差异；不要删除其他研究缓存。runner 对五个调用脚本只替换原写死的 build 路径，保存 `QA-build-path-only.patch`；被测 kernel、oracle 和计时参数不改。TRITON/CUPY/CUDA/TORCH/XDG 缓存均落 QA 临时目录。

先运行另写的 CPU FP64 逐 head dense 参考、字节级 KV 和非默认 stream 图校验，再运行原 20 项图检查、隔离设备错误检查。其后三组各三独立进程，seed20261113/14/15、每进程7轮交错×30图调用；各组首进程独立采 CUPTI。不把进程内轮次当独立样本，不跨研究比较绝对时延。

每个正常/独立数值进程上限600s，图检查240s，设备错误父180s/子120s；每进程前后记录显存/频率/温度/功耗/compute-apps。启动前至少1GiB空闲，torch allocator fraction≤0.20，batch≤8/sequence≤4097/总token≤20000。allocator限制不等于整卡隔离。timeout只终止该 QA 子进程会话，所有子进程均前台收齐。

`oracle.py` 不调用被测 `reference()`、gather 或 LSE；用逻辑 K/V 与 CPU FP64 按 query head 独立求 softmax attention。FP16/BF16使用0.003/0.02容差，KV另按uint8逐位相等；成熟核调用原 `torch.ops.sgl_kernel.store_kv_cache`，无 RuntimeError fallback，D80/480字节行明确unsupported。图检查改变 Q/K/V、毒化输出及目标KV后重放，并重新对照 CPU FP64。

汇总已完成结果：

```text
python test/qa-gpu-e6de90e/summarize.py <QA-output-directory> <summary-directory>
```

该脚本重算每组7轮中位数、检查split各cap输入hash一致，并从三个原始CUPTI trace按同步标记区间独立重数kernel。完整命令/每轮样本/trace/失败与unsupported通过本轮附件交付。报告见 `report.md`，研究验收矩阵见 `matrix.json`。

这是无权重、手工backend状态的真实GPU张量实验，未初始化ModelRunner/Engine/scheduler/serving。g++/ATen host+NVRTC device已运行；nvcc SDK、Compute Sanitizer、动态slot生命周期、Engine capture/stream、模型质量与生产收益未签收。exit42只证明隔离context错误被观察，不是内存安全认证。
