QA-CHAT-RACE-001在固定393的**正常Go/MySQL、明确offline-controlled、真实Chrome及受控GET迟到**范围独立关闭。本轮9个唯一页面运行用例9通过/0失败，另4个只读契约检查通过；不累计作者64项、旧浏览器9/10、SQL50或CPU28。**QA-MIG-SHAPE-001/P1继续开放，本轮未执行其3反例或权限新方案。** MAAS-7/21保持in_progress。

## 固定版本与执行层次

产品代码c99e5dfccfabec17b6a582892cd155a37a49b0a4→标准四锁393edc9c25a2bea55969af87d29158b2f0d74f94；前端组件eec33eb42d48d78c2dce832c21e188f24403b134（PR25），console树与393字节相同。认证bundle362664字节/SHA256 fe98c0a5cfa83f695b11708baf3cb383ae7a6c3bd650f2a70435c82f0c08beed及3前置对象verify通过，固定源码在自己的短目录检出，未取远端旧6285代替。目标标准库存664/664、114/114匹配，跟踪源码干净；本轮未改产品。

Go1.26.0/linux-amd64/CGO0，GOMAXPROCS1、-p1、GOMEMLIMIT256MiB顺序构建；Node22.23.4、同package-lock的自有依赖、静态typecheck/Vite build通过。Chrome158.0.8127.38/Playwright-core1.64.1是真实headless浏览器，非jsdom/Response合成站点。没有可用node_repl桌面入口，沿项目现有Playwright测试方式，没有操控用户桌面/个人浏览器。自有MySQL8.0.44、project maas7-ui393-76e89ce8/端口57359，原migrate.sh与四角色，服务是正常maas-service。

数据源分开：页面4Run/6child使用normal Go/MySQL的明确offline-controlled、5000ms、requireApproval配置，两个工具是实际安全Go实现；模型与网关/发布/速率见证仍为受控fixture。正式tools桥的34HTTP/42事件是固定393内保留的作者受控producer样本，本轮独立读取Schema/身份检查，不是假称重新生成正式模型链路。真实供应商/Higress/付费/GPU/目标K8s0。

## 四迟到顺序与原ID

停止：74291e98-9b96-4209-ad8f-49a8cbc3e30e（old-before-new）、29df8249-b6b1-4d9a-9c1f-0d505a00dcad（old-after-new）。均先独立GET原child账本实际in_progress，再点击一次停止，原Run cancelled。

批准：235f8acd-43e9-4a30-b8ba-e1f4ca8d49d6（old-before-new）、4478c63b-b7e0-4fb9-9da0-afac681bf3e4（old-after-new）。均冻结原审批GET，点击原批准API一次，等待同原Run完成再放行新终态快照，实际2child、两工具各1条且attempt1/succeeded。

方法不是伪造终态：截住old poll尾部的真实GET，先route.fetch取得合法Go200/ETag/原JSON，再仅延迟发送。停止尾部为ToolCallPage，批准尾部为原Approval。新的前台快照GET已开始，按两种顺序分别释放旧GET与新快照；新快照取的是原Run真实cancelled/completed状态。raw/arrival-order-proof.json从实际response事件重核：停止old-before旧0/新1，old-after旧2/新0；批准old-before旧0/新2，old-after旧3/新0。原GET字节/hash保留。

每例捕获AbortError：快照读取已由新操作替代。两层传播只代表同一逻辑淘汰，不算额外用例。终态无假AR-1告警、无旧running/waiting_approval，发送按钮可空闲使用；停止不再残留“等待实际终止”徽标。截图已视觉核对，正常execution_stopped原因不被误当协议错误。idle SSE后能发起GET；不把合法idle超时当错误。两个真正的坏关联负控分别把当前Snapshot Run.session_id或ToolCall.run_id换成别的合法GUID，当前消费者仍显示协议异常、0业务POST，证明未通过吞掉所有错误来修复。

每个父Run只一次send及一次cancel/decision POST。共6个不同原child；正常重复GET/刷新后Run、Steps、Tools、Events及消费业务字段哈希一致，每child精确一条。仅剔除原消费响应generated_at及lookup/capacity.checked_at三观察时间字段，业务数据不删。全库generation_requests/usage_events/finalized从0到1/2/4/6，最后6/6/6；只读恢复未加数。当前live受控用量每child known10，Agent父known20，held0；不是供应商账单，也没有新增unknown用量场景。

## R-P01、bootstrap及契约

公开配置playground缺省和显式false两种情况下，旧在线试用均不显示消费Key表单，无/v1请求，按钮引导现有Chat。bootstrap用实际Go未登录GET401，测试只延迟其到达：期间账号/密码/提交均禁用，无登录POST；401完成后再输入一次，正确登录POST仅1，未发生晚到响应清空已允许输入的竞态。正常成功登录清空密码属于既有策略。此结论只签页面门禁/引导，公共消费Key API及真实/v1可调用仍未验，不能由引导销项。

固定保留样本complete23HTTP/33事件/2原child、invalid_second_tool11HTTP/9事件/1原child，均按官方AR-1 OpenAPI/SessionEvent重验证，原child互不重复且每查询精确一行。共34HTTP、42事件。两官方Schema与4402逐字节相同；给已通过的HTTP/事件各添加一个未批准字段仍拒绝，严格消费者未放宽。oneOf外层拒绝与内层additionalProperties错误区别在QA修正记录中分列。没有据此独立签收正式H4/供应商/模型能力桥或质量/性能。

## 原失败及接续

所有失败保留，不用局部通过抵销非零exit：认证下载先两次网络/响应中断，HTTP/1 CLI成功且TLS校验保留；依赖复制9个Windows长路径失败在构建前，改本命令长路径前缀后同锁复制通过，不改全局设置。文件写入单元无返回时已取消，后用明确升级的UTF8文件写入建立自有脚本；未重复provision。MySQL初始临时server让ping过早，通过最终数据库就绪SQL后仅重跑未完成安装，非产品模型失败。

浏览器attempt1只因忙态按钮不再叫“登录”的QA定位失败，0生成POST；修正为表单按钮。attempt2停止两例通过；批准old-before的Run已completed，但三个completed徽标令QA严格定位失败。保留原截图/DOM/GET顺序/Abort，未重复生成或批准；只用同原RID读回并核原现场无协议告警、终态收敛，再完成只读刷新/哈希/唯一工具检查，随后只执行余下old-after。最终复现入口browser-reproduce.mjs合入两个定位修正，as-executed保留每版原脚本。trace首轮真实负控已经拒绝，但QA错误要求外层keyword必为additionalProperties；按oneOf错误树确认未知字段拒绝，复用原34/42通过日志，原错误亦保留。

## 命令与复现

provenance.json、原build stdout/stderr、每例network/records/ledger和raw目录含准确版本/请求ID。编译：npm --prefix S/console run build；GOMAXPROCS=1 GOFLAGS='-p=1 -buildvcs=false' GOMEMLIMIT=256MiB CGO_ENABLED=0 GOOS=linux go build ./cmd/maas-service。全部从固定393源码，而非作者目录；依赖树package-lock与本QA旧缓存相同。以全新自有目录/端口/卷生成配置，复制公开console-config到dist，原migrate.sh→正常serve。Windows Secret需Linux mode600卷；等待最终MySQL数据库实际可查后迁移，不以临时server ping代替。

执行全新站点入口：MAAS_QA_ROOT=<自有测试目录> node browser-reproduce.mjs。先提供site.json（source指自己的固定源码，origin/base/socket/project均指自己的站点）、private测试bootstrap文件和同source的Playwright依赖。as-executed/prepare_site2.py是本轮实际装配源码，历史compose/site只用于复现参数，不可直接重用已清理的实例或他人资源。该入口有初始ledger=0保护，必须全新DB；历史browser-resume.mjs仅说明本轮如何安全接续原已写入RID，不在新站点盲跑。

Schema入口为固定源码的test/controlled/maas20/fc1-tools/validate-traces.py，在固定源码root运行；本QA的trace_checks脚本另加额外字段/原child检查。manifest中的命令不作可执行外部输入；需要看脚本和本报告后显式运行。

|唯一运行页面用例|结果|
|---|---|
|BOOTSTRAP-late-real401-input-gate|PASS|
|RP01-missing|PASS|
|RP01-false|PASS|
|RACE-cancel-old-before-new|PASS|
|RACE-cancel-old-after-new|PASS|
|RACE-approve-old-before-new|PASS|
|RACE-approve-old-after-new|PASS|
|MALFORMED-foreign-session|PASS|
|MALFORMED-foreign-tool-run|PASS|

## 清理与剩余

本轮自有project、data/socket/两Secret四卷及宿主private全部清理，cleanup-after为空；所有Chrome context/browser关闭，未停他人服务、不清共享缓存。公开源码/构建缓存与证据保留，未留后台站点。截图/日志扫描未发现本次密码/pepper/cursor原值。

QA-MIG-SHAPE-001/P1仍开放且未纳393，本轮不重跑3原反例/新SHOW VIEW。主单最新有效权限审计边界（额外direct grants、预提供角色、外部DB）亦未由本轮页面测试签收。后续准确Go/SQL组合按实际差异保留本页面范围，需要影响AR响应时再做针对性回归。旧879/R01/R02/d27 MANIFEST、PR23 AA-CPU-01 CPU关闭保留，原4402失败记录不改写。完整A01–A34、真实消费Key/Higress/供应商、生产/集群/HA仍未验；MAAS-7/21保持in_progress，不自动合并。
