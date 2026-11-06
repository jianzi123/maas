# 按教材选练习与交付结果

从[性能总入口](../README.md)进入[六章教材](../foundations/README.md)，按本页选择练习；详细命令仍保存在原 B/A 页。先解释机制，再交固定结果，最后写优化课题。

## 按章节找到对应练习

| 主教材 | 必做的标准库教学材料 | 原练习详解与检查项 | 交付 |
|---|---|---|---|
| [第1章 请求与张量](../foundations/01-request-to-tensors.md) | shape、首输出、30ms/20ms-token/0.4请求每秒手算 | [B02报告](../onboarding.md#exercise-b02)、[B03时钟](../onboarding.md#exercise-b03) | 起止点、分母、覆盖率和clock_scope说明 |
| [第2章 调度与KV](../foundations/02-scheduler-and-kv.md) | runtime_walkthrough、worked_numbers | [A03未恢复](../advanced.md#exercise-a03) | 六轮轨迹、68/55容量上界、P5待回收原因 |
| [第3章 算子与剖析](../foundations/03-kernels-and-profiling.md) | GEMM/Attention/roofline手算 | [B01 mask](../onboarding.md#exercise-b01)、[B04参考](../onboarding.md#exercise-b04)、[B05门禁](../onboarding.md#exercise-b05)、[A01收益](../advanced.md#exercise-a01)、[A02字节](../advanced.md#exercise-a02) | shape/布局/误差、边界与成熟baseline |
| [第4章 发布协调](../foundations/04-deployment-controller.md) | release_walkthrough | 第6章题10–13 | 原身份回查、旧证据拒绝、held/slot与UID清理 |
| [第5章 框架接口](../foundations/05-framework-design.md) | 请求/BatchPlan/页/完成事件接口草图 | [A03](../advanced.md#exercise-a03)、第6章题5/6/14 | 所有权、并发、背压、TP依赖与五个故障截点 |
| [第6章 实现与评审](../foundations/06-build-and-review.md) | 14道工程题；R/D阶段完成条件 | [A04目标卡](../advanced.md#exercise-a04)、[B06回环](../onboarding.md#exercise-b06) | 一张目标卡、一份阶段交付与限制 |

三个教学模型及35项固定预期核验的命令统一放在[主教材入口](../foundations/README.md)。教学步数、虚构显存和toy journal不作为性能、真实容量或数据库耐久证明。

## 分清练习的资源条件

| 条件 | 可以做的内容 | 尚缺条件时如何记录 |
|---|---|---|
| Python 3.10+标准库 | 三个教学模型、check_examples、正文手算、接口/故障作业 | 无需安装模型、CUDA或依赖 |
| 完整CPU课程依赖 | B01/B02/B03/B04；jsonschema4.25.0，NumPy2.3.5要求Python3.11+，见[准备环境](../onboarding.md) | 记录缺包，不自动联网安装 |
| 兼容宿主C++编译器 | B05共用finite门禁 | 记录未执行；Python skip不算host通过 |
| 获准本地临时回环 | 可选B06，每case20请求、自动限时清理 | 保存原始报告；不替代Go/Higress/模型 |
| 真实GPU/模型/平台 | 后续R2/R3/D2/D3与E1–E3 | 依批准计划和具体输入执行；计划保持关闭 |

入门先完成标准库路线即可建立基础；B05和B06按条件选做。进阶读者可先手算A01/A02、写A04，再补真实数据的A03。不要因为某个可选工具缺失而把学习整条阻塞，也不要把跳过的验证写成完成。

## 工程实现练习

深入实现按[工程实现卷十二章](../engineering/README.md)与[八类代码](../../../tools/perf/engineering/README.md)逐项运行，进阶作业集中在实现卷第12章。CPU算法/本地恢复报告与原离线指标报告是不同格式，按各自入口读取。

## 不同成员交什么

新人交一页推导和教学脚本结果，讲清每个数值的来源。运行时方向交BatchPlan/KV/Completion所有权图及固定事件轨迹；部署方向交发布意图/副作用/回查状态图与对象归属。性能方向从[目标卡](../optimization-goals.md)选一项，登记成熟baseline、进入证据、唯一改动、代价与否证条件。

答案分两处：B/A题的[答案页](answer-key.md)，框架工程题的[第6章](../foundations/06-build-and-review.md)。实验产物用[实验记录](../templates/experiment-record.md)，跨角色交接按[整合地图](../integration-map.md)。

一次交付只报告本次实际执行、历史复用和未执行项；不要累加旧测试数。框架建设阶段与优化课题编号的关系也在整合地图中统一说明。
