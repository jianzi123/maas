# P25-AA v0.28：修复版新窗口在215MiB显存门槛收口

**本次明确新阶段只尝试一次。GPU0可查询，但启动前空闲仅215MiB，小于要求1024MiB，门禁拒绝；没有启动REF/HOLD模型worker，A/A重复性仍未测量。** 未释放他人资源、未调低阈值、未新开窗口或追加Profiler。它不同于v0.26的JSON启动失败，两次记录独立保留。

## CPU签收前提与新冻结

AA-CPU-01已由原QA独立关闭，仅CPU预算/控制路径：实现0cea087d21cac94d41f2f93443a48c3a7eaef00f，四锁82284e8fae1c8c11f437e2506aa125694b1f7f99；QA代码8970fe57e6480ba0f6973480e713c403a6c77ed7→四锁e191827072cb64473599ce74db568bc4d830f994。不重跑/重派该CPU复验，也不外推GPU签收。

经认证CLI取得独立ZIP（附件01a217eb-c832-750f-869d-8d25bcb601de），149796字节，SHA256 da798aba5c2ccaa6b1e433b87beb389cd91a50a7693725faf0a4cb470a9df6b2。CRC、17清单逐项hash及嵌套17份执行源码通过，与0cea/822两个Git tree及本次工作树全部同字节。没有改变任何控制/执行源码，QA e191只作签收引用，没有合入QA分支。

本次实际执行HEAD仍为**82284e8fae1c8c11f437e2506aa125694b1f7f99**。新experiment为P25_AA_FIXED_20261126_01，plan语义SHA256为3593858c29da10b668366b3bc3e7885c1dfade2482ab32451ecee089047e1a08。manifest及17来源hash先冻结；保持16层、48参考＋64holdout＋16过渡、128块/1280调用和32配对，原AB/BA/捕获/两进程顺序不变。

冻结入口沿原逻辑在Popen之前一次生成并写driver.json，实际window ID为P25_AA_FIXED_20261126_01-cb124a042f43。没有用wrapper改变UUID或执行行为。输出新目录execution-fixed-01，原disabled plan/失败件不翻转、不覆盖。新增实际plan的validate-only成功、没有GPU导入；不是重跑旧CPU矩阵。

## 原始资源反例与完整分母

| 本次字段 | 实际结果 |
|---|---|
| 父窗口启动 | 1次；driver记录1.2522017s；WSL/parent命令返回2 |
| GPU资源首次查询 | index0，RTX4070 Laptop，driver581.29，总8188MiB，空闲215MiB，returncode0 |
| 要求/差额 | 至少1024MiB，缺809MiB；215×1048576＜1073741824 |
| 失败 | ValueError: startup GPU0/free memory |
| REF/HOLD模型worker | 0/0；未创建REF/HOLD job及reference bank |
| 计划/测得块 | 128/0；missing128，实际调用0/计划1280 |
| HOLD资格分母 | 64计划/0观测，匹配率null，不能说实测0/64 |
| 别名配对/范围 | 32计划/0观测；全部差/比值/范围null |
| 资格解释 | 工程false来自资源前置条件和缺测，A/A未检验 |

查询与拒绝发生在REF模型启动前，原research锁已取得；这不代表Torch allocator/planner0.20、cap8或实际backend已经在模型运行中应用。它们是保留的计划约束，本轮未进入框架初始化。也没有参数/输入hash、完整logits/KV、caller、padding、同图/stream/scratch/pool的新GPU证据；不能填0或借CPU签收补齐。

没有执行模型forward、capture、预热或数值gate；两次资源观察（启动前一次、收尾一次）不是GPU算子/推理调用。Torch allocated/peak和本研究显存回收量均为不适用/未记录，不伪称测得0。库版本是固定源码要求，实际框架加载未发生；只有显卡名称/driver及显存状态来自本次资源查询。

## 控制、进程与收尾记录

本次控制报文解析已到资源门槛，没有复现旧5c6e错误。driver发送前已耗0.928002500s，parent接收等待0.247279682s，soft接收剩537.824717818s；原摘要/前置origin记录保留。没有创建job2 worker，不能据此说其GPU路径或整窗540/600截止已完整实测。

Windows WSL relay PID34520已wait收齐、记录exit2，随后已知PID检查为不存在。Linux parent PID9206也已不存在；lifecycle为空。冻结launcher没有写Python自身PID，本字段明确未记录，不拿relay PID冒充，也不修改源码补采。工具包装调用状态1与driver内child exit2分列，原始命令/日志保存。

收尾只观察本轮已知PID，不枚举/停止他人进程。按同一控制domain和保守D+R剩余预算检查，原research锁可非阻塞重新取得，探针handle随后关闭。此GPU资源观察结束时D+R保守已耗140.418535503s＜600s，未另给新预算；它不是性能耗时，不能拿重叠区间推吞吐。

收尾GPU0空闲145MiB，记录仅为系统现状；没有模型worker/本研究CUDA分配，**不把215→145解释为本研究泄漏或归因给其他使用者**。无归属GPU进程未查询/终止，没有重启共享WSL或改驱动。真实GPU signal/子孙树路径未触发/未验；只确认本轮可见parent/relay收齐及锁可回收。

## 离线复核及证据

[完整新原件/冻结计划/manifest/签收来源核验/资源反例/PID/锁/显存/128身份/32配对](../../../tools/perf/operators/local_gpu/evidence/aa-v0.28/)保留。原report.evidence_kind的synthetic_or_incomplete是通用缺失分类，本实际事件是本地资源门槛拒绝，没有合成测量或GPU计时数据。

同一17份producer离线重算与原报告逐字段一致，实际CLI退出2（完整性失败），不写为成功性能报告。仓库根目录可运行：

~~~text
python tools/perf/operators/local_gpu/analyze_aa_window.py --plan tools/perf/operators/local_gpu/evidence/aa-v0.28/plan.json --root tools/perf/operators/local_gpu/evidence/aa-v0.28/execution-fixed-01/window --output NEW_REPORT.json
~~~

输出必须全新。预期128计划、0测得、128 missing、32未观测配对、engineering_repeatability_qualified=false。本命令仅复算，不会启动GPU。执行时HEAD/来源已冻，结果/文档提交是事后交付版本，不冒称其为实际执行SHA。没有变更17源码，所以独立CPU关闭范围可以继续沿用，不能据新结果扩大为GPU关闭。

## 下一具体缺口与停止边界

当前首个阻断是**本机GPU0空闲显存215MiB未达1GiB**；后续模型初始化/身份/数值和重复性条件全部尚未执行，不能说只要资源够就已达标。下一阶段需要Mika协调满足原≥1024MiB和独占research锁条件的获准时段，既有GPU许可没有撤销；本次已收口，剩余时长不顺延或自动等到显存变好再跑。

不停止他人工作，不缩模型/矩阵/分母、不把1GiB下调或改变planner/allocator、cap8，不新增付费/云GPU/权重/Secret/目标部署。此资源拒绝已有明确query/不等式/日志，不需要Profiler解释；只有后续真实测量波动才另阶段考虑timeline。本批不启动N/M主比较、第三worker或循环回访。

原窗口128 missing/0调用/32null另存，旧34/64、Full严格0/18与未知收益不改。AA-CPU-01独立关闭、旧P2、E-LIT-02/03及stage2/save=False/cap8、MAAS-15配置/done保持。MAAS-21无需GPU的ExternalAPI交付继续，研究分支/研究四锁/venv/冻结执行件不直接进入默认产品包。本轮一次性交回Mika，不重复派QA或跨单通知，MAAS-10保持in_progress。
