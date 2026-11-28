QA-MIG-SHAPE-001 作者修订
=======================

恢复输入与范围
--------------

2026-11-27恢复时核对两条失效通知：集成任务01a217c5-cbec-7050-8671-afa401e55fd5（queued_expired）、QA任务01a218da-8b8e-77ca-bb19-19d679f72c63（runtime_reconnect_timeout）均未开始、无delivered comments/result。原作者5328463交付和附件仍在。跳过重复guest接收链，复用MAAS-21/7已恢复的原负责人运行；未重新分派内核或把runtime错误当产品测试失败。

实际需修的是原独立QA的50项47过3失，固定1f8/e12d代码：Applied/hash正确时缺usage_events、缺only_terminal唯一键、缺retained_release_snapshots仍被Open/checkReady接受。三例同一P1；本作者修订不替原QA关闭。

实现
----

在原validateRequiredSchema接只读物理校验，故Open在监听/Host前、ready/重授权及显式reconcile沿同一门禁：

- 原固定9份DDL生成41个必需对象（含三域journal和历史views）、50个原PRIMARY/UNIQUE约束。scripts/generate-required-physical-schema.py只生成代码常量，不连接DB、执行DDL或创建第二迁移账本。旧SQL字节不改。
- 使用当前DATABASE()范围information_schema.tables/statistics，核对象存在、BASE TABLE/VIEW类型、InnoDB引擎；每个唯一键核完整列序、NON_UNIQUE=0、无前缀。usage_events终态request_id/event_type还须非NULL。
- 缺对象、缺权限、错唯一键或必要元数据未知均required_physical_schema_not_ready，不补表/索引、改journal或回退其他DSN。运行发现异常取消本实例，阻止新dispatch；恢复后原数据不清空。
- 这不是全量DDL语义审计：不宣称检查不可见的所有私有列、view定义、CHECK表达式、触发器或完整effective grants。现有Agent/product列/文档检查保留。

限定元数据权限
--------------

FC-M-META-1原架构评论01a21a94-4325-7331-af37-b91750d89b91有条件核准设计；不等于目标权限变更或P1关闭。只在原maas_release_reader追加对象级SHOW VIEW，四default roles不变：

| 九张表 | 三个view |
| --- | --- |
| release_revisions | release_history_directory |
| publish_intents | release_history_projection |
| resource_inventory | release_history_completeness |
| release_operations | |
| release_history_owners | |
| retained_release_snapshots | |
| release_history_retention | |
| release_history_legacy_audit | |
| release_management_operations | |

不加私有SELECT（包括LIMIT0）/REFERENCES/DML/DDL/GRANT OPTION或通配权限，不借History/Payload/Operations角色及DSN。SHOW VIEW可能暴露view定义/definer等结构信息，不能当零新增信息；运行校验不查询或向普通HTTP/日志导出定义。实际基础表探针只可见TABLES/STATISTICS，COLUMNS仍0，因此本项列序指key列序而非全部私有列。

旧安装未应用这12项元数据授权会准确拒绝，需原获准安装身份消费更新的同路径模板。已有不同/过宽直接数据授权不得因本设计被默认认为安全：现有migrate.sh拒绝额外/继承/default角色，但其注释明确direct object grants及role模板修改还需DBA审计。此既有安装边界已交主单/原运维协调，不冒称本只读形状补丁完成完整身份审计。

主单已明确新增安装有效权限预检由原MAAS-8在migrate.sh/一次性入口独立收口，MAAS-21评审组合；pre-provisioned及运行端边界由原架构裁定，若需运行审计另给独立切片。本形状修订不等待该未提交安装审计，也不把它算成已关闭。

实际验证
--------

MySQL8.0.44先仅验证单表SHOW VIEW：TABLES1/COLUMNS0/STATISTICS1，spec_bytes SELECT LIMIT0返回1142；不外推目标版本。

目标为本机已有镜像mysql:8.4.7，ID sha256:0426ec38c7a10aa45ba383887df7878f74ee70e2fd589c7b69207f3577901903。专属maas20-shape-8544-v847，无网络/host端口、skip-networking，确认最终PID1与认证socket后实际SELECT VERSION()=8.4.7/port0。没有借作者或QA实例、停他人容器、调用模型/GPU/付费/目标集群。

目标SQL定向批次**5个顶层、含子测试21项，通过、0失败/0skip，整体exit0**：

- 原3反例；伪同名非unique、前缀unique、错key列序、terminal nullable全部Open拒绝，现存owner /readyz503并退役；人工恢复对象后正常Open，marker不变。
- 原四角色真实装配并正常Open；SHOW VIEW恰12对象，撤私有对象元数据权后失败关闭；九表/三view SELECT与spec_bytes LIMIT0全部拒绝，marker UPDATE/DDL拒绝。移走私有表时同窄身份能检测且运行owner拒dispatch。
- 原必需journal状态矩阵和真实reconcile/历史/unknown-held不重放两项回归保留通过；不与原QA47项或旧879相加。

Go1.26，GOMAXPROCS1/-p1/GOMEMLIMIT256MiB；直接使用已批准任务模块缓存，GOPROXY=off，无新增依赖。Windows默认缓存编译曾长时间等待，WSL探针退出-1且未产生新产品输出；改用本任务无网络Docker，仅记录这些为环境/装配失败，不作产品断言成绩。错误的未加整体引号-test.*参数曾被PowerShell拆分，未执行断言；正确完整参数重跑exit0。

原始输出/被测二进制SHA/镜像与清理记录在test/controlled/maas20/shape-001。通过不等于独立签收：原QA仍需在主单最终同树复验本P1三例/边界；完整权限/旧宽直接GRANT、错数据域及其他未执行项保持未验，不把532或1f8旧成绩扩到新修订。
