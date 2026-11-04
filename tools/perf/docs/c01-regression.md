# C01 共同客户端时间窗回归记录

范围：只修复未归一化的不同client clock_scope仍能进入同一window计算RPS的问题。协议v3/3.0/1.0、输入/报告格式、原固定synthetic夹具和原有计算公式保持不变。完整验收依据见acceptance-v0.3.md；其C02–C08真实运行项和收益建议不由本轮离线修复判通过。

## 缺陷与最小修复

旧提交86f5408只保证request.clock_scope与自己的client observation一致，无法证明不同request之间有共同monotonic坐标。新增跨request的client scope一致性检查，所有sent（包括失败、拒绝和pending）同样适用；混杂直接抛InputError，CLI在写报告前退出2。第一个有效request确定本批客户端scope；空批次保留原空集合行为，不声称有采集或同步证据。

server/engine观测不加入客户端scope集合；duration继续使用其原采集口径，引擎token时间只在自身scope内求差。相同标签也不证明真实同步，多发生器映射/误差/有效区间未实现。

## 新增的7个行为测试

| 用例 | 可检查结论 |
|---|---|
| single_client_clock_scope_accepts_uniform_relabel | 全部客户端统一改名仍接受，原合成计数、TTFT不变 |
| mixed_client_clock_scopes_rejected_for_all_sent_states | 只改一条request及自身client observation，成功/拒绝/pending三个子场景均拒绝 |
| request_client_observation_clock_mismatch_rejected | 单改request或单改client observation都拒绝 |
| server_clock_scope_keeps_own_duration_legal | Go独立scope的分段duration合法，服务端首片与可见TTFT仍分列 |
| engine_clock_scope_uses_own_origin_for_tpot | 引擎原点平移1000000ms仍得到同一引擎TPOT，客户端TTFT不变 |
| invalid_client_clock_scopes_rejected | 空或null客户端scope拒绝 |
| cli_mixed_clock_scopes_exit_two_without_new_or_changed_report | 混合scope退出2；无新报告、已有报告字节不变、无共同RPS或合成敏感哨兵回显 |

新增测试先在旧实现执行：混合scope的3个场景和CLI的2个场景按预期暴露缺陷（7个测试方法、5个失败子场景）。最小修复后7个针对性测试通过；交付的干净导出完整回归日志另外记录原41项与新7项的实际执行结果，不能只凭总数推断覆盖范围。

原反例脚本来自Multica附件01a1a67f-379f-7368-8223-5b173d6e3020，纯离线副本为fixtures/clock_scope_reproducer.py。可从仓库根目录复验：

    python tools/perf/fixtures/clock_scope_reproducer.py .
    python -m unittest discover -s tools/perf -p "test_*.py" -k clock -v
    python -m unittest discover -s tools/perf -p "test_*.py" -v

原反例预期输出PASS: rejected mixed unnormalized client clocks。完整测试日志、退出码、归档/输入hash和提交信息见本轮交付的验证记录。没有模型、GPU、数据库、发布或付费验证；这些测试不证明生产时钟同步、真实吞吐或整套C01–C08验收通过。
