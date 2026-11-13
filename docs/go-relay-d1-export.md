# Go relay D1 源端采样

本增量沿PR #6/d2d7869接续。原QA的Usage20/20、Reader12/12结论保留，不据此关闭本轮新见证。普通SSE data出现顶层error时，sourceEnvelope立即拒绝，Forward以失败终态结束；后续usage/finish/DONE不再读取或恢复成功。非流式完整响应也复用该拒绝边界，供应商error正文不输出。

## 三个测点

- `first_protocol_ms`：第一个合法data协议事件接收时刻（role、空delta、usage-only均可），不包括注释心跳或DONE。
- `first_content_received_ms`：第一个合法非空delta.content事件接收时刻，取Next返回后、receipt耐久写和客户端Write之前的单调时钟。空字符串、role-only、usage-only和无内容完成均不触发。
- `first_content_write_ok_ms`：包含该类非空content的首次完整Write返回且err=nil的时刻。失败Write不记成功。`first_content_flush_attempt_ms`仅表示调用了http.Flusher.Flush；该接口没有成功ACK，不能称客户端收到或成功flush。

原终态`first_chunk_ms`保持字段名与“Go收到首内容”含义，以原请求Received为起点记录首个非空内容，排除诊断等待、Write与Flush。新内部采样以Forward进入时刻为0；不能直接把两种起点混用。没有内容时原字段与内部content/write字段保持null。非流式本增量只导出end/result，协议与content测点为null，不伪造token事件。

## 有界路径与脱敏

安装方在进程启动时创建 `NewRelaySampler(runID, instanceID, sourceRevision, capacity)`，绑定到同一Relay；未配置时不导出。容量必须1–4096，实例UUID由运行方登记；采样器创建一次生成本进程采样boot标识。每个Forward最多向固定容量channel非阻塞发送一条固定大小summary，满则计Dropped，不等待消费者、不回调用户代码、不额外写MySQL。每请求只保留首测点，不随分片数增长。消费者在业务路径外读取Records并写JSON；不在请求内导出文件。未准入或缺依赖时result可能unknown；不能由样本授权调用。

`RelaySample`/`maas-go-relay-source-1.0`为内部诊断源，**不是ObservationEnvelope1.0、终态事件或账务证明**。只含白名单身份、发布revision和时间/结果，既无prompt/response/error正文，也无Key、Secret、URL或私有payload。Dropped分母须另报；不把丢样本当作无请求。采样器禁止运行时并发替换配置。

## 实际受控采集

在现有授权临时依赖缓存完整时，从仓库根目录前台运行：

```sh
MAAS_D1_SAMPLE_OUTPUT=artifacts/go-relay-d1.json \
MAAS_TEST_PATTERN=TestMySQLRelaySampling \
MAAS_TEST_LOG_NAME=go-relay-d1-tests.txt \
bash scripts/test-controlled.sh
```

这是实际Go Relay→受控HTTP上游＋真实MySQL内核执行，非Python合成时钟；只有网关/proof为明确替身，没有真实Higress或模型。运行10种情形：正常内容、全空、usage-only、error后finish、内容后error、raw EOF、写失败、取消、超时、采样满。注入35ms首内容前延迟和60msWrite延迟，用来验证测点分离，**不作为平台性能/SLO结果**。9条实际summary导出，满队列那次为可核验丢样本负例；测试断言业务终态仍唯一且未失败为成功，失败预算held保留。

源样本的source_revision=`working-tree-d1`明确表示受控工作树采集；交付manifest另记实际提交、源文件hash、命令、原始JSON hash，不能声称采样时已经知道尚未创建的commit。进程instance/boot是本次采样器真实生成的本地身份，不是已批准生产registry或Worker身份。trace/experiment/cell、组件、校准缺项均明确列出。退出会清理自己的MySQL/Redis/socket和数据，不留长期服务。

## 给8420aaf消费端的映射

已只读核对MAAS-10提交 `8420aaf956b7d44d52c2bbe52c9d20d15fcdb781`，本轮不修改其tools/perf。

| Go源 | 工具sidecar接线 |
| --- | --- |
| run_id、request_id | registry.run_id和请求关联；experiment_ref/cell_id/replicate尚须运行编排补齐，不用request_id冒充trace_id |
| instance_id、boot_id、clock_scope | 同一Go采样器的clocks/interval归属；各请求以自身Forward=0，不跨请求或跨组件计算绝对顺序 |
| publication_id、release_revision | 核对原调用不可变绑定；完整binding_sha256/runtime_metadata_ref仍须获准源映射，不能散列两个字段冒充完整绑定 |
| first_protocol/content/write/flush、end | Go局部测点或区间边界；未观测前驱不自动推导exclusive依赖，Write返回不等于client receive |
| result、return_error、缺组件清单 | 显示失败/unknown与覆盖缺口；不能倒填业务actual或安全释放证明 |
| 原始JSON hash和源文件hash | 对应工具evidence来源索引；不因此提升为生产可信证据 |

完整sidecar仍需原指标数据集、trace及完整绑定/工件/实验身份，故本次源文件不能直接冒充可通过封闭sidecar校验的输入。原性能专家在工具侧做适配和缺项拒绝/降级；真实校准缺失时保持scope隔离。公开Schema/Observation1.0/票据v3/终态3.0和旧迁移均未改。真实adapter批准、Higress/Secret/validation、接流集合及生产装配仍未齐。

## 开销复现

```sh
go test ./internal/kernel -run '^$' -bench BenchmarkRelaySamplerFull -benchmem
```

该微基准只测满队列丢弃固定summary，不能外推整链路开销。完整采样固定内存上界为capacity×sizeof(RelaySample)加channel元数据，每请求固定测点/一次非阻塞offer；没有新增数据库写放大。真实平台负载的采样比例、队列容量及吞吐影响仍须原E1批准负载验证，不能用本轮受控延迟注入冒充优化收益。

本轮Windows/Go1.26、Ryzen7 7745HX满队列微基准为10.31ns/op、0 B/op、0 allocs/op，仅offer丢弃路径；不包括时间戳/summary构造和真实负载竞争。全仓Go测试、vet/build通过；实际临时MySQL/HTTP10/10场景通过，导出9条正常/负例样本，page/模型/GPU未执行。正常样本协议47.35ms、内容83.20ms、完整Write143.67ms，延迟来自明确35/60ms测试注入。原80与QA20/12未整套重跑、不累加，新增见证仍交原QA独立确认。
