# GEMM finite 正确性门禁修复（v0.5.1）

问题：旧gemm.cu仅比较abs(output-reference)>tolerance；IEEE NaN的大小比较为false，可误通过并继续计时。Mika提取的旧循环无需GPU即可复现exit0。本次仅修此门禁，原dtype、shape范围、容差、协议与禁用计划保持不变。

## 共用函数与失败路径

gemm_validation.h中的validate_gemm_results显式检查candidate、cuBLAS baseline和double reference全部元素finite；随后检查容差及误差算术finite，并按原atol=1e-4、rtol=2e-4判定两份输出。失败结果passed=false，错误max值为无穷哨兵；失败结果不会输出为成功报告。

CUDA与宿主driver都调用同一validate_then_execute。预热、CUDA Events创建/计时及成功JSON都在其成功continuation内；数值失败退出1，continuation不调用。gemm.cu仍在失败后清理handle和分配；初次candidate/baseline调用是取得正确性样本，不属于预热/基准计时。

为避免编译器假定所有数值finite而删除检查，宿主编译禁用fast-math/finite-math-only；header检测到相关宏会拒绝编译。本轮实际验证了该拒绝路径。

## 可复现的纯宿主回归

    python tools/perf/operators/check_gemm_host.py --output tools/perf/reports/gemm-host.json
    python -m unittest discover -s tools/perf -p "test_gemm_host.py" -v

需要现有GCC/Clang兼容C++编译器。脚本在自有临时目录编译、收集进程退出码/输出并清理，不依赖CUDA、Torch、GPU或服务；没有编译器时unittest明确skip，本轮并未skip。独立矩阵覆盖21场景：

- candidate与cuBLAS各NaN/+Inf/-Inf，reference的NaN/+Inf/-Inf；
- 尾元素NaN、两份输出各自有限错误；
- NaN/Inf/负容差及容差溢出；
- 原始单元素NaN输入；
- 正常精确值、容差内、带符号零和容差边界。

17个拒绝场景必须退出1、stdout为空，warmup/timing/reporting都为0；4个正常场景退出0，三个计数均为1且JSON标host_gate_only。另单独测试-ffast-math编译失败。这些计数验证了共享门禁的控制流，不是实际CUDA预热/计时证据。

## 验证边界

本轮使用已有宿主GCC4.9.2/C++11编译此header和CPU driver，不代表该编译器适合作CUDA13的host toolchain。CUDA translation unit仍未编译，CUDA/Triton算子、低精度/模型质量与性能收益均未验证。GPU/引擎执行计划保持execution_enabled=false，Higress和E1真实链路仍按后续门槛执行。

旧反例源码是旧循环的独立拷贝，修仓库不会自动改变它：验证记录分别保存“旧拷贝exit0复现”和“新共用门禁同输入exit1”，不能把旧脚本误说成已动态引用新函数。
