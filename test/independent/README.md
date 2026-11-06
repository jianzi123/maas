本目录为 MAAS-7 独立测试接续，不包含产品实现。

固定产品基线：821269bd32164918443e63e66c6a7cbce45d440b；发布依赖：4d45c6f5a033783a8c1a8886f2b6e65eff7a3cf4；消费者：428d44e0b4f64ec628e6a945fd4b63a0e45c260b。

management_test.go.in 从该产品版本的 test/integration/management_test.go 派生；原15组保留，另加6组独立断言。通过 Go overlay 替换测试文件，产品源码未修改。6组覆盖错误Origin、同namespace跨scope游标与原ID查询、缺私有历史payload回滚失败关闭、503后Unknown保持、同名重建新UID隔离、Paused到Paused保存的Update归类。派生测试中重复的原15组只算复验，不累计为新场景。

kernel_cases_test.go.in 来自 QA 提交 e6c7be21d40f6e1115b9830a46a0407bf825608c 的附件。本轮仅选择 TestQATerminationMatrix/before_headers/transport_eof；原断言保留，增加原allocation释放后不退款、不释放后继slot、不改原终态及证据日志。其余历史测试声明不属于本轮执行清单；不要以本轮结果推断整个旧文件通过。合成Token held140/金额held520000只属于该测试profile。

运行前在已批准的本地临时环境准备固定Go1.26.0、MySQL8.4.7、Redis6.0.16以及envtest API-server1.36.0/etcd3.6.8。脚本不会安装依赖、创建集群或调用模型。显式提供 MAAS_TEST_GO_ROOT、MAAS_TEST_MYSQL_BASEDIR、MAAS_TEST_REDIS_BASEDIR、KUBEBUILDER_ASSETS；可提供 MAAS_TEST_GOMODCACHE/MAAS_TEST_GOCACHE，写入必须位于自己的缓存。MySQL/Redis二进制路径须符合原scripts/test-mysql.sh的task cache限制。

运行 bash test/independent/run.sh。脚本前台依次执行原72组共享回归、原15组管理HTTP，再执行定向EOF与独立管理补充。Go overlay只作用于测试；所有临时服务沿原编排退出清理。输出在artifacts/qa-*。如要只重跑第二阶段，设 MAAS_QA_PHASE=independent。

schema.py 读取本次真实HTTP响应，并从固定前端Git对象提取原始Schema；需要Python jsonschema。它只是响应Schema检查，不能充当Vue组件或浏览器证据。稳定/草案Schema随本目录交付，来源保持固定SHA。

metadata registry、受控上游及网关producer仍是测试适配；真实API-server/MySQL/HTTP不等于真实Higress、供应商模型或GPU。不得把202、Running、Ready或Schema通过当生产Callable。QA-002原2319eb6受控通过范围沿用；本轮不重新宣布完整19格矩阵或A01–A34通过。
当前QA-003未修复时run.sh预期以非零状态结束；原始失败必须保留。Schema脚本不改变该功能失败结论。
