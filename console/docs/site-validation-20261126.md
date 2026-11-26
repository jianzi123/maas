# 2026-11-26 同源站点作者验证说明

基线4402c456（树等d27），自有Compose maas5-site-1126，localhost:18765，正常maas-service/MySQL8.4.7/Nginx。使用已记录64b镜像缓存，生产Go/console/运行配方输入与d27逐字节相同；本轮原生maas/probe二进制SHA也与镜像一致（673b96f153c04bd446cda8429a371cbddfafff64989863fa2e2e93076b15482b、d9c3e48473bdfbf68a2180da10dee4bbd7692fd59af353da47cf7f18a6f54fe1）。新前端dist以只读目录挂载验证，不冒称新镜像标签或重新完整构建两包。

完整原生脚本执行到npm ci发生ECONNRESET/cleanup EPERM，保留失败；Go二进制已成功，本任务目录锁依赖恢复/前端构建成功，缓存路径替代有效。没有因网络失败把静态parse当站点通过。

证据在console/artifacts/site-1126（不入Git，随原任务附件交付）：

- 原deployed-site首先真实失败；真实首次GET会话401的延迟输入复现确认密码被清空且登录POST0。修复后输入禁用至检查完成，同样响应延迟下登录POST1并进入Chat。
- R-P01真实页面选择可调用离线模型、用明确无效合成Key发送得到405/Allow GET,HEAD，无原X-Request-ID，generation_requests/usage_events增量0。修复后默认不呈现Key/发送表单、不请求旧目录或/v1，Chat引导可达；不会误称供应商失败。
- 普通Chat中文/emoji完成前输出观察、Agent两真实工具/参数/必要批准/结果/实际attempt、原child用量已作者验证。首次批准差异样本曾需一次重连，原失败保留，补抓正常不关项；最终候选增加读取代次隔离与有界修复等待，交原QA定向复验。
- QA-CHAT-RACE-001原包认证SHA a49ef912acba81f14462ab53a4798a2ba2376301c33df549549cd321effd6a87。新增取消/批准×旧stream晚到/旧page晚到四例，及idle Abort正例、当前畸形关联负例；旧轮询不再重新发快照夺取前台读取代次。真实畸形仍拒绝，非把所有取消错吞掉。
- 原拒绝操作通过原command/approval查回failed/approval_denied、attempt0；未再次生成或决定。先前只读脚本hash导航未真正重载的等待失败也保留；验证器现明确刷新文档后核原记录，未篡改业务状态。
- 停止先看原child in_progress，再真实点击，ACK202后权威cancelled；最终UI不再保留等待终止提示。断开事件仅GET观察，原child继续，显式重连和刷新不重放。
- Go/MySQL顺序重启的同一浏览器principal/Cookie/CSRF、原消息/事件/工具/child及用量哈希保持，SQL请求/usage计数不增；计数observer只在本任务独立库SELECT，不替代运行身份权限矩阵。
- 实际两工具小分页＋一次正常标题PATCH产生真实ToolCallPage410，整批GET重取、两工具各一次、原事件cursor保持、生成POST增量0。该受控故障输入与旧独立QA102消息场景分开，不重跑/累计旧矩阵。
- 正常production空models负例：MySQL登录正常、能力空、生成禁用、无demo回退或模型POST；随后原样恢复受控配置。

原217/11skip、原静态HTTP夹具、旧独立QA4402九项通过与本次作者结果范围各自保留。各脚本的check条目存在重叠，不能相加成场景/全仓测试数；最终报告列准确代码/四锁头、dist哈希和命令。真实供应商、生产Higress、正式tools新Go头、新FC-1/锁取消、管理目标/完整Operator和目标K8s均未由本前端本轮验证。不得将作者候选自行登记为独立关闭。

退出前停止自有Compose容器/网络，保留专属卷和受保护配置供原ID复验；不停止他人服务或Docker Desktop、不删除历史/unknown-held、不远端合并PR。
