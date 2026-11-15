# D1 消费端独立 QA

本目录沿 `qa/maas-7-relay-c7e863b` / `dbba820` 接续，仅增加独立核验入口和矩阵，不修改产品或性能工具。固定源 `c7e863b11fb34ee2828c947393444e1e5a9baf08`，消费 `df8d40efa08fcbb72e4a29a922d15ef22a849ec4`。本次只覆盖 `8420aaf..df8d40e` 的 17 文件增量，不签收整份 PR #7。

使用 Python 3.10+、jsonschema 4.25.0、Git。通过 Multica 认证附件下载：

- review：`01a1d47f-6bda-7684-b14e-d2fd4a4b3177`，解压到 `d1-input/review`。
- evidence：`01a1d47f-8047-7e95-b210-8c2cd453ec16`，解压到 `d1-input/evidence`。
- HTML：`01a1d47f-8649-70d3-ab61-07447ca4f114`，保存原名到 `d1-input`。
- 历史归档：`01a1d42c-eb2b-7b95-97ed-2a78e8019b29`，保存原名到 `d1-input`。该归档含其他历史资料，消费者仅读取四个允许成员及 hash manifest；交付新证据时不转发其环境/数据库日志。

将固定消费提交的 `tools/perf`、`docs/performance` 用 `git archive` 导出到全新 `d1-consumer-fresh`，Git 仓库须含源提交及消费提交对象。不要把 17 文件增量作为完整消费工具；不要用 PowerShell 文本管道导出 Schema（可能改变字节）。不执行 manifest 中的采集命令。

在 QA 仓库根目录执行，所有路径均可调整；输出目录必须不存在：

```text
python test/qa-d1-consumer/verify.py --consumer ../d1-consumer-fresh --repo . --inputs ../d1-input --output ../d1-results/independent
```

先在全新消费目录运行受影响回归：

```text
python -m unittest discover -s tools/perf/diagnostics -p "test_*import.py" -v
```

本轮该回归 42/42；独立检查最终 46/46，分开记数、不相加为场景总量。首轮 40 项为 39 过/1 失，原因是 QA 错误假设历史原件含真实零值。原件实际为 16 条未知和 4 条非零已知；原始失败 oracle、脚本和命令保留在证据包中。仅重核失败项并新增 6 项检查后通过；`--resume` 只跳过已通过项，不重跑源端或整套回归。零值与 null 的差异由明确标注的合成衍生归档另验，不冒充 Go 原件。

报告、局限和后续门槛见 [report.md](report.md)，A01–A34 接续见 [matrix.json](matrix.json)。
