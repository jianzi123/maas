# P25-AA v0.26：启动失败与CPU传输修复

**本次仅一次资格启动尝试，在父进程读控制报文时退出；没有启动REF/HOLD模型worker，未获得重复性测量。** 修复后只执行CPU检查，不开启第二个窗口。旧v0.25仍为design_only，旧v0.24的34/64、原Full严格0/18和所有旧失败保持。

## 实际边界与版本

实现03a31e15175704063ba52dd058e340968e10c6af，采前四锁/实际执行dea6485a4fa62426f610e0f15463513e63e880f6。实际plan语义SHA256为92a3ef939dc27746f39a1db4331c055cb1aaba92bd68f63dd823167dc5dbf1ae；[采前协议](p25-aa-method-v0.26.md)及manifest/source hash保留，不将事后修复当作当时执行版本。

| 本次实际结果 | 数值 |
|---|---:|
| 父窗口启动尝试 | 1 |
| Windows前台墙钟 | 1.7387928s |
| REF/HOLD模型worker启动 | 0/0 |
| 计划/实际块 | 128/0 |
| missing / invalid | 128 / 0 |
| 计划/实际计时调用 | 1280/0 |
| 计划/已观测别名配对 | 32/0 |
| 工程资格 | 未完成，原报告false |
| 新GPU重试 / Profiler | 0 / 0 |

所有128计划身份和32配对仍在原报告；没有缩分母。配对差、比值与范围全部为null，不能叫“别名差为0”或“64条测后全超差”。原报告的synthetic_or_incomplete是分析器缺失分类，本实际事件是**本地启动失败、没有测量**，不是合成数据或CUDA失败。

## 可复现的确切缺陷

原启动器追加了字面反斜杠+n（十六进制5c6e），没有追加实际LF（0a）。关闭pipe后，父进程readline读到EOF，json.loads因此报：

~~~text
JSONDecodeError: Extra data: line 1 column 229 (char 228)
~~~

原foreground.log和冻结源码能直接定位：run_aa_window.py在读取lease时退出，尚未进入research锁、GPU资源查询或worker创建。错误属于启动器传输路径，是作者采前测试遗漏；18项CPU门禁及validate-only没有覆盖真实pipe framing，不能把它们当该链路已经跑通。

transport-original-counterexample.bin按**冻结源码和已保存lease重建**，不是伪称截获的原始stdin；CPU得到相同异常位置228。原始stderr则完整保存在execution/foreground.log。两种证据的来源明确区分。

15份实际执行源码按Git blob与plan hash保全为frozen-producer.zip。解压到一个新的短目录，再使用其analyze_aa_window.py和原plan/原window完全离线重算，结果与原qualification.json逐字段一致（实际CLI退出2，因为完整性失败）。这是原失败的复核，不是新GPU执行。

## 修复及验证范围

现候选提供共享encode_lease/read_lease：使用显式字节0a结尾，要求一个完整frame和EOF，拒绝字面转义、空EOF、多个frame及错误预算。生产入口和纯CPU的--validate-lease-only走同一个解码函数；后者在POSIX、锁、资源查询和worker分支之前返回。

修复后22项CPU测试通过（18项原新AA门禁＋4项传输回归）；保存真实完成输出块与退出码。Windows和WSL实际pipe验证各接受正确包、拒绝原坏包，共4个CLI检查，GPU模块未加载。新disabled plan仅用于CPU报文验证，execution_enabled=false；未生成或执行第二个资格窗口。新source hash与原执行source分开，旧源码/plan/协议不被重写，GPU限制和端点容差未改变。

这些检查证明传输修复及协议CPU校验，不证明实际capture caller、别名同图/stream/scratch/pool、padding、跨进程参数/输入数值或logits/KV已经在GPU核验。该路径仍无GPU或独立QA签收；捕获期观察器和数值门禁目前只是已交付实现。

## 原件和复现

[全部原始记录、冻结件、配对CSV/范围、坏包、修复验证及源码包](../../../tools/perf/operators/local_gpu/evidence/aa-v0.26-result/)；[采前18项CPU/CLI检查](../../../tools/perf/operators/local_gpu/evidence/aa-v0.26-preflight/)保持原样。

复核原报告：解压frozen-producer.zip到新短目录，将下列FROZEN替换为该目录；必须使用冻结producer，而非事后修复模块，输出文件必须全新：

~~~text
python FROZEN/analyze_aa_window.py --plan tools/perf/operators/local_gpu/evidence/aa-v0.26-result/plan.json --root tools/perf/operators/local_gpu/evidence/aa-v0.26-result/execution/window --output NEW_REPORT.json
~~~

预期：非零退出，measured_rows=0、missing=128、holdout_matched=0、engineering_repeatability_qualified=false。全部32个配对均未观测。不能直接用修改后的源码加载旧plan：source hash拒绝是正确行为。

修复验证可在仓库根目录运行：

~~~text
python -m unittest discover -s tools/perf/operators/local_gpu -p test_aa_window.py -v
~~~

CPU packet CLI命令及stdin bytes见transport-fix-verification.json和对应bin/log；其临时disabled plan记录运行时源码hash，交付代码应同字节，不声称修复提交当时已存在。

## 下一精确缺口

本失败已有CPU stderr/报文字节/冻结源码最小反例，**不需要Nsight来解释JSON错误**。先对新增传输握手及新runner门禁做独立CPU复核，再由Mika按新阶段交接决定是否开新的资格窗口；现有GPU许可没有撤销，但本次一次窗口已收口，不把剩余时长转成自动重试。

之后才可能验证真实caller/同图别名、完整KV输入与全窗预算，最后评本窗重复性并交全部实际别名差/比值。若后续真实数据出现不可解释波动，再另批采enqueue/stream队列/prepare/主机调度的实际timeline；本批不追加Profiler。A/A通过也不能证明零偏差、统计等价或任意KV收益可分辨，更不启动N/M主比较。

E-LIT-02/03、stage2/save=False、cap8、旧P2 QA16/32及MAAS-15配置/done保持；权重、全局环境、付费、Secret和目标部署边界不扩大。MAAS-10保持in_progress。本次没有推理性能、模型质量、Engine/serving或TTFT/TPOT结论。
