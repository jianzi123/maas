
# 控制台 UI16 改版交付

本次将 v1.6 设计落入实际 Vue 页面，复用原接口、原请求身份与预算协议。统一基线为 agent/MAAS-10-offline-metrics，旧个人分支及已验协议成果保留。

## 用户可见变化

| 清单 | 实现 |
| --- | --- |
| UI16-01 | 白色分组侧栏、紧凑顶栏、环境条、统一工具栏和内容密度；移动导航可访问五页 |
| UI16-02 | 当前模型集合搜索/来源筛选、能力摘要、模型详情侧抽屉、目录到试用/发布 |
| UI16-03 | 调用设置、对话画布、输入区和原请求结果分层；中文传输状态、停止/回查保护 |
| UI16-04 | 发布表/详情分层；进度、当前活动和阻塞解释；完整条件/UID/RV折叠 |
| UI16-05 | 基本信息、来源、批准引用、生命周期、确认五步；完整外部/私有 Schema 双向 JSON |
| UI16-06 | 请求表/侧抽屉、明细/汇总页签、紧凑筛选/高级查询、精确原 ID 回查、观察/分页范围 |
| UI16-07 | 保留已有 Key 创建、预算、撤销与一次显示；统一样式，非秘密 ID 可检索/联动 |
| UI16-08 | 保留服务端错误码，增加403/409/503的可行动提示；unknown 仅查原操作 |
| UI16-09 | 原生模态焦点/Esc/返回焦点、可见焦点、文字状态、390/768/1440布局检查 |

UI16-10 未增加趋势或性能指标，接口尚未提供相应可信时序样本。

## 完整表单与恢复

来源类型在创建模板时选择。全部现有字段进入结构化表单：ExternalAPI 的供应商、端点、上游模型、协议、Secret 引用；SelfHosted 的权重、镜像、runtime/placement profile、完整组/GPU/并行/CPU/内存和启动配置；共用网关、三项业务引用、生命周期全部字段。空引用及模板0不产生获准默认值。两种输入共用严格 ReleaseReleaseInput 校验，结构化编辑与高级JSON互相同步；服务端继续核验引用权限和实际就绪。

更新绑定当前UID/RV，保存动作仍按期望状态变化识别Pause/Resume/Update。回滚/删除的空resource及202沿原operation恢复。原Delete操作确认Succeeded后，清除失效的编辑基线、保留原操作ID并恢复创建入口，不要求重读已经删除的CR，不重发DELETE。其他结果/归属冲突继续保守锁定。

请求和预算保留精确十进制字符串；未知actual与held分开。页面不从EOF、停止、slot释放或最后一个usage片推导成功/退款。会话、消费Key与上游Secret分离；Key不进入浏览器存储。

## 复现

在console目录执行：

```powershell
npm ci
npm test -- --pool=threads --maxWorkers=1
npm run build
node scripts/redesign-browser.mjs
```

最后一条启动并关闭临时Vite/Edge，以显式开发夹具验证非空请求、未知用量、流式停止及原请求回查。不是供应商运行证明。

真实管理路径运行 `node scripts/redesign-browser.mjs --real`，复用根目录 startWorkbench：Windows通过WSL临时MySQL/API-server和实际Go控制台，结束时stop并清理。可通过已有 MAAS_WORKBENCH_TOOL_CACHE 读批准便携工具，MAAS_WORKBENCH_GO_CACHE 指向本任务私有缓存。缺推理适配时发送保持禁用。

结果输出在console/artifacts/redesign/{fixture,go}；results.json记录实际候选完整SHA、环境、路径、HTTP方法/状态和失败。每个环境五页各含1440×900与390×844截图，768px做无整页溢出检查。

三路径按同一候选验证：

1. 目录搜索/详情→在线试用→原请求：真实Go展示未开放原因；合成流覆盖一次POST、停止、原ID回查、未知费用。
2. Key创建→关闭原值→预算改0→按Key进入用量：使用实际Go/MySQL管理接口；保留服务端真实空态。
3. 完整发布配置→202→阻塞原因→原操作/保留修订→暂停→删除→原操作确认：实际Go/MySQL/API-server；不将受理当Callable。

## 验证限制

新增组件用例验证完整字段/JSON同步、私有输入阻断、请求未知详情、Delete终态恢复与查询失败；现有协议及回查竞争断言保留。旧测试中卡片article定位改为请求表行，首按钮改为明确刷新操作；独立QA原断言不改写。

本地管理和夹具成绩分别交付；真实供应商/生产登录/Higress/Secret/validation、非空真实用量、SelfHosted推理和A01–A34整体验收仍需原任务独立证据。历史通过范围不因改版扩张。UI16新候选由MAAS-7定向验收。
