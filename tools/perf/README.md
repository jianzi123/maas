# MaaS 离线性能观测分析器

此工具**严格离线**，只读本地脱敏 JSON/SSE 夹具并写诊断报告。没有 HTTP 客户端、模型入口、长期服务、GPU、集群写入、授权/结算/退款或关闭证明能力。

fixtures/synthetic.json 和 expected-report.json 中所有记录与数值均为 **SYNTHETIC / FIXTURE**。输入逻辑窗口和延迟是人造数字，运行计算器所耗时间也不是模型性能。真实链路、质量、GPU、预算/计量及发布验收均未执行。

仅支持当前票据版本元数据 v3、完整 request.finalized 3.0、ObservationEnvelope 1.0；旧 v2/2.0 不支持，版本不匹配拒绝，不静默改名。工具不读取、验证或签发真实票据，ticket=3 只是导入声明。contracts/ 是 MAAS-2 v0.4 附件的**不可变本地副本**；provenance.json 记录来源和 SHA256，不是共享契约修改。

## 运行

Python 3.10+，依赖见 requirements.txt（jsonschema 4.25.0）。本轮使用已有 Python 3.13.9/jsonschema 4.25.0，未联网安装依赖。缺包时从经批准的离线 wheelhouse 准备，例如在本工具专用 venv 内：

    python -m pip install --no-index --find-links <approved-wheelhouse> -r tools/perf/requirements.txt

从仓库根目录：

    python -m unittest discover -s tools/perf -p "test_*.py" -v
    python tools/perf/analyze.py --input tools/perf/fixtures/synthetic.json --output tools/perf/reports/synthetic.json

退出码：0=本地计算成功，2=输入或文件访问被拒绝。CLI 错误不输出原始数据/Schema 值或异常堆栈。输出路径不能覆盖输入。先验证输入再生成报告；失败时不产生新报告，调用方须检查退出码，不能误用旧文件。

夹具可确定性重建：

    python tools/perf/fixtures/build_fixture.py

build_fixture.py 只读同目录的 source-template.json（从架构合成算例挑选出的无秘密终态/观测模板），不会读取源包中的合成签名密钥，也不调用上游。expected-report.json 是已交付的固定输出实例；test_analyze.py 另有手算数值断言，防止仅靠重生成输出自证正确。

## 输入格式与导入限制

输入顶层为 schema_version=1.0、synthetic 布尔值、protocols、window、registry、requests、observations、terminals、runtime_metadata、gateway_observations、slo。synthetic 必须显式提供；false 仅标记 offline_import_unverified，不构成真实运行证明。示例是完整格式参考。

- registry: experiment_ref、run_id、cell_id、replicate；由受控导入流程关联。run/cell/replicate 不塞入共享观测或业务账本。
- window: start_ms/end_ms；预先冻结的完整批次或 drain 截止的单调时钟逻辑窗，所有发送/终止必须在窗内。end_ms=null 的请求仍 pending，不能删除尾部换吞吐。工具无法证明源记录没有漏请求。
- requests: 完整发送清单。每项的 scheduled_ms/sent_ms/end_ms、stream、transport_result、quality_pass、clock_scope、frames、visible_tokens、tokenizer_sha256、engine_token_times_ms/engine_clock_scope、rejection_code 是**工具导入 sidecar 字段**，不是 MAAS-2 新增 API。
- frames: at_ms + wire，wire 是 LF/CRLF SSE 原文片段，可在事件中间分包。事件时间使用完整事件收齐时刻；角色、心跳、usage-only、空 delta 不算可见内容。只处理平台单完成文本流；非流式记录 frames=[]。
- 每个请求需要一个 sampling_fraction=1 的 client request.observation，以保证本工具的固定分母与客户端时钟口径。稀疏服务器 trace 可额外提供，但不能凭 1% trace 反推全量吞吐。未准入拒绝必须无 invocation_binding 和终态，仍有 request_id。
- observations/terminals/runtime_metadata/gateway_observations 使用原 MAAS-2 Schema 完整校验，并额外检查跨记录绑定、唯一终态、价格快照、用量子集/总数与账本向量守恒。正式数据应由批准脱敏导入器准备，本轮未实现在线 exporter 或真实采集。
- 调用观测的 active_revision 按调用捕获的上下文匹配 invocation_binding；当前 CR desired/observed 状态放独立发布事件，不能由当前 CR 回填旧请求身份。RuntimeMetadata 记录实际 observed 摘要，不能复制 desired 伪装实测。
- visible_tokens 必须是固定 tokenizer 对完整可见输出的计数，并与实际 RuntimeMetadata.tokenizer_sha256 相符。计算器只核验声明/关联，不加载 tokenizer 或验证计数来源；缺计数就不算 TPOT 代理。engine_token_times_ms 在自己的 engine_clock_scope 内求间隔，绝不跨时钟与客户端相减。
- 输入须先脱敏；常规导出禁止真实正文、平台 Key、上游凭证、票据或带秘密 URL。报告不输出 SSE 正文，只保留受控 request/revision 引用。高基数关联数据不能直接变成 Prometheus labels。

这里的完整 client 记录、可见 token sidecar 与本地 SSE 是工具的受限输入规范；并不声称支持全部生产导出格式、所有供应商 SSE 协议或稀疏 trace 拼接。Schema 验证不替代来源真实性、可信 reporter/JWS 校验或 MySQL 真账核对。

## 计算与报告 1.0

报告实例见 fixtures/expected-report.json，机器格式见 report.schema.json。结构如下：

| 字段 | 口径 |
|---|---|
| report_version / synthetic / evidence_kind / authority / input_sha256 | 报告版本、合成标记、诊断边界及输入溯源 |
| counts | sent、admitted、五类终态、pending、rejected；同 ID 同内容重投去重，冲突拒绝 |
| rates | success_rps=成功/整个逻辑窗；技术错误/sent、拒绝/sent、已准入非成功/admitted 分列；取消不偷算技术故障 |
| goodput | 成功且质量/TTFT/E2E和可判定TPOT满足输入 SLO；单 token TPOT不适用；未知/零输出不伪造资格；缺 SLO则 count/rps=null |
| distributions.all_sent_observed / success | 每项 count/denominator/missing/coverage/p50/p95；E2E仅成功，失败看 termination_ms；失败观测不从 all_sent 中删掉 |
| rows | server_first_chunk_ms、可见/计划 TTFT、E2E、终止时长、visible_tpot_proxy_ms、engine_generated_tpot_ms、chunk_gap_ms 分开 |
| usage | 已知 input/output/total 分别求和和已知子集吞吐，coverage 分母为 admitted（含 pending）；全部未知为 null，已知真0为0 |
| diagnostic_reconciliation | admitted=已观测终态+pending；unknown_held单列，不算actual；金额按 currency/price_snapshot/version 分组 |
| revision_groups | 完整 invocation_binding 分组及 request_ids；跨修订总计只描述输入批次，不能作为同配置A/B |
| stages_inclusive_only | 各 stage 原有 inclusive 分布；不求嵌套总和、不用p95相减推断网络或引擎 |
| unattributed_ms / inclusive_stage_sum_ms | 固定null：当前输入无时段区间/独占信息，不能求残差 |

分位数使用 index=(n-1)*q 线性插值；n<200标 descriptive_only，不报 p99 或可靠性保证。usage 的缓存输入/隐藏推理是子集，不重复加到 total。钱是十进制字符串 atomic 整数；held 不计真实成本，不跨币种合计。缺失数据不填0。goodput 的 eligible 是有资格判定的请求数，pass_over_sent 分母始终完整 sent；可从 eligible/sent 得资格覆盖率。

固定夹具的手算核对：9 sent、8 admitted、4成功、2失败、1取消、1拒绝、1 pending。逻辑窗为人造1秒，因此成功吞吐代数值4、有效吞吐代数值2；**这不是 MaaS 性能结果**。可见 TTFT 已知5条、成功中已知3条；第1条可见TTFT=100ms而服务端首片=60ms，TPOT代理=80/3ms、独立引擎TPOT=30ms。已知total token合计41，未知token held=420，后者绝不并入实际用量。

## 方法、计划与实现范围

docs/method-v0.2.md 更新方法与 v0.4 兼容；docs/experiment-plan-v0.2.json 保留 execution_enabled=false、审批值/基线/收益为空；docs/observability-handoff-v0.2.csv 保留 OBS01–OBS19 并逐项映射真实契约字段，未存在的细节留在受控 trace/rank/run sidecar 或待审扩展，不能给封闭协议擅加字段。

代码仅在 tools/perf，独立于 MAAS-11 的控制器、api、共享契约和根 Go 模块。工具不读集群/数据库/Secret、不释放slot，不建立新预算真源。真实指标采集、GPU/模型质量与基线、一次优化对照、Higress/MySQL并发恢复及A01–A34运行验收尚未执行。

真实运行仍需最小Key/三维预算/全局slot/request/唯一结算内核，以及模型/权重许可、GPU/互联、获准环境版本、SLO、调用额度、预算/价表及停止阈值；由Mika后续明确交接。
