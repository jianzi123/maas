本目录为MAAS-7对PR14 TLS工厂的组件独立验收。固定四锁head 00a3e62c539b726113fa21686e29096be88820e2，代码ada28d8f3552d18a3f9cfc448b4b54e1dabc0b93；二者差异仅四份锁元数据。产品未合入统一默认分支这一事实保留。

factory_test.go.in通过Go overlay编译到internal/kernel，使用临时CA和客户端/服务端证书及真实loopback TLS listener。38个独立leaf＋原TestRelayTLSRuntime 13项分别记录，不累加为13项以外的平台验收。PKI私钥不写源码/日志/证据包，不安装系统信任根。

本轮直接调用工厂返回的内部client.Do，core为未连接数据库的Store占位；验证TLS组件而非业务Relay.Forward。预取消记录实际DialContext调用数/WroteRequest/peer handler均为0；不代表Go业务准入或计量取消已复验。字节/行限值只验工厂输入范围和传入原Relay字段，不声称client.Do自身限制流体大小；原Forward执行业务/体积限制需后续实际装配验证。

持续SSE使用100ms响应头时限、250ms显式测试体等待，迟头负例70ms/300ms；这些是测试注入，不是性能或SLO结果。Close测试释放idle后让原活动响应体继续；不称完成客户端交付或Higress验证。环境代理使用实际loopback哨兵加Transport.Proxy=nil结构检查，redirect覆盖301/302/303/307/308。

复跑：显式指定获准Linux Go1.26的MAAS_TEST_GO_ROOT及自有MAAS_TEST_GOMODCACHE/MAAS_TEST_GOCACHE，运行bash test/qa-tls/run.sh，再python test/qa-tls/summarize.py。原测试与独立测试都仅组件，无SQL/模型/GPU/集群或旧工作台。Go的t.TempDir及服务器Close负责清理临时证书与listener，运行结束不保留服务。

QA只新增test/qa-tls文件，不改产品/四锁、不运行锁脚本重写候选来源。既有R1–R3/UI16-U2/Delete及旧QA范围保留，production批准仍false；后续#10/#13/#14组合及实际生产配置消费/真实Secret/H1-H4/validation须另验。