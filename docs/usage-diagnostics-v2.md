# QA-001/002：独立耐久诊断与截止分类

本增量接续 `6dc3914`，继续同一 PR #2。实施依据是 Mika 在 MAAS-7 的 `01a1aba0-d123-7001-b0bf-91fae22e68bf` 补充及架构收口 v2（附件 `01a1ab9a-d947-7c65-9398-6875fab20d5c`）。原 48 场景记录保留，不能与本次重跑简单相加。

## 保存与账务边界

新增显式迁移 `0003_diagnostics.sql`，不改已发 0001/0002 或发布迁移：

- `request_snapshot_digests`：在**唯一准入事务**对 Go 实际建档的原始快照字节 SHA256 保存；诊断直接读取该值，不能从当前 profile 或恢复 owner 的重建对象重算。旧请求无此原始摘要时故障关闭，不伪造回填。
- `request_usage_diagnostics`：追加式 BLOB，只保存内部 Diagnostic `0.1-draft.1` 规范 JSON，最多8192字节/条；不含用户文本、响应正文、Key、DSN或凭证。`authority=diagnostic_only`，不是第二账本、授权票据、H2关闭证明或最终计费收据。
- `diagnostic_policy`：独立安装身份显式设置每请求记录数、字节上限及批准保留策略引用；无默认天数、不自动删记录。运行身份仅读策略。测试用64条/262144字节及明确合成保留引用，不是生产默认。

receipt 在 usage 帧或完整响应转发前先提交。结束另追加 termination，精确原因保持 `eof/client_write_error/explicit_cancel/deadline_exceeded/parse_invalid/usage_conflict/diagnostic_limit/normal_completion`；没有往3.0或ObservationEnvelope1.0暗加字段。为 termination 预留一条及8192字节；超限停止正常转发并保守结算。

相同 `(request_id, owner_fence, sequence)` 同规范字节幂等，异内容拒绝；新记录序号必须连续。每次写入同 guard X→原 request 锁核对当前 owner/fence、原快照摘要和完整 invocation_binding。旧 owner/fence 迟到写拒绝，已写记录继续可读。COMMIT ACK未知只按原键读回并核对完全相同字节，不能创建新记录身份猜成功。

诊断写失败立即停止该帧正常转发，在独立限时上下文尝试原唯一保守终态，不发正常 DONE、不重发生成。**失败关闭测试通过不等于该次观测已成功保存**；日志/存储故障不被掩盖成“观测完整”。

## EOF/写失败后收到的 usage

即使帧包含12/7/19、cached4、reasoning3，该异常夹具仍没有最终计费权威性：五个数持久保存为诊断，原终态实际五项为null，Token held140、金额held520000（合成TST预留），请求/终态/汇总各一次。已存 receipt 后，终态 `missing_reason=not_provided`，不再标 `*_before_usage`。没有 receipt 的原 before_usage 分类保留。

正常完整响应/DONE仍沿既有批准 profile 的结算路径；诊断不会自动成为结算参数。已终态的迟到诊断不改预算/终态；H2关闭证明只释放原 slot。Go owner 在 receipt 提交后 os.Exit(23) 的进程测试已接合：新实例读到原五项计数，过原截止后唯一 interrupted，仍为未知实际/held，且不误标before_usage。未测试MySQL断电/HA。

## QA-002

流中和非流式读体硬截止都使用原 sendCtx 的首个终止原因；sendCtx 已DeadlineExceeded后父context再Cancelled，不覆盖为取消。显式取消仍为cancelled。原因在清理cancel前读取；writer错误本身不证明用户点了停止，termination记client_write_error。parent deadline早于硬截止、headers前/后和usage前/后均有受控用例；无正常DONE、无重新生成。

## 给独立 QA 的读取入口

没有新增公开HTTP诊断路径，也没有扩展 RequestLookupPage 的账务列。可在获准主库/测试库使用：

```go
reader, err := kernel.NewDiagnosticReader(readonlyDB)
if err != nil { return err }
records, err := reader.Read(ctx, originalRequestID)
```

该 reader 只需 `maas_diagnostics_reader` 的诊断表 SELECT，不需要 Key pepper、publisher 或预算写权限。也可由测试通过原 kernel.Store.ReadDiagnostics 读取；精确单记录恢复为 ReadDiagnostic(requestID, ownerFence, sequence)。权限模板不给 publisher/operator 诊断读写，运行身份无诊断UPDATE/DELETE。保留策略由安装渠道批准，无策略不能声称生产耐久观测关项。

原 SnapshotDigest/调用绑定、receipt五项与termination原因是 QA-001 的新读取 oracle；terminal.usage 保持null、held保持完整原预留。禁止为让旧断言“terminal.total=19”通过而改财务行为或伪标3.1。

## 复现、事实和未执行

`bash scripts/test-controlled.sh` 运行原48场景及新增9个诊断relay模式、1个重复/冲突/fence/ACK场景，总计58个数据库/受控场景；专用子进程入口不计额外场景。新增首次失败为测试服务器未消费请求体而等待连接关闭；夹具现先读体并设有界等待，没有删除或skip该场景。另有上下文首原因单元测试。

v2的21个Schema正反样例使用原Schema独立校验；runtime每条记录同样按原Schema验证。新Schema字节/来源见 diagnostic-provenance.json；旧终态3.0、ObservationEnvelope1.0、预算计划和既有迁移保持不变。最终命令、原始Go事件和MySQL输出随任务评论提供，以实际新SHA为复测基线。

真实部分包括MySQL、诊断事务/去重、HTTP转发顺序、Go进程退出和Redis重启；Higress/证明生产者仍是受控替身。production Operator继续DependencyMissing。真实H1–H4/Secret通道/生产身份registry、保留修订真源/FE-R02、浏览器、MySQL崩溃/HA、模型/GPU与A01–A34整体验收未完成。QA-001/002是否关闭由原独立QA按新SHA复测，不由实现方自行宣布。
