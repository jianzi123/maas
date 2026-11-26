AA-CPU-01在CPU控制范围独立关闭。固定实现/证据`0cea087d21cac94d41f2f93443a48c3a7eaef00f`，标准四锁/head`82284e8fae1c8c11f437e2506aa125694b1f7f99`。本批为原39项矩阵中受影响反例/正控与新控制身份/接收时限的定向扩展，不重跑旧GPU/全面别名矩阵。**28个唯一受影响用例，Windows有效28/28、WSL28/28；另一个Windows→WSL管道实例不重复累计用例。** 作者21/22/37、旧QA39均不加到本轮数量。

## 独立关闭依据

合法lease driver已用10s、soft529s/hard589s，原job soft529/hard589在函数和真实worker --validate-only接受。仅将soft抬至550s时，函数和真实CLI均明确`soft budget reset`拒绝，CLI exit1；不是因旧source不符拒绝。全部plan使用当前17文件准确hash、execution_enabled=false，包含的plan_sha256、lease hash、REF身份均合法；当前source-pin单独负控明确`frozen sources`拒绝。

soft/hard分别cap+1ns拒绝，等号与较短期限正控通过；ns字段拒绝bool。REF/HOLD保留同一原600/540、driver10、原control/origin/binding，不能自算新origin摘要绕过继承parent tag。历史job1仅metadata_only=true，validate_job_time拒绝其作为live authority；job2真实validate-only核当前本地monotonic域/原parent tag/owner/window、过期和未来起点，非法路径在GPU导入前拒绝。private-cpu.lock仅本批私有夹具，未触研究锁。validate-only不验证实际GPU父子FD授权，不冒充真实执行已过。

## 原parent与真实CPU管道

实际source run_aa_window.py中唯一origin在ready、load/read/EOF之前。真实Windows和WSL管道覆盖实际LF+EOF、旧字面5c6e、空/截断、重复frame/额外LF/数据；有效首行只收紧期限，不能扩大CPU等待上限；迟到有效包拒绝，无EOF由生产receive_lease自己非零超时收口（本批不把外部kill当validator拒绝）。成功报告fresh和已有sentinel均保持，分析器独占写也不覆盖原报告。

Windows→WSL独立管道实测driver D=1867186400ns、接收R=468875026ns；发送侧实扣D和1s预留，接收方再扣R，原D完整回传，soft/hard剩余分别精确减R。D与R可重叠，保守双计不返还，未跨OS相减单调坐标，未与性能clock_scope相加。该实例复用PIPE预算断言，不另算第29个独立用例。原收据字节/PID/exit与时间字段在cpu-receipts.zip/cross。

## 原oracle和失败保全

history-d9ca内原verify.py/followup.py/matrix/results/report逐字节从d9ca7ff导出，verify.py哈希`ecbfc7cbcb90f619de4d2b8a33fbe9277c3391bc42f92a8ce2b436de51ae49bd`未改。原39唯一38过1失不覆盖。原followup那条“坏job应接受”的确认断言，在本轮retest-82284e8.py::soft_original改为函数与CLI非零且明确soft拒绝，并验证fresh/已有报告不变；oracle-change.diff单列语义改变，没有让旧确认断言成为关闭证明。原followup的HOLD缺bank和分析器不覆盖两项在同一28项中各执行一次；未复跑无关旧合成GPU/身份全部矩阵。

完整检出首次因历史NPZ长路径失败，0测试；仅命令局部core.longpaths=true重试成功。真正执行的17源码按Git对象逐字节复制到运行时获准短目录，source hash与Git822一致，executed-source.zip逐项回读通过。

Windows首轮27过1个QA夹具失败：自有CPU failure子进程启动超过100ms夹具期限，被收尾而未观察到预期exit7。保留win1原结果，不记产品回归失败。第二次增加readiness后因Windows CRLF而断言失败，未形成有效汇总/进程收集收据，不能登记通过；只命令日志和该尝试原文件保留。最终仅让**测试夹具**readiness兼容CRLF后单项重跑exit7并完成wait，1/1；产品lease实际LF断言未放宽。WSL同28项一次通过。两项监督器用自有纯CPU子进程/私有锁，记录正常失败exit7与超时forced kill并wait；实际GPU信号/子孙树收尾未验。worker CLI由subprocess.run同步收集，未逐个保留worker PID；管道/监督器/跨OS子进程PID、退出码和collect事实均有收据，不扩称所有失败尝试均取得完整收据。

## 复现与证据

解压本QA到短目录；executed-source.zip解压为S，逐项对provenance.json的17个source_sha256验证。使用独立输出目录和当前daemon PID：

```text
python retest-82284e8.py --source S --out NEW_WINDOWS_OUTPUT --protected-pid CURRENT_DAEMON_PID
wsl -d Ubuntu-22.04 --exec python3 /mnt/.../retest-82284e8.py --source /mnt/.../S --out /mnt/.../NEW_WSL_OUTPUT --protected-pid CURRENT_DAEMON_PID
```

该脚本不调用--execute或作者测试。cpu-receipts.zip保存win1/win2/win3/wsl1/cross及原stdout/stderr；commands/wsl1-command.json是实际WSL命令。cross_pipe.py保留本运行具体provenance/目录接点，移植时显式配置新的路径/保护PID，勿自动执行manifest里的命令。源文件/依赖完整hash见provenance；每份disabled-plan记录当前源码hash和本地时间，其created_UTC不同而plan hash不同是正常，未沿旧plan失败冒充soft拒绝。

|唯一受影响用例|Windows有效结果|WSL|
|---|---|---|
|AA-CPU-01-original-function-and-CLI|PASS|PASS|
|BUDGET-corresponding-caps-and-short-control|PASS|PASS|
|BUDGET-integer-only|PASS|PASS|
|JOB1-metadata-not-live-authority|PASS|PASS|
|BUDGET-HOLD-original-control-and-caps|PASS|PASS|
|BUDGET-HOLD-origin-reset-rejected|PASS|PASS|
|JOB-HOLD-missing-bank-reject|PASS|PASS|
|JOB2-live-local-positive|PASS|PASS|
|JOB2-original-parent-binding|PASS|PASS|
|JOB2-local-domain-not-performance-clock|PASS|PASS|
|JOB2-expired-rejected-before-work|PASS|PASS|
|JOB2-future-origin-rejected|PASS|PASS|
|JOB2-owner-and-window|PASS|PASS|
|PIPE-LF-EOF|PASS|PASS|
|PIPE-old-5c6e|PASS|PASS|
|PIPE-empty|PASS|PASS|
|PIPE-truncated|PASS|PASS|
|PIPE-extra-frame-LF-and-data|PASS|PASS|
|PIPE-ready-wait-charged-and-driver-kept|PASS|PASS|
|PIPE-no-EOF-self-bounded|PASS|PASS|
|PIPE-first-line-tightens-only|PASS|PASS|
|PIPE-late-valid-frame-rejected|PASS|PASS|
|PIPE-first-line-cannot-expand|PASS|PASS|
|PIPE-failure-preserves-success-report|PASS|PASS|
|SOURCE-current-disabled-plan-and-negative-pin|PASS|PASS|
|REPORT-analyzer-exclusive-no-overwrite|PASS|PASS|
|OWNED-CPU-failure-collected|PASS|PASS|
|OWNED-CPU-timeout-collected|PASS|PASS|

## 结论边界与状态

仅AA-CPU-01 CPU预算/控制路径关闭；MAAS-7/10保持in_progress。原128 missing/实际调用0、32配对差和比值null、A/A重复性未检验、旧34/64与Full严格0/18、未知收益不变；没有GPU资源查询、共享research锁、模型/权重、第二窗口或付费执行。GPU caller/同图/stream/scratch/池/padding/质量、跨OS性能校准和生产验收未签收。由Mika按独立结果决定具体下一阶段，不自动再派GPU。

本轮从统一4402建立QA增量分支，不合入PR9研究代码到产品，不改产品Go/前端/安装内容。上轮产品浏览器9过1失与QA-CHAT-RACE-001开放范围、879/R01/R02及d27 MANIFEST关闭范围原样保留；A34整体仍NOT_ACCEPTED。

自有短目录a27、源码临时副本、输出和private-cpu.lock文件已在逐项归档回读后清理；cleanup.json保留核对。未停止他人进程/服务，未改共享research锁或模型缓存。
