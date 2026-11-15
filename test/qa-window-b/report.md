# 窗口B增量独立QA：bf319d6 / 7315b32

本次从统一基线agent/MAAS-10-offline-metrics的实际最新8dbf99e建立qa/maas-7-window-b，保留qa/maas-7-kv19/cf8cf1c和更早关闭范围。交付head bf319d6172d595140bf7ff86a67c589b1d5877b6，研究源码7315b32f08d8cb84c8e330a55c68045545d7898c，执行checkout dcc5a53bee0f58d7d0e58c5f085dcf2450dab7f8分别登记。运行时研究文件未提交，只能用实测源码hash关联事后研究提交，不称当时执行了已提交7315/bf。QA没有重跑窗口A或四个成本进程。

**增量离线审查与六格库级GPU语义通过；漂移原因未知，成熟KV稳定收益未成立。** 未接Llama/ModelRunner caller，save=False未验，不能由本批关闭caller或签收Engine/serving收益。

## 来源与统计独立复核

两包实际SHA与delivery-manifest一致；29份增量与固定Git、74份原始项hash均核对通过。8dbf99e→dcc5a53→7315b32→bf319d6祖先关系成立；7315研究变更只在tools/perf和docs/performance，bf只改四份来源锁。bf的backend556/console68来源清单逐字节核对，锁定7315，条目数不是测试数。运行报告code_sha256均匹配研究提交；实际安装的7份库/框架源快照另以本轮CPU只读检查核对一致。旧六份cost逐字节匹配19e63a1 Git及本批保留件，未丢弃或改写。

直接按process/batch/scope/cycle/position/variant身份独立复算全部240交错块、120配对；另54块原入口独立控制、18个真实before/after状态门禁分开。检查每格10对、交错顺序、身份唯一、五个时间字段的单位及有限正值、门禁logits/KV指纹跨阶段不变。四个成本进程参数抽样指纹相同；两套graph input/KV-index/scratch地址各自独立，源码切换runner.attn_backend/graph_runner和ForwardBatch.attn_backend一致，不并发图。

33/120对成熟更慢。逐轮M/N比值中位数按配对求，不能换成边际中位数之比；全部慢态、正反离群、原6–7ms/13–15ms及25.846ms样本保留。120对不是120独立实验，未算总体CI或显著性。块前nvidia-smi快照未覆盖整块，capture先后与进程/时间窗混杂；bare也有长event/wait，只能否定“全由Python提交解释”，不能确定设备/driver/WSL/其他工作根因。host enqueue/thread CPU/wait/event/wall与busy union/span/核时长不相加归因。cold_calls是门禁后的收敛观察，不叫在线冷启动。

实际运行原analyze_kv_window_b.py：正常输出通过，缺块/NaN/重复变体/profile冒充成本四种独立损坏输入均非0退出、不写成功报告。它们是CPU输入负控，不是GPU故障注入。首轮QA解析器在最后误将retained-costs的list当dict而失败，首版保留；只修QA读取格式，在新目录离线重算，不改产品、原件或GPU样本。

## 核数口径勘误（旧原件不变）

原始CUPTI中按cudaGraphLaunch的correlation关联kernel，新增full/bare四区域纯图native364、mature334；KV仍60次index→30次store。原QA持有的native/mature四个旧graph区域也分别得到纯图364/334，而原区域总数378/348各含14个图外准备/观测核。修正历史报告中“图总kernel”的简称为“区域总核”；cf8cf1c的接线/状态关闭范围不撤销，旧trace/JSON不覆盖。Profiler窗口独立于240干净块，核数减少不推算加速。

## 一次短GPU六格独立语义

原持久WSL Python3.10环境、torch2.8.0+cu128、sgl-kernel0.3.9.post2、本地4070 Laptop；同gpu0-research.lock非阻塞串行，GPU0、启动前≥1GiB、allocator0.20、B3/5/8、KV512、position0/127、context128、每进程600s上限。没有构造planner/ModelRunner，静态planner上限未扩大。实际只运行一个新增人工张量库进程，PID及代码hash/result/timeline/snapshots保留；计算/采样窗口约2.11s，全部前台收齐，最终无GPU计算进程。没有重跑成本/窗口A、下载权重或改系统依赖。

使用不同于作者的固定种子20261117，B3/5/8×默认/非默认stream六格。原始QKV行宽960，Q/K二维stride[960,1]、K三维视图stride[960,64,1]，FP16、rotary64、NeoX布局、FP32 cos/sin cache，k/v scale均None，动态loc不含dummy0且在KV512内。独立CPU FP64数学参考使用实际输入cache值，rtol0.001/atol0.002通过；与分开RoPE+store的Q/目标K及全V/cache逐位相等。Q/K指针保持原地别名，K内容确实更新；V输入和非目标槽不变。正向支持范围限该六格；没有非法scale/量化/offload/其他layout通用安全结论。

独立trace六格均为分开调用2核/融合调用1核。setup与cos-cache跨stream依赖用event明确建立，末端event等待，不以全局torch.cuda.synchronize掩盖数据准备依赖。本批仍是直接库探针，不是Llama caller/save=False或原生图新接线；库核数也不作性能收益。

## 复现和下一窗口

在工作目录保留认证包展开为wb-input/code和wb-input/evidence，并从固定bf319d6导出wb-source；旧QA trace放kv19-qa/native及mature。运行audit.py --output <全新目录>可复算来源/配对/负控和correlation。GPU仅rope_semantics.py --output <全新目录>，用原持久环境及timeout --kill-after=10s 600s，保持同research锁/资源cap，不为本次审查重跑任何成本脚本。

附实际源、原始统计、四负例退出/无报告证据、库GPU输出/trace、首轮QA失败与来源清单。历史实验原SHA和四份来源锁按标准流程保留，QA不代改研究实现。

下一窗口由原性能专家先冻结实验卡：只改查询节奏且匹配/记录idle，再单独改变idle，固定图/参数/负载/捕获次序及完整分母；最小图/GEMM另作控制批次。未知就保留否证，不能挑慢态以外的数据。RoPE+KV caller先证别名/V/save语义及等价性，再谈成本。默认cap8、完整权重授权门槛、模型质量/Engine/serving/生产验收保持未完成。MAAS-7/10继续in_progress。
