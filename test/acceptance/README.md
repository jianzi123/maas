MAAS-7 独立复验入口；基线 PR #2 `4f3eb9358f26ebab637a549b795651171d3b924f`（含 PR #1 `6302256`）。只新增本目录，不修改实现或其他角色目录。

- `kernel_cases_test.go.in` 通过 Go overlay 编译为 `internal/kernel/qa_acceptance_test.go`，复用作者已审阅的 SQL 初始化夹具，断言由 QA 独立编写。H1–H4/批准 profile、绝大部分 rate gate、受控 HTTP 网关仍是替身；现有独立 Redis 场景使用真实 Redis。
- `run.sh` 调用既有临时 MySQL/Redis runner；保持本次运行在前台，结束后 trap 清理精确子 PID 与专有 datadir。新 QA 失败用例是已知缺陷回归，禁止通过 skip 或改期望掩盖。
- `review_contract.py` 独立复核草案，要求 Python + jsonschema。取得附件 `01a1ab52-be21-7667-87cf-fcee92844e9c`，解压后使用。不是 HTTP 实现验证。
- `probe_admin.py` 是等待装配的新查询端点的只读验收入口；要求原服务端 request_id、原 CR UID 和通过环境变量提供的管理 Cookie，仅允许已授权 loopback。没有运行中的接口时不执行，也不以空结果判通过。

从仓库根目录执行：

```sh
# Go 1.26.0 Linux / MySQL 8.4.7 / Redis 6.0.16 放入原 scripts/test-controlled.sh 所要求的本任务 .cache 路径
bash test/acceptance/run.sh
# 只复测本轮独立场景
MAAS_TEST_PATTERN='^TestQA' bash test/acceptance/run.sh
python test/acceptance/review_contract.py --draft ../inputs/draft/unpacked --output artifacts/qa-contract.json
python -m unittest discover -s tools/perf -p 'test_*.py'
```

后端真实只读 API 就绪后执行（此命令本轮未执行）：

```sh
# MAAS_QA_ADMIN_COOKIE 由安全渠道注入，不在命令历史/文件中写原值
python test/acceptance/probe_admin.py --base-url http://127.0.0.1:PORT --request-id ORIGINAL_SERVER_ID --namespace NAMESPACE --name MODEL_RELEASE --cr-uid ORIGINAL_CR_UID --output artifacts/qa-http.json
```

该 probe 覆盖原 ID 的精确一行/禁止分页默认、非法 ID、匿名访问及原 UID 的历史读取/缺参；0 行 unknown、跨日保留、403/404 可见性、503 存储故障、未知写入、409、容量/held 投影和浏览器联调仍须按矩阵/报告中的受控数据与故障条件扩展。只读 probe 不生成请求、不做管理写入；不提供自动重试生成或回滚。

全部临时限额、币种 TST、价格、模型和身份是合成测试配置，不是部署默认。安全隔离不等于容量恢复，slot 释放不释放财务 held。终态继续 3.0，D1 3.1 未切换。
