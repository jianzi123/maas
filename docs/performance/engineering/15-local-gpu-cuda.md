# 本地GPU：CUDA工程闭环与SGLang接续

本轮在 RTX 4070 Laptop 上实际编译、执行并剖析 RMSNorm，完成一次归约优化。SGLang 成熟核仍更快，教学核没有替换它的依据。SGLang Engine 已导入成功；现有模型缓存缺权重，生成和引擎性能尚未执行。

## 数学与工程范围

对连续张量 x[rows,width] 和逐通道 weight[width]：

    y[i,j] = x[i,j] * rsqrt(sum_j(x[i,j]^2)/width + eps) * weight[j]

RMSNorm不减均值；eps在平方根内。rows可以表示批内token数，width可以表示hidden size。选择它是为在没有权重时完成较小、可核对的工程闭环；尚无完整模型profile证明它是热点。支持FP32/FP16，FP16用FP32累加，eps=1e-5。CPU FP64只承担数值oracle。训练梯度、BF16、量化和任意stride尚不支持。

实际验证空行、width=1/17/31/33/127/129/257/1024/4097/8192、零/小/大/随机值、非默认stream，以及布局/类型/shape/梯度/eps/variant拒绝。NaN/Inf按IEEE传播，性能发布finite门禁拒绝这些结果。FP32 rtol/atol=2e-5，FP16=2e-3；极大有限值仍可能让平方和溢出，不保证无界数值稳定性。

## CUDA C++到PyTorch

实现见 [CUDA源码](../../../tools/perf/operators/local_gpu/rmsnorm.cu)、[注册与调用](../../../tools/perf/operators/local_gpu/rmsnorm.py)、[完整runner](../../../tools/perf/operators/local_gpu/run_rmsnorm.py)。

1. CuPy13.6 RawModule用NVRTC12.8编译CUDA C++，驱动JIT并加载sm89设备代码。使用C++17、关闭FMA合并，不启用fast-math。
2. PyTorch拥有张量，DLPack建立零复制视图；torch.library.custom_op注册maas_local::rmsnorm，提供fake实现。schema/fake opcheck通过，torch.compile/AOT与反向尚未验收。
3. 每次launch取得PyTorch当前CUDA stream，通过CuPy ExternalStream发射。绑定时保留张量引用；限制同设备、连续布局、width<=8192、元素<=1048576。
4. 正确性通过后才预热、捕获图、计时和采样；新输出目录防止失败后误读旧成功报告。

本轮完成运行时编译与Python注册路线；nvcc/ATen主机扩展构建链尚未执行。Windows nvcc13.0.88可见，本轮结果实际来自WSL既有PyTorch/CUDA12.8。全局驱动、CUDA及他人Python环境未改。

接口依据为[CuPy RawModule13.6](https://docs.cupy.dev/en/v13.6.0/reference/generated/cupy.RawModule.html)和[PyTorch2.8自定义算子](https://docs.pytorch.org/docs/2.8/library.html)。

## 一次有证据的优化

serial核由一个线程处理整行：归约串行，同warp相邻线程相距一整行。首份有效timeline中，256×4096 FP32的rms_serial共3次、合计约9878us（带profiler），用于定位与提出假设，不当稳态吞吐。

block核改成每行一个256-thread block：连续lanes读连续列，warp内shuffle归约、8个warp部分和进入共享内存，首warp合并并广播scale。尾列j<width保护；所有线程经过同步。FP32编译属性从26寄存器/0共享字节变成32寄存器/36共享字节；这不等于测出了实际occupancy或DRAM利用率。

### float32，graph事件中位数（us/调用）

| shape | serial | block | torch_native |
|---|---:|---:|---:|
| 1×1024 | 552.468 | 15.606 | 57.702 |
| 32×1024 | 1732.721 | 16.159 | 86.497 |
| 256×1024 | 1836.718 | 37.233 | 146.862 |
| 256×4096 | 7298.056 | 181.770 | 372.551 |

该精度最大绝对误差 9.536743164e-06；PyTorch峰值 36720640 bytes。

### float16，graph事件中位数（us/调用）

| shape | serial | block | torch_native | sgl_kernel |
|---|---:|---:|---:|---:|
| 1×1024 | 333.517 | 6.420 | 48.005 | 5.018 |
| 32×1024 | 839.905 | 6.513 | 58.849 | 5.243 |
| 256×1024 | 1088.041 | 29.010 | 193.608 | 7.526 |
| 256×4096 | 4532.562 | 46.213 | 325.468 | 33.444 |

该精度最大绝对误差 0.001953125；PyTorch峰值 22556672 bytes。


每格预热20次、图内100次、5份事件样本，不是5个独立实验。桌面GPU未锁频，功耗限制N/A；不同运行数值明显漂移，表格仅比较同一进程内各实现，不构成生产收益显著性证明。

graph_event_us是图中重复核序列的CUDA事件时长/次数，包含图执行间隙，不等于单个CUPTI kernel duration。eager_raw_launch_wall_us是绑定好视图后的Python原始launch循环加同步，不含自定义dispatcher/视图建立/模型/网络；baseline包装成本也不完全相同，wall只作工程开销观察。Profiler在计时结束后另采3次。不要相加嵌套record_function、ATen与kernel统计。

FP16 timeline实际出现rms_serial_half、rms_block_half和flashinfer::norm::RMSNormKernel<8u,__half>。成熟核来自sgl-kernel wheel，不表示使用FlashInfer attention Python包。成熟实现各格均更快，保留负结果，不把教学核集成到SGLang。

## 排障反例

- 首轮保留绑定时stream，图捕获为空，产生约0.02us的无效计时。serial目录标INVALID，其passed字样与图计时均不得引用。修正为每次launch取当前stream，空图警告直接失败。
- sgl-kernel0.3.9.post2 RMSNorm拒绝FP32：failed to dispatch data type Float。计时前失败，随后两侧均用FP16；没有只在一侧隐藏转换开销。
- WSL缺ensurepip，采用--without-pip --system-site-packages隔离venv；开发包仅装到任务venv。深层/mnt/c安装大量小文件很慢，最终使用WSL ext4临时目录。
- 0.5.6发布元数据要求torch==2.9.1，本机既有2.8.0+cu128，因此本地固定v0.5.2；历史0.5.6/0.5.18研究保留原范围。
- 一次wheel截断触发SHA256失败，未绕过校验。完整srt extra中的FlashInfer0.3.1源包出现metadata name=unknown，最终按Triton后端安装runtime-common、sgl-kernel和CUDA Python。
- pip22不能将runtime_common匹配runtime-common，改用连字符。隔离venv遮蔽了继承vLLM所需的xgrammar/outlines版本，不能拿此venv跑vLLM对照；全局包未被卸载。

## 固定SGLang请求到kernel源码

v0.5.2，commit b0d25e72c401f37b55d689ddbf05b8c583afe854。9份安装源码与官方commit逐字节相同；hash/AST行号见evidence/source-map.json。下面是选定Triton路线的源码导航；实际引擎分支尚无生成timeline验证：

| 位置（python/sglang/下） | 动作 |
|---|---|
| srt/entrypoints/engine.py:141 | Engine.generate |
| srt/managers/tokenizer_manager.py:330 | generate_request与tokenization |
| srt/managers/scheduler.py:1534/1606/1798 | 选batch、prefill接纳、run_batch |
| srt/managers/schedule_batch.py:1139/1522 | extend/decode的token、位置与KV索引 |
| srt/model_executor/model_runner.py:1811/1830/1914 | decode/extend/raw forward |
| srt/models/llama.py:188 | LlamaAttention.forward |
| srt/layers/attention/triton_backend.py:725/748/794/805 | 写KV，调用extend/decode attention |
| srt/mem_cache/radix_cache.py:158/203 | 前缀匹配、完成后缓存生命周期 |
| srt/layers/layernorm.py:84 | RMSNorm.forward_cuda进入sgl_kernel |

~~~mermaid
flowchart LR
  A[Engine.generate] --> B[TokenizerManager]
  B --> C[Scheduler / ScheduleBatch]
  C --> D[ModelRunner]
  D --> E[Llama forward]
  E --> F[Triton attention backend]
  F --> G[KV write]
  G --> H[extend / decode attention kernels]
  E --> I[sgl_kernel RMSNorm]
~~~

prefill处理多个输入位置，decode通常每序列新增一个位置；都需正确映射已有KV。GQA的KV头可少于query头。本地配置hidden576、query heads9、KV heads3、head dim64、layers30。理论FP16 KV容量为2×layers×tokens×KV_heads×head_dim×2 bytes；单序列1024位置约22.5MiB。这是容量推导，未含allocator、工作区和权重，不是显存实测。

## 模型门禁与引擎下一步

现有HuggingFaceTB/SmolLM-135M-Instruct snapshot为fcc320f490e08fdb4b99d935b2c58d40bf35b0d0。7个配置/tokenizer文件已记录hash；没有model.safetensors/pytorch_model.bin或完整分片。WSL默认缓存路径见environment.json。只核验了这个缓存，不声称整台机器没有其他权重。

Engine import实际通过；离线preflight输出blocked_missing_model_weights、generation_executed=false、requests=[]。当前确定缺口为完整权重目录，须含匹配配置/tokenizer和全部分片，或提供另一个获准、适合8GB的模型目录。新增权重仍按MAAS-10顶部要求单独给模型/版本/来源/许可/容量并获准，本轮未下载。

[离线入口](../../../tools/perf/operators/local_gpu/run_sglang.py)默认只预检；完整权重路径加--run才生成，此分支尚未执行，加载仍可能暴露额外兼容问题。计划FP16、tp1、context1024、KV tokens2048、并发2、静态显存0.30、Graph关闭、Triton attention、PyTorch sampling、greedy/32输出token、2次预热/6请求；外层180秒超时控制进程组，finally关闭引擎。

下一步先交实际输出、全部成功/失败分母、首内容、引擎报告token数、E2E、显存与kernel timeline，另采prefill/decode。stream事件不是token；入口的visible_tpot_proxy_s是客户端近似值，不当Worker TPOT。baseline/profile具备后才在Graph、chunk/KV或attention热点里选一个因素，核对生成一致性、尾延迟及显存，不预设必有收益。

## 复现

Ubuntu-22.04仓库根目录。实际venv为任务专用/tmp/maas-10-gpu-9bf1ab626448，临时目录可能被清理；requirements-local.txt固定主要版本，environment.json补充实际依赖来源。

~~~bash
LAB_ENV=/tmp/maas-10-gpu-9bf1ab626448
python3 -m venv --system-site-packages --without-pip "$LAB_ENV"
# 已有torch须为2.8.0+cu128；新环境请从官方cu128 index安装对应wheel。
"$LAB_ENV/bin/python" -m pip install --no-cache-dir --no-compile \
  -r tools/perf/operators/local_gpu/requirements-local.txt
export CUPY_CACHE_DIR="$LAB_ENV/cupy-cache"
"$LAB_ENV/bin/python" tools/perf/operators/local_gpu/run_rmsnorm.py \
  --variants serial block --dtype float32 --output tools/perf/reports/repro-fp32
"$LAB_ENV/bin/python" tools/perf/operators/local_gpu/run_rmsnorm.py \
  --variants serial block --dtype float16 --sgl-kernel --output tools/perf/reports/repro-fp16
"$LAB_ENV/bin/python" tools/perf/operators/local_gpu/source_map.py tools/perf/reports/repro-source
"$LAB_ENV/bin/python" tools/perf/operators/local_gpu/run_sglang.py \
  --model-path /path/to/complete/model --output tools/perf/reports/repro-preflight
# 完整权重和预检具备后才执行；本轮未执行此--run：
timeout --kill-after=10s 180s "$LAB_ENV/bin/python" tools/perf/operators/local_gpu/run_sglang.py \
  --model-path /path/to/complete/model --run --output tools/perf/reports/repro-engine
~~~

先执行probe_local_gpu.py复测显存。少于512MiB空闲时算子runner退出，PyTorch分配上限15%，不回收其他应用。报告记录source hashes、全部事件样本、PyTorch峰值（不等于全进程显存）和CUPTI。正式复验还需交替顺序、多独立进程、固定频率/功耗与隔离负载。

## 自测与练习

1. 首轮0.02us为什么不能用？图为空；要核对capture stream、真实kernel与数值门禁。
2. block更快为何不替换SGLang？它只优于简单serial，成熟实现同精度更快，且模型路径/端到端未验证。
3. width129安全吗？j<width保护尾部，剩余线程贡献0，仍全员参与shuffle/同步；此边界实际已测。
4. FP16为何FP32归约？控制累加误差，输出半精度舍入另计容差；不保证任意巨大输入稳定。
5. KV22.5MiB说明显存够吗？还要权重、activation、workspace、allocator、Graph及其他应用，须实测。
6. 实战作业：新目录复现，定位三种kernel，解释wall/event/kernel时间不同；提出可否证的向量化假设，先验证正确性及同条件收益，保留失败。

原D1/QA、平台Key/预算、Go/Higress与生产验收保留原范围；本轮不提供平台性能结论。
