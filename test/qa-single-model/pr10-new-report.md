PR #10新增5481ac0本次独立局部QA通过。固定产品代码23571a983304d5465021ec00813cc15fb3463ccc、四锁head5481ac0fddbf02cb5e22e3145d5a3dc69c76acd9、base8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a。不盲跟移动head、不修改候选、不签远程合入。

执行前核MAAS-7最新描述、线程扫描/06:38后增量及active runs：仅本唤醒运行01a1e340-6304-7d5d-868d-26f526f64869，无同5481独立结果/活动重复批次。旧工作树7089ceb和既有qa-single-model分支b287abe干净并保全；本次只在后者test/qa-single-model追加，未中止/覆盖#14/TLS或其他任务。一次性唤醒fire_count1、enabled=false，不需再disable；网络多次读取失败均先重试，最终必需上下文读到。

认证MAAS-17报告附件01a1e32d-8535-761c-a31d-b75f5ceef380已取得，报告只作输入。原证据ZIP01a1e32d-8b2c-79cb-a4eb-f6200f404b8f本次认证下载报Could not reach server，未谎称核其原件；本次结果由精确Git源码重新独立运行，不依赖该包成绩/命令。没有执行manifest中的外部命令。

Node22.23.4/Vitest5.1.0/jsdom，候选console锁文件与原U2缓存相同，隔离导出固定源码后复用原依赖。
- 新增四配置/六交互10/10通过，0fail/skip。原配置缺省/0关闭、1启用开发Vite define、非法值拒绝；仅dev serve采用插件。
- 六交互（known/unknown/eof/error/stop与不可用禁POST）独立增补凭证、R/Q、方法/路径断言后6/6通过。它们是原六场景的受影响重跑，不与10相加成16。
- 必要新增缺可信R一格通过，其他6例被-t过滤未执行不是6个额外通过。总唯一场景为新10＋缺R1=11；不得与旧U2十项加成21或与审查20相加。

原始JSON和verbose日志分列，未删失败。首轮QA仪表脚本未显式UTF-8导致读取源码UnicodeDecodeError；只修QA读取编码，第一次未加仪表的10项原样通过记录保留，随后只复跑受影响六项，再只运行新增缺R。未改变产品断言以适配实现。

POST/GET与原R轨迹：known/unknown/eof/error/stop均先GET模型→同源/v1/chat/completions恰1次POST→/api/admin/v1/usage/requests?request_id=R恰1次GET。R为00000000-0000-4000-8000-000000000001，独立查询响应头Q为00000000-0000-4000-8000-000000000099，lookup仍原R、不替换。停止后state stopped，EOF/error interrupted；known投影Token19，其他actual null，原budget_accounting逐字结构保持，不由客户端结算。无R格仅一次POST且无lookup/无文本展示，结果明确未知，不扫描列表或重发。

生成端credentials=omit、Cookie/CSRF头为空、Authorization仅合成平台Key，body固定model-a，路径只有同源/v1；未加入供应商URL/凭证或跨来源fallback。此为fetcher/Response断言，不证明浏览器TCP/mTLS或服务端秘密未泄漏。不可用时即使目录callable样例为true也不POST。

App/Vite静态边界：localControl插件apply=serve，Vite config仅command=serve采用；App要求DEV且flag=true才能在local模式开放发送，编译workbench仍关闭；internal/workbench/http.go的inference_available=false且/v1仍返回503。开发flag只表安装方显式声明端点，不能证明Callable/批准/Key预算/网关/结算；当前管理专用workbench不得设置1当真链路。

来源核验：复用scripts/unified_sources.snapshot/verify，候选backend514/514、console78/78完全一致；锁码23571a9是5481祖先且两者仅四元数据差异。四锁与8份关键文件SHA在pr10-source-results.json。候选导出产品缓存仅复制测试并加QA仪表，真实产品树无修改。来源hash/命令与实际QA提交分别记录。

本轮未重跑U2（b287abe对aa9720f的10/10保持）、UI16/Delete（1e4a1af）、R1–R3、TLS #14或GPU/DB/真实模型。不把Response/jsdom合成known19/unknown当权威真实上游/SQL结果，也未运行作者5组浏览器/旧20项。迟到A/B与合法独立final沿旧已签范围，本轮仅新增路径/缺R与原ID回查，不扩张为全部竞态签收。

测试全部前台退出，未启动Vite/浏览器/DB/模型服务。旧#14服务/任务没有操作。原型回放不开放真实Secret、供应商付费、目标部署或GPU执行；A01–A34及单模型真实11格仍NOT_ACCEPTED，MAAS-7保持in_progress。

复现：固定5481ac0导出console，用候选package-lock依赖，运行Node node_modules/vitest/vitest.mjs run src/single-model-mode.test.ts src/single-model-replay.test.ts --pool=threads --maxWorkers=1。原两个文件以.in归档；附加仪表版另列，缺R用-t 'QA missing trusted R'单独运行。输出选择新路径，四锁用现有verify工具核。

下一步：Mika/MAAS-17据本局部QA与#13实际修复head/base合并审查，保持Merge commit及来源锁流程；本次不批准remote merge、production Callable或真实端到端。#14 TLS与真实factory入口另段验收，待同一批准profile/来源/Secret/额度/价表和实际接线SHA后再用现有单模型矩阵取证。
