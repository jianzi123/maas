# 本地GPU实验

最新：[第19章](../../../../docs/performance/engineering/19-native-kv-integration.md)。native_kv_binding.py仅做进程内研究绑定；run_native_kv_integration.py在capture前接入并含晚接入负控；bench_native_kv.py另做无观测调用成本，不与结构trace计时混用。总体成功须有integration.json与退出0。

最新：run_framework_dummy.py使用原生DummyModelLoader和bench batch入口实际构造ModelRunner，执行1/2/4/8原生图和动态batch；见[第18章](../../../../docs/performance/engineering/18-native-modelrunner-graphs.md)。预训练权重门禁不变；原run_sglang.py不作为本次人工权重入口。

最新：run_split_cap6.py与[第17章](../../../../docs/performance/engineering/17-cap6-empty-cta.md)。环境恢复在任务/var/tmp隔离目录；只验证后端张量切片，未改Engine默认。

当前批次见[工程16：SGLang Decode/KV](../../../../docs/performance/engineering/16-sglang-decode-kv.md)，上一批RMSNorm闭环见[工程15](../../../../docs/performance/engineering/15-local-gpu-cuda.md)。

- decode_path.py / run_decode.py：原生SGLang0.5.2 Triton metadata、KV池与decode核，合成请求状态，固定6份官方源码hash。
- kv_fused.cu / kv_aten.cpp / kv_extension.py / run_kv_fusion.py：仅融合K/V写入，g++ ATen主机派发＋NVRTC设备编译；每次取得当前stream。不是nvcc路线。
- run_mature_kv.py：原生双写/成熟store_kv_cache/教学原型同条件对照，直接op、不接受fallback；D80行宽限制明确记录。最终优先成熟库。
- check_decode_graph.py：改变捕获后的KV、毒化输出并重放验证。
- check_kv_device_fault.py：仅在独立子进程绕过预绑定校验，验证异步设备错误；不与性能计时并行，不是Compute Sanitizer。
- evidence/decode-v0.16：九个成功的独立GPU进程的原始报告、数值/图/错误补证和汇总；完整CUPTI、逐轮jsonl与失败摘录随MAAS-10附件交付。

实际依赖复用requirements-local.txt和上一批环境。设备0、至少1GiB空闲、Torch allocator fraction0.20、batch≤8、单序列≤4097、每图30调用/7轮/每进程600秒外层timeout。fraction不含全部context/库占用，不代表整卡强隔离。

默认使用任务原WSL环境与构建目录；迁移环境须固定torch/CUDA/ABI并使用自己的任务目录。输出必须全新；不自动安装SDK、下载权重或修改全局驱动。

Engine只做过导入，模型生成、scheduler/serving及质量未验证。手动torch graph不是SGLang CudaGraphRunner；当前KV分支未开启Engine的alt-stream捕获flag。不要通用替换原实现。
