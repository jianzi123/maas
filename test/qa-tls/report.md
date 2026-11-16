固定PR #14四锁head 00a3e62c539b726113fa21686e29096be88820e2、代码ada28d8f3552d18a3f9cfc448b4b54e1dabc0b93完成定向独立TLS组件复验：38/38通过，作者原13/13已独立复跑，两个范围分别记录、0失败/跳过。未发现新产品失败。PR仍未合入统一分支，本结论不代表生产入口消费或真实单模型闭环通过。MAAS-3/7继续in_progress。

原始结果qa-tls.txt含完整测试名/状态，qa-results.json按leaf去重。Go1.26.0、Ubuntu-22.04 WSL2 Linux6.18.58.1-microsoft-standard-WSL2 amd64；实际本地CA、证书文件、TLS handshake及HTTP/SSE body参与，使用临时fixture，不是实际Higress、Secret或生产身份。无SQL、供应商/模型、GPU或旧工作台运行。

独立通过范围：
- 双向TLS成功，服务器真实VerifiedChains/PeerCertificates非空；固定HTTPS endpoint、专用RootCAs、客户端pair、TLS最低1.2、Proxy=nil、原Relay字节/行设置保持。
- 持续SSE头先成功，100ms头时限之后仍收到250ms显式等待后的完整尾帧。迟头70ms/300ms负例拒绝。均为测试注入，不外推性能收益或SLO。
- 预取消client.Do没有拨号、WroteRequest或peer handler增量；活动body取消返回错误并使服务端context结束。Close只关idle时既有活动流仍能完成。
- 环境HTTPS_PROXY/ALL_PROXY哨兵未接收到请求，另核Transport.Proxy=nil，避免只凭loopback默认绕代理误判。301/302/303/307/308均返回原状态，不命中redirect目标。
- 正确CA但错server SAN、不可信server、client错误EKU均在握手失败，错误身份不进入peer handler。client过期/未来有效期、错pair、缺/空/无效PEM和超长CA配置失败。超长负例是有效CA追加空白到65537字节，若仅PEM解析而没有长度限制本应可用，故不是用随机坏数据冒充大小门禁。
- HTTP endpoint、userinfo/query/fragment/path、dial/header缺失或超一分钟、byte/line为0或超过上界、nil core均拒绝。23个配置负例返回ErrUnavailable，不回显私钥、私有标记、路径或userinfo。

上述38项包括7个基本transport场景、5个redirect、3个证书握手负例、23个配置负例。未把TLS内部Do取消当作业务取消/预算/唯一结算证据：本轮core是未连接数据库的Store占位，没有调用Relay.Forward，也没有平台request_id。没有把文件路径作为交付链接，更没有将临时CA注册进系统或使用真实上游凭证。byte/SSE行上界只验输入门禁及传入Relay，client.Do本身的body截断不是工厂承诺；Forward路径与原业务取消/账务按后续实际装配另验。

四锁独立复证：head相对代码提交恰好只改deploy/build-sources.lock.json、runtime-interface.json、dependencies.lock.json、identities.json；按代码Git archive逐字节重算backend517/517、console68/68全部匹配。sourceCommit指向ada代码；deploymentApproved=false、productionWiringVerified=false。qa-locks.json保存结果。工厂在该增量尚无cmd生产消费者，真实H1–H4/Secret/registry/validation、provider批准和准确来源输入仍缺；不据工厂构造成功或本地mTLS提升Ready/Callable。

复跑入口bash test/qa-tls/run.sh，需要显式批准Linux Go1.26和自有缓存；Go overlay仅增加独立测试，生产文件与四锁均未修改。原TestRelayTLSRuntime直接复跑，未改其oracle。临时PKI由Go t.TempDir正常清理，所有httptest listener由Close结束，测试进程及专属工具缓存已清理；qa-cleanup.json记录生命周期与进程检查。证据包不包含任何测试私钥/证书原值。首次运行全部通过，无产品修改/重试放宽。

旧R1–R3、UI16-U2独立10项、Delete/Usage/Reader及QA-001/002/003各保留原SHA/范围。本轮未重跑SQL、历史D1/GPU/浏览器/全仓或A01–A34；13与38不能加成模型/组合验收数量。组合#10/#13/#14后仍须重算四锁，再验证同一受保护入口、真实来源/adapter/Secret/validation和原ID非空用量/结算；不把“已过”写为“已合入”。完整A01–A34矩阵仍NOT_ACCEPTED，生产不可调用。