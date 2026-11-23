ELIT-QA-01/P2 在离线门禁校验范围关闭。旧失败报告 `report.md`、原始 `results.json`、原最小反例入口与 df4d45cb2c477650404da9da72a0fb0074a86b59 历史保持；本次没有修订产品或重跑 GPU、模型、Chat/Agent、SQL。

产品实现 `3a2966225cd0102663687ad281a0264cb5e0822e`；归档冻结锁 `029fd0528e99034de769d7fde6c24bee1e4a248e`；交付 `7c10e4d3397848de1f4508ec4295b7dc25324a45`；最终实际分支 head/四锁 `4ab8a277efe5edb9219d83cc9aea204add36af8e`。执行源码 `tools/perf/operators/local_gpu/analyze_kv_cadence.py` SHA256 为 `3d4c176f257afe7a977fcf1fdcfd9da2b0df9fa29eed977256c36c9291a0639b`。当前四锁指向 7c10e4d；归档包冻结在 029fd05，二者明确区分。归档28个版本化文件、四锁679个合并库存文件及包字节独立核对一致；保留 deploymentApproved=false。未执行归档 manifest 中的命令。

当前修复16/16唯一用例：1个原件正例与15个损坏反例。另1个旧版本历史反例单列，不计修复通过；总共32次实际分析 CLI 调用。每个损坏输入分别验证新输出与已有真实成功输出两条路径：新输出非零退出、无新成功报告；已有输出非零退出且文件 hash 不变，FileExistsError 明确阻止覆盖。完整命令、stdout/stderr、退出码在逐项 `.log.json`，输入变异及报告在同名目录。未使用作者36/18数量替代独立结果。

|用例|输入/断言|结果|
|---|---|---|
|P00|原始认证 ZIP，未修改 plan/阈值/向量/ledger|exit0；1080 measured、10800 calls、108 complete clusters、缺测0/无效0、Full严格0/18|
|H00|旧5f8bd5d源码，R01首门禁native=[]/mature=[]|旧错误exit0及unexpected-success.json保留；历史控制，不计修复通过|
|N01–N03|双侧空、native空、mature空|全部非零，无新报告；旧报告保护|
|N04–N05|分别缺native或mature键|同上，variants incomplete|
|N06–N07|数量1:2与2:1|同上，requires logits and KV|
|N08–N10|native缺logits、mature缺KV、双侧角色反序|同上，实际role/shape/dtype拒绝|
|N11|实际logits含NaN，元数据hash正确|同上，finite/hash拒绝|
|N12|实际有限logits不同且hash正确|同上，bitwise拒绝|
|N13–N15|错误raw hash、错误shape元数据、实际FP64且元数据正确|同上，数值/shape/dtype拒绝|

原始 ZIP 附件 `01a1dd40-3774-71ee-b270-238d67a77937`，SHA256 `64e348ddb21eb84f6a4c4827c8c0aaedeb38c2e6f4add85e591ab0775539990f`。原 plan 文件SHA `c42a4755b426fe964b7423ffb6cf4001e75f42bc52bf9ff018de6184a58c52c7`、canonical SHA `ab0ac451d9d4beffd6a879ff04bcdcd4000a256ec3194b710f5e7dabca49d9c9`均保持。校验前后317个输入文件hash完全一致；正确原件的26门禁/104向量引用由分析器逐项校验。原始缺测0不等于故障派生缺测；本轮没有重跑历史隐藏R02等全面矩阵，也没有修改原阈值、分母、采时版本、raw证据。Full严格0/18仍不足以支持独立query/idle因果或稳定收益。

实际环境为本机Windows、Python/NumPy的CPU离线分析，准确版本/UTC见 `gate-repair-results.json`。GPU执行0，模型调用0，无新的请求ID。运行子进程均前台收集并退出；没有服务、PID、socket或GPU资源待清理。原件与派生失败/成功证据保留在QA目录并归档，其他自有工作树不改动。

复现（仓库已含上列固定提交；原始ZIP经Multica认证下载）：

```powershell
python test/qa-elit01/prepare_gate_repair_inputs.py --repo ../maas --original-zip ../inputs/elit-original/MAAS-10-ELIT01-v0.22-evidence.zip --output ../inputs/elit-retest-fresh
python test/qa-elit01/verify_gate_repair.py --inputs ../inputs/elit-retest-fresh --output ../inputs/elit-retest-results-fresh
python test/qa-elit01/check_repair_provenance.py --repo ../maas --inputs ../inputs/elit-retest-fresh --output ../inputs/elit-retest-results-fresh/provenance.json
```

本轮实际验证使用等价的 `inputs/prepare_elit_retest.py` 固定导出到 `inputs/elit-retest`，后两命令的实际输出目录为 `inputs/elit-retest-results-01`；逐条分析CLI命令原样保存。随交付的prepare入口将同一导出过程参数化，未额外再跑一次门禁矩阵。

QA归档检查首轮误把ZIP中生成的manifest.json/changes.patch/BASELINE.txt当作Git源码，AssertionError已记录；随后明确三种附加元数据与28源文件，逐个核对长度/hash/Git字节。一次临时元数据读取因Windows默认GBK失败，改为UTF-8/JSON字节读取。二者只涉及QA检查解析，不是产品失败；详见归档 `inspection-notes.txt`，没有修改门禁oracle或放宽断言。当前门禁矩阵首轮16/16通过，未重跑以抹除失败。

仅关闭本缺陷。参考模板资格、后续有界holdout与因果/收益主比较由原性能角色按已有门槛继续；本次不批准合并、生产、真实模型性能、A01–A34整体或其他Chat/Agent验收。MAAS-7/10继续in_progress。
