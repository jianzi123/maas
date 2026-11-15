# D1 消费端独立核验记录

2026-11-13 UTC；Windows 11 10.0.26200，CPython 3.13.9 / Anaconda、jsonschema 4.25.0、Git。源 `c7e863b11fb34ee2828c947393444e1e5a9baf08`，消费 `df8d40efa08fcbb72e4a29a922d15ef22a849ec4`，QA 沿 `dbba820` 原分支。未改产品/性能源码，未执行 Go、数据库、Higress、GPU、模型或付费调用。

**消费端本次受控范围通过；D1 整体、PR #7 整体和 A01–A34 完整要求不签收。** MAAS-7/10 继续 in_progress，生产不可调用。

| 范围 | 实际结果 | 证据边界 |
|---|---|---|
| 固定输入 | raw `a2589061b5c39fb259397e6bdf6129cbdb16bce8579318438fe760642fb51458`；manifest `9cf52e7a5b3338a6f115d087a621fb3f0a932bccdc07bff7ca592ad97378eb9c` 一致 | 通过认证附件取得 |
| Git/字节 | 17 增量文件在交付包、固定 Git、全新目录三方一致；六份源文件 hash 与 c7 一致；Schema 新目录字节一致 | 拉取最初中断/缓存缺对象，经定向 refetch 恢复；没有依赖缓存 HEAD 猜测版本 |
| 原件报告 | `consume_relay.py --source-repo` 成功；JSON、HTML 与作者附件逐字节一致 | Python 消费，未重跑源采集 |
| 导入回归 | 42/42 通过 | 本轮独立运行作者的受影响测试；与作者 276/归档42重叠，不累计 |
| 独立 QA | 最终 46/46；累计 68 次消费 CLI | 检查/CLI次数不是实际调用数；26 类负例各测全新输出和既有报告保护 |
| 首轮 QA oracle | 40 项中 39 过/1 失；原断言误认为历史20条包含0 | 保留首轮脚本、results/commands；修正样本覆盖后定向重核，不改产品/不放宽拒绝条件 |
| 历史原件 | 20 个 request/19 个 case、19 条 oracle 通过和1条原失败均保留 | 与新9条 request 完全不交集；16条未知、4条非零已知，无原件0样本 |

26 类篡改覆盖 raw/manifest hash、预期 commit、六源文件 digest、run/request/boot/clock、重复/未映射 request、三层额外私密字段、负/boolean/NaN/Infinity/越界/缺前驱/逆序时间、版本、伪称完整 sidecar、隐去缺时钟/trace、源路径越界及 manifest 命令。均退出2，不产生新报告、不残留 pending、不覆盖既有 JSON/HTML/开销文件，不回显合成私密哨兵。manifest 命令只被校验，未执行。

原作者9条摘要逐request保留：succeeded3 / failed2 / interrupted1 / cancelled2 / timed_out1；另外满队列1次无摘要仅按 manifest 声明保留。9/10=90%仅为该批场景摘要覆盖。client sent/拒绝/pending、全局 drop、公共时间窗、RPS/goodput 仍 null。QA先前17条属另一批，本次未消费、拼接或重新计数。

协议/非空内容接收/完整Write成功/Flush尝试保持分开。空及usage-only仅协议有值；失败Write保留 write_ok=null、flush有值且不变成成功。Forward起点不填Received起点legacy字段，client receive不推算。独立合成衍生样本验证全部测点null与数值0；历史用量0与null/held另以标注SYNTHETIC的衍生归档验证，未声称原件提供真实0。

缺trace/完整binding/工件/experiment/cell/replicate时新源保持局部降级；作为完整sidecar直接输入被拒绝。完整合成sidecar另验缺trace/binding/experiment退出2；无校准及“零误差但未获可信验证”的校准声明均阻断跨域边，保留device局部时钟，不组成165ms合成链，不判可比。后一测试故意切换声明flag以覆盖不可信分支，其数据仍为合成，未获得真实校准。

`working-tree-d1`、`capture_commit_attested=false` 保留，交付commit/hash只作来源核对。新源actual/held/terminal仍未知，旧归档保留actual与known/held、原reserved与当前Reserved以及oracle失败/修正复跑，不以case连接两批request。历史归档hash错误、白名单成员hash/路径错误、重复成员均拒绝；额外私密/越界成员不读取/提取/回显到报告，只消费允许文件。原历史环境和数据库日志不随本轮附件转发。

**未执行项与下一步：** 源端19次调用/9函数沿dbba820已过范围保留，本轮未重跑。未验证真实Higress/Worker/GPU、生产登记instance/boot、可信跨时钟校准、同request完整客户端清单/接收测点/实验关联、全路径采样on/off及耐久恢复。35/60ms为测试注入、10.31ns为满队列offer微基准，不转为平台性能。下一批仍为同request客户端清单和关联→固定SHA/资源/负载采样on/off→获准真实受保护E1；E1/K1/R1/R2及模型收益均未验，真实计划禁用。

原始命令、结果、正反输入与JSON/HTML通过本次任务附件交付。QA代码沿原分支推送；未改或合并PR #7，本次不以新PR替代原产品评审。当前无gh/可调用GitHub写入工具，平台PR关联仍空。
