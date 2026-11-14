# 19e63a1 成熟KV原生图接线独立QA

固定候选19e63a1999c1c9b54e532f7d8afd6473bf2836bc。QA从统一基线agent/MAAS-10-offline-metrics当时最新8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a建立qa/maas-7-kv19增量分支，旧ecff788等分支与结论保留。只改独立测试目录，不将未合入候选写成统一基线，不重开旧PR。

**本批FP16原生图接线、动态位置和受控状态等价性通过；稳定成本/预训练质量/Engine或生产收益未签收。** 窗口A已结束并释放research锁，窗口B成本漂移研究由原性能负责人接续。

## 来源与独立执行

两认证包SHA分别25588f9abd50b21fc409a0e5ac0dbbee6461deea81ec36daaba3da764628f830、0b2079dff024bbc99f6568f5a7d63a6617a574c69e097d7fdb35059923ea8da7；29份增量与固定Git、58份原始文件hash独立核对。作者数组仅作输入来源，QA全部输出由本轮GPU独立生成，没有用恢复/复制作者logits代替采集。

既有Ubuntu-22.04、/var/tmp/maas-10-gpu-01a1a5ba/bin/python、SGLang0.5.2/b0d25e7、sgl-kernel0.3.9.post2、torch2.8/CUDA12.8、RTX4070 Laptop。执行脚本按九份框架源码锁验证安装字节，报告保留本地config/tokenizer hash和代码hash。HF/Transformers/Datasets离线，DummyModelLoader人工参数，未下载预训练权重或改驱动/共享依赖。

同gpu0-research.lock、单GPU串行：native/mature/late三独立结构进程，native/mature两独立全层状态进程，以及一个event/支持范围进程，共六个均退出0。每进程600s、allocator/planner0.20、req8/KV512/context128，启动前5947MiB空闲，命令/PID/资源快照与日志齐备。自有cache独立，全部子进程收齐，最后compute-apps为空。未运行成本矩阵。

## 实际图与状态结果

| 变体 | graph每次KV核 | graph总核 | eager每次KV核 |
|---|---|---|---|
| native | index60 / store0，双stream各30写 | 378 | index60 / store0，单stream |
| mature（capture前） | index0 / store30，单stream | 348 | index0 / store30 |
| late（capture后） | index60 / store0，双stream各30写 | 378 | index0 / store30 |

三个raw CUPTI共12区域由QA独立按同步标记重数。late证明数值一致/CPU op非零不足以证明图接线。378→348只证明本例核结构，不按比例推算加速；完整CUDA Graph edge形式化证明/任意调度内存安全不在本例观察范围。

三变体各12步原生decode，含B3→4/B5→8 padding、8→3→1缩减、非默认stream、固定buffer/输出别名与池回到req8/KV512；完整输出先clone再转CPU。跨变体24对完整logits为FP32，按uint32逐位一致。另两次独立GPU采集12步全部30层实际新写locations，24份FP16 K/V按uint16逐位一致、shape/finite/key齐全。两状态进程参数完整SHA相同，独立状态进程的logits也与相应结构进程一致。

QA在每次graph前保存全部非目标真实槽的K/V比特，排除目标locations和dummy0，graph后逐层核对未改变；动态locations唯一且均正值。只对本轮受控写入和非目标槽观察负责，不外推整池内存安全、生产取消或ACK未知恢复。

同一严格比较器拒绝24个置零、10个陈旧快照，以及错shape/错dtype/NaN/单bit篡改/缺key五项，合计39个离线负控。它们是新GPU快照的CPU变体，不是GPU故障注入。首版QA比较器误假设logits为FP16而失败，保存首版；修正为实际FP32/uint32后重算，KV仍严格FP16/uint16，未放宽数值容差、未重跑GPU。

## 支持范围与依赖

真实caller K/V非连续view stride[960,64,1]经直接store，无wrapper fallback/连续化预处理；原生图和eager核证据单列。额外QA组件用两个动态location集合、三个非默认stream，通过producer-ready→writer-done→reader-done显式event链验证真实非连续输入写入/读取；只等待末端event，无torch.cuda.synchronize全局同步。这是组件依赖补证，不能替代任意Engine图的竞态证明。

k/v scale、隐式dtype转换、量化store_dtype和层范围共五个不支持条件均在cache修改前拒绝，拒绝前后cache字节不变。正常退出与故意异常退出均恢复原类方法。全路径正向仅FP16，不外推BF16、量化、offload或scale。

## 复现及未执行项

run.py --source <固定19e63a1完整tools/perf/operators/local_gpu目录> --output <全新QA目录>，使用既有持久Python；QA cache路径必须另选新的自有目录，原research锁保持。它前台运行三结构、两状态和组件进程；state.py在调用真实ModelRunner前后独立采状态，不改框架。summarize.py <QA目录> <汇总目录>重数trace、比较完整数组/负控及支持范围。候选脚本未修改；独立代码及完整执行源/原件/输入输出hash随附件交付。

作者三对六进程6–7ms/13–15ms全部cost.json原样归档为author-reference，与本轮QA结构分开；漂移尚未解释，不判稳定收益。静态ForwardBatch成本不是TTFT/TPOT。含hook/同步/参考/CPU快照的本轮trace不作性能基线。本地GPU研究已授权，不等待E1。

下一项RoPE+KV仍先核固定caller、原地别名/V视图/save_kv_cache语义，在capture前安装或显式重捕获，先等价性再干净A/B；默认cap8保持。完整预训练权重、语义质量、完整Engine/在线scheduler/serving基线、nvcc/Sanitizer及生产验收仍未完成，MAAS-7/10继续in_progress。

QA未改产品代码，四份产品来源锁保持原基线；本机无gh/可用GitHub写入工具，未创建QA PR，提供统一基线增量分支与可审代码/证据，目标为agent/MAAS-10-offline-metrics。
