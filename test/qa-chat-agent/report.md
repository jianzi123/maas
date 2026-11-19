Chat/Agent Runtime 独立QA准备交付。本轮基线8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a，沿qa/maas-7-single-model-u2继续，旧工作树/分支/失败记录全部保留。实际产品候选SHA与契约版本均未取得，不能宣布应用/运行时验收通过。MAAS-20读取时为todo、无交付评论，统一分支未发现新会话/Agent实现；MAAS-2本批契约交接线程01a1f1d7-f8fa-7164-a636-1928b816850e无回复。本轮未依据任务创建事实伪称功能已存在。

已检查active runs：仅本运行01a1f1d8-2fc1-757e-b4a0-c4f09378e11b，没有同批重复QA；未触发新实现/其他角色运行。读最新MAAS-7、核心任务MAAS-20及当前项目输入，首期共用Session/Run/事件、替换组件、安全真实工具和每子模型唯一结算的要求作为依据。没有获取DeepSeek官方页面或对其内部架构做新事实断言，锁版ADR与复用取舍归原架构/后端。

本轮实际运行：
- 17个unittest正反控制全部通过：合成合法trace、相同事件重复只读、同ID异内容、跨会话事件、未授权/畸形工具、未批准、错批准owner/args、重复工具执行、未知结果恢复重放、重连触发模型执行、子请求重复结算、父账本重复扣量、未知补0、缺限值和编辑缺关联。
- 4个CLI损坏输入（未知副作用重放、错误批准owner、重复结算、缺身份）均exit2且无成功新产物。cli-rejections.json保留实际stdout/exit/产物不存在检查。没有覆盖旧报告。
- GET探针read-plan.template.json因contract_approved=false及无SHA实际exit2，未创建输出、未发网络请求。Python标准库探针仅接受loopback和人工提供的已审路径，拒绝redirect，不存会话原值/正文，不做写入/生成/工具执行；仅检查状态码不能验证消息/执行语义。

以上为QA工具单元/CLI验证，不是17个或4个产品能力通过；18项新能力运行均NOT_EXECUTED，真实链路/生产均未验。代码未实现替代AgentLoop、会话账本或工具服务，也不使用内存fake-store结果冒充真实持久化。synthetic-valid.json仅用于测试oracle，所有标识/预算为合成测试值。raw_evidence_verified字段是独立审核前置标记，不能靠输入自称true就获得产品验收；正式签收还须验证源文件hash、数据库/HTTP原件及映射关系。

矩阵matrix.json/matrix.md编号CHAT-01..06、AGENT-01..12，独立于旧A01–A34：
多轮持久化/刷新/用户隔离、流式停止/事件重连、编辑/重新生成关联和Markdown/秘密边界；真实工具执行/结果回填/最终答复、Schema/权限、批准拒绝/重复/参数变化、工具超时/输出上限、步数时长预算和无进展、崩溃/Checkpoint、未知副作用、重复事件/迟到fence、子R唯一结算、版本化tool_calls、工具输出注入隔离。每项列可观察断言，不自创公开路径/状态或暗改文本v3/终态3.0/Observation1.0。

verify_trace.py只接收QA归一化证据格式（不是拟定产品Schema）。后端交付后由独立适配从实际事件/SQL转换，固定product SHA、contract版本、环境、owner/session/run及各子request，保留原始证据引用。核事件ID内容稳定/顺序、工具授权/参数Schema与call身份、owner/args绑定批准、未知副作用不重放、每子R request/终态/summary各一次、父run不重复扣业务账本、未知actual null/held、重连不执行、编辑原消息关联。形状/断言满足不证明数据真源，不能把accepted当生产通过。

probe_reads.py是后续只读接口入口，需要MAAS-2/20批准的具体GET路由/预期状态和固定SHA，由安全渠道注入MAAS_QA_SESSION_COOKIE。不同用户使用独立临时session分别验证列表/会话/run/events可见性，未审计划/相对路径错误立即拒绝；创建/提交/批准/取消/编辑等写动作仍由明确获准的隔离集成harness执行，不能由本只读probe自动推断。当前没有填猜测的API URL，没有向工作台探测性写入。

可复现命令（仓库根目录）：
python -m unittest discover -s test/qa-chat-agent -p test_trace.py -v
python test/qa-chat-agent/verify_trace.py test/qa-chat-agent/unknown_replay.json --output <全新输出路径>
python test/qa-chat-agent/probe_reads.py test/qa-chat-agent/read-plan.template.json --output <全新输出路径>
后两条当前预期exit2拒绝；不把拒绝当产品服务错误。

后续接点与责任：
1. MAAS-2/20交最小Session/Run/Message/Step/ToolCall/Event/Checkpoint及cursor/API/工具能力版本、并发/编辑策略、取消/恢复及批准幂等/未知结果规范，附准确SHA/迁移/角色与运行入口。QA只按实际字段映射，不要求后端适配本归一化字段命名。
2. 原后端交受控模型选工具→执行真实纯计算/本用户只读工具→回填→答复的完整轨迹，标明哪个ModelClient是替身；副作用负控工具只能在显式隔离harness注入，不默认执行shell/MCP/外部写入。
3. 在独立临时MySQL/进程/HTTP环境验证持久历史与崩溃恢复、重复/冲突批准、超时/限额、取消晚到结果、用户A/B权限和每子模型原账本。独立进程退出不等于DB HA；输出read事件不等于工具已真实执行。
4. MAAS-5交同一契约/SHA的Chat页面与浏览器入口，再按6个Chat能力取证，包括刷新、重连、编辑/重新生成和agent步骤/等待批准。页面按钮或受控流不当真实模型验收。
5. 真实Higress/profile/tool_calls批准/价表/Secret/额度/目标环境沿已有门槛，MAAS-18底层单模型闭环不因新增应用准备被关闭；工具次数与父run视图不构建第二份预算真源。

旧U2/5481新10＋缺R1、UI16/Delete、R1–R3、Usage20/Reader12、QA-001/002/003、TLS/性能等已有记录保持各原SHA与范围，不重开或重跑。本轮未启动GPU、浏览器、Vite、DB、真实工具产品进程或调用供应商/目标集群；无后台工作，工具命令已前台收齐。MAAS-7保持in_progress，Chat/Agent和A01–A34整体未验收，下一轮在新契约/实现SHA上按影响范围定向运行并一次性交Mika归并。
