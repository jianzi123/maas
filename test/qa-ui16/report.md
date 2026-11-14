# MAAS-7：UI16 与 Delete P2 独立定向验收

日期：2026-11-14 UTC。被测前后端同一候选 **b73d96be97e3666d3470106d5b6d13fd91c5c9f7**，PR #10，统一基线祖先8dbf99ef59c847da775b83d0eeb7dc8f8bf48a9a；产品代码来源锁f182ee2380424f70fc004657c0d9ed4a165c4132。独立验收分支qa/maas-7-ui16从统一基线建立，未修改产品实现。

**结论：UI16-01至09在下述受控页面范围通过；Delete恢复P2在本次真实临时管理与合成负控范围关闭。** 这证明实际Vue页面和操作已改变；UI16-10仍待可信数据，真实模型和A01–A34完整验收不在本轮通过范围。

## 实际执行与计数

| 证据 | 本轮结果 | 范围 |
|---|---|---|
| 前台Edge实际Go/MySQL/API-server管理浏览器 | 24项通过，pageerror=0，退出0 | 实际临时管理接口，真实空用量，未接推理 |
| 前台Edge显式开发夹具浏览器 | 24项通过，pageerror=0，退出0 | 合成流式/请求/非空及未知用量，不能作真实模型证据 |
| 新增独立Response/jsdom组件用例 | 18个唯一用例通过，0失败 | 首15项一次；新增3项定向运行，原15项因名称过滤未重复，不计新的通过/条件跳过 |
| 新增独立Edge焦点/窄屏操作 | 4项通过，15个五页×三宽度量测样本，pageerror=0 | 标题位置、抽屉、Esc、返回焦点、背景不可聚焦、完整私有字段 |
| 候选来源锁独立比对 | backend514/514、console72/72 | 全部hash匹配，未外推生产装配 |

不把这些不同分母相加为场景总数，不引入作者146项、作者两组24项或原型38项作为本轮独立通过计数。未因页面改版重跑后端全套、GPU或历史协议套件。

Windows；Node22.23.4、Edge157.0.4341.46、Vitest5.1.0、jsdom30.1.3、Vite8.3.6、Vue3.5.45；Ubuntu-22.04临时管理，Go1.26.0/MySQL8.4.7/envtest1.36.0。原依赖junction目标失效，首次启动缺vite未执行用例；移除的仅是本任务失效链接，按固定package-lock在本任务npm ci。便携工具从既有批准缓存只读复用，Go mod/build缓存属本任务私有，无全局工具或目标集群变更。

## UI16逐项结果

| 清单 | 判定与本轮证据 | 限制 |
|---|---|---|
| 01 应用壳 | 通过；同SHA五页1440×900及390×844实际截图，768检查；导航/主操作/内容分层可操作 | 移动页允许正常纵向滚动；没有访谈/效率百分比结论 |
| 02 模型目录 | 通过；当前集合搜索/清除、详情/Esc、试用上下文；真实目录未开放及发送禁用 | 未把目录健康、活动绑定或配置受理当Callable |
| 03 在线试用 | 通过；夹具流式→停止→精确原R回查只发一次生成POST；真实Go生成POST=0；独立A/B迟到回查保持B | 停止、真实计算退出、slot与账务分别解释；不是供应商调用验收 |
| 04 发布进度 | 通过；实际202/阻塞/原operation/历史；独立新generation99不继承旧目标成功，活动Callable单列 | 不把受理当生效；生产网关/validation缺口保留 |
| 05 完整表单 | 通过；ExternalAPI与privateCR合法样本全部叶字段覆盖，结构化/高级JSON双向一致；缺引用、来源混合和坏JSON均禁提交、无写请求 | 结构合法不代表引用批准；SelfHosted未执行GPU部署 |
| 06 请求用量 | 通过；真实空态、夹具请求详情/未知；独立分页保持已应用过滤、data_complete不完整；USD/EUR和超安全整数原子金额/held字符串分别保留 | 非空与多币种仅合成；未新增趋势/性能指标 |
| 07 Key | 通过本次受影响路径；实际201创建、关闭一次原值、PATCH预算0、非秘密Key ID联动用量；浏览器存储为空 | 复制/撤销等未改业务沿历史原SHA证据，不虚称本轮重跑全部Key用例 |
| 08 空/错/未知 | 通过；独立403/409/503保持错误，不伪造成功空结果；Unknown/Failed/错归属/查询503不恢复写入口 | 这些错误注入为组件合成Response，未外推全部真实依赖故障 |
| 09 可访问/响应式 | 通过当前Edge范围；两模式五页三宽度不整页溢出；独立15个标题rect量测，390抽屉/私有表单可操作，Esc返回原开启按钮，背景不可聚焦 | 未进行屏幕阅读器/全浏览器兼容认证 |
| 10 趋势等 | 未执行，等待数据 | 本轮没有造时序、假性能曲线或新增产品指标 |

## Delete P2 关闭证据

实际Go管理路径：DELETE /api/admin/v1/model-releases/maas-local/local-example返回202，原operation **b3a3be90-8f46-43df-8dba-6e9cc8208f67**确认Succeeded；页面显示“原删除操作已确认完成”、新建外部CR入口恢复、原operation ID保留；实际DELETE恰好1次。临时K8s/API-server、MySQL与业务Go均参与，真实网关/模型未参与。

独立合成恢复矩阵六项全部通过：
- Succeeded：解除失效编辑基线、恢复创建、保留原ID，不重读已删除CR，不重发DELETE。
- Unknown/Failed：不能当成功恢复；Failed仍按原规则要求确认/重读，不用旧CR做新写。
- wrong-uid/wrong-action：即使回执Schema合法且Succeeded，也因归属不符不解除门禁。
- lookup-503：查询失败不造成功，不发写请求；六项各自原DELETE仅一次，后续只精确查询原operation。

原QA-001/002/003、created/错误R、后台/性能其他关闭范围保留其原SHA。不得把这次Delete/UI16通过改成全部A01–A34通过。

## 首轮失败、诊断与修正

1. 原作者redesign-browser.mjs的fixture首轮在生成计数断言处0≠1，页面已显示流式文本。观察包装安装于page.goto后，可能被App.boot异步fixture装配覆盖。独立QA复制入口仅将观察安装放到模型集合实际就绪后，保持原24项断言，另加强返回焦点断言，产品源码不改；随后24通过，generationPosts=1。原失败JSON/截图保留。
2. 独立焦点首轮要求每次Tab的activeElement都在dialog内，失败。诊断轨迹显示两次activeElement=BODY时document.hasFocus=false、dialog仍为:modal；主动尝试聚焦背景导航也不能取得背景焦点。QA修正为“对话内可交互焦点或失去文档焦点的浏览器边界，背景不得可聚焦”，未接受任何背景按钮焦点。修正前JSON/截图和逐次轨迹均保留；最终4操作通过。
3. 证据汇总首次受Windows默认GBK解码影响，改为显式UTF-8，不涉及产品或重跑。

上述失败是测试环境/观察判定记录，不删除，也不计作修复产品代码的证据。未发现新增阻断产品问题。

## 复现与证据位置

在console目录：
- node ../test/qa-ui16/browser.mjs：独立fixture入口，保留24项及新增返回焦点检查。
- 设置MAAS_WORKBENCH_TOOL_CACHE为批准便携工具目录、MAAS_WORKBENCH_GO_CACHE为本任务私有目录，node scripts/redesign-browser.mjs --real：实际管理路径。
- node ../test/qa-ui16/edge-focus.mjs：独立窄屏/焦点观察。
- 将test/qa-ui16/independent.test.ts.in临时复制到console/src/qa-ui16-independent.test.ts，运行node node_modules/vitest/vitest.mjs run src/qa-ui16-independent.test.ts --pool threads --maxWorkers 1 --configLoader runner --no-cache --no-fsModuleCache --reporter json --outputFile ../test/qa-ui16/independent-results.json，完成后删除执行副本。
- python test/qa-ui16/verify-source.py核验固定候选来源锁。test/qa-ui16/summary.json列实际环境、唯一用例及Delete原ID。

附件原始证据目录包含两模式各五页桌面/390实际截图、768检查、路径补图、三份浏览器结果、cleanup及首轮失败/焦点轨迹。manifest记录逐文件大小和SHA-256。源码/报告/JSON留在独立QA目录，截图作为附件交付，不塞入产品代码。

临时源测试副本已删除。实际管理结束回执code=0、cleaned=true；Edge、Vite与自有工作台进程均已前台结束，临时数据库/数据清理。没有留下长期服务。

真实模型/生产登录、Higress/Secret/validation、实际非空用量与SelfHosted、Helm/目标集群及A01–A34仍未验收；本地GPU研究未参与。MAAS-7继续in_progress，MAAS-5实际页面候选供成员评审，MAAS-12保持in_review；v1.5历史验收不改写。