# AA-CPU-01 v0.27：原lease上限、传输耗时与共享父起点

本轮修复已由独立QA确认的AA-CPU-01。原QA d9ca7ff7742cf706f26b06d3f81f5733e12fbc25的39唯一用例38过/1失保持为历史，不把作者回归当独立关闭。本候选只作CPU验证：全部新plan.execution_enabled=false、没有GPU查询、共享research锁、模型/权重启动或第二资格窗口。

## 原失败与准确契约

原4bed4b4候选的合法lease为整数ns：driver已用10s、soft剩529s/hard剩589s；job launch=0，soft529/hard589合法。只把job soft改到550、hard仍589时，validate_job和真实worker --validate-only都错误接受。原接受输出、夹具、命令已保全。它证明漏拒绝，不证明原父窗口已超时；唯一原窗口仍是JSON启动失败、128 missing/实际调用0、32配对null，A/A未检验。

修复后的静态关系：

~~~text
D = driver_elapsed_at_send
S_lease <= 540s − D
H_lease <= 600s − D
0 <= launch < S_job < H_job
S_job <= S_lease
H_job <= H_lease
~~~

soft/hard逐项对应原lease，不能只判断soft<hard或hard<=原hard。保留soft529/hard589的等号正控；更保守的短期限仍可用，不能回收发送侧的1s安全余量。ns字段严格为整数。原550坏job现在函数和真实CLI均拒绝；新成功报告不生成，既有CPU成功哨兵hash不变。

## 等待从哪里扣，不在接收后重开钟

原parent在read_lease之后才设置本地start，控制传输/等待EOF超过预留时可能在本地计时中丢失。本次把唯一parent控制起点移到**ready、读帧和等待EOF之前**。Windows driver的原起点、已耗D、540/600与保守预留保持。

设R为从接收方原起点到当前的单调时钟duration，live worker须满足launch<=R<S_job及R<H_job。因此D+R不超过原540/600上界。接收起点在发送之前，D与R可能重叠；本实现允许保守双计，绝不补回重叠、重置driver耗时或把D+R当性能耗时相加。真实Windows→WSL CPU管道记录D=2.7543423s、接收等待R=0.60959804s，两项都保留；没有拿两套OS单调坐标直接相减。

新的receive_lease对实际pipe/file做有界读取，保留单frame、实际LF及EOF语义；完整第一行先用于**收紧**等待deadline，不能扩张它。Windows用PeekNamedPipe检查可读字节/EOF，POSIX用select；上限64KiB。元数据拒绝、过期和通道未完整接收的timeout分开，不把外部kill或缺EOF写成验证通过。CPU验证可用更短等待上限，生产--execute不接受CPU测试选项。

[Python单调时钟](https://docs.python.org/3/library/time.html#time.monotonic)支持在同一受控系统进程间使用统一控制时基；本代码选用monotonic_ns，避免依赖不同Python版本的perf_counter实现差异。[PeekNamedPipe](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-peeknamedpipe)可检查匿名pipe可用字节；这些只是控制期限机制，不是GPU测量时钟校准。

## REF/HOLD不能靠换origin续预算

生产新增内部P25-AA-job2：包含local-monotonic控制域/原origin、原parent/window、以及lease+control的摘要。parent只建立一次control.json，将同一摘要通过独立继承环境交REF/HOLD。它是本地上下文一致性标签，不是业务授权或Secret。

worker在GPU框架导入前验证：原parent摘要、控制域、当前elapsed及原soft/hard；初始化返回与各块边界再次检查。HOLD不能换origin并自算新摘要来更新预算：它会与parent继承的原摘要不一致。两进程的job cap仍引用同一lease，不各取600/540。实际GPU时钟/事件端点不混入这套控制时钟，跨进程性能仍只比较duration。

兼容分界明确：历史job1仍可做静态metadata校验，合法soft正控继续通过，CLI明确metadata_only；它不能授权当前执行。真正执行必须job2、实时控制校验及原有parent/FD证明。离线分析器只核存档上下文和值，不拿今天的时钟重新判历史数据过期，旧冻结producer/原件不重写。

## 本轮实际证据（作者验证，待独立复验）

| 范围 | 实际结果 |
|---|---|
| 新CPU01用例 | 21/21：上限、合法短期限、HOLD原origin、时效、域、EOF/迟到、报告保护、自有CPU子进程/私有测试锁 |
| AA兼容回归 | 22/22；不是GPU结果 |
| 原QA主verify.py未改重跑 | 37/37；作者运行，不是QA新签收 |
| 原followup两项等效补核 | HOLD缺bank拒绝、分析器不覆盖旧成功报告，2/2 |
| Windows真实CPU收据 | 10例，含原529正控/550坏job、fresh报告缺失/旧报告不覆盖、HOLD换起点、迟到和无EOF |
| WSL真实CPU收据 | 同10例，GPU导入/查询/共享锁均被guard禁止 |
| Windows→WSL真实控制pipe | 1例，发送前实际D与接收等待均计入；disabled plan |
| 独立AA-CPU-01关闭 | **尚未取得，交MAAS-7复验** |

这些范围重叠，不能相加成独立用例总数。原QA followup.py的一条旧确认断言预期坏job被接受，修复后不再适用；作者没有静默改QA脚本或借旧39计独立通过。原37脚本的legacy候选文字仍为4bed4b4，当前实际工作树源码hash另记；不能用该文字冒称测试在旧SHA或事后提交上执行。

作者重跑原QA第一次因Windows长路径在生成CPU合成NPZ时中断，完整错误保留；随后仅换到本运行获准短临时目录，原脚本字节未改，37项收齐。没有把中断计为通过。所有自有CPU子进程均collect，终止前核保护PID，仅用private-cpu.lock；不触碰共享research锁。真实POSIX GPU signal/子孙树收尾和GPU资格仍未签收。

[原反例/正控、全部真实命令/字节/PID/退出码、源码hash和作者回归](../../../tools/perf/operators/local_gpu/evidence/aa-cpu01-v0.27/)分别归档；各ZIP带SHA256清单，Windows应短目录解压。sentinel只是CPU报告保护夹具，不是性能成功件。输入plan均disabled；原历史enabled plan只作字节保全，不执行。

## 复现与交接

仓库根目录：

~~~text
python -m unittest discover -s tools/perf/operators/local_gpu -p test_aa_cpu01.py -v
python -m unittest discover -s tools/perf/operators/local_gpu -p test_aa_window.py -v
~~~

要执行自有子进程收口用例，先从当前Multica daemon status读取真实PID，设置仅该CPU测试进程的AA_CPU_TEST_PROTECTED_PID；未设置时两个进程收口用例明确skip，不把skip计通过。本批实际已提供保护PID，无skip。更多真实CLI见Windows/WSL收据与cross-OS receipt。CPU模式不加载torch/sglang/pynvml/aa_runtime；测试锁与原研究锁无关。

MAAS-7应在具体修复SHA上独立复验原550坏job/529正控、共享caps、期限/控制传输、报告保护及新job2绑定；不重派旧P2或启动GPU。当前产品QA忙时放在其后，不steer打断它。独立关闭后，再由Mika按具体下一阶段衔接资格窗口，既有本地GPU许可未撤销，本批没有第二窗口。

向MAAS-21交付的是**研究线状态和可单独评审的CPU控制修复**，不是可部署产品功能。默认Compose/K8s ExternalAPI包不依赖PR9；不要合入未经新runner/GPU验证的研究分支、旧研究四锁、venv或冻结执行件。文档可作分离研究附件引用，任何产品集成仍以MAAS-21最终组合与独立QA为准。本模块的budget是研究墙钟，不是Go/MySQL业务准入账本。

保留原128 missing/实际调用0、32配对null、A/A未检验、旧34/64与Full0/18和未知收益；数值/同图/stream/scratch/池/padding/跨进程输入仍无新GPU证据。业务内核/共享契约、MAAS-15、E-LIT-02/03及cap8、权重/付费/Secret/目标部署边界不变。MAAS-10继续in_progress。
