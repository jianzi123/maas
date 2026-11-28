# 约14分钟同源站点演示

2026-11-26：本脚本以已交付d27/统一基线4402的正常maas-service+MySQL为基础，复用现有Chat/Agent。离线模型和真实工具分清：模型为明确offline-controlled合成响应，算术/目录为真实Go安全工具；不是供应商、生产Higress或目标集群验收。新正式tools-v1桥以MAAS-20固定新头/批准配置为准，不从前端伪造。

准备：按MAAS-21同版本包README校验/取源、构建、configure --profile offline-controlled，再启动专属Compose project。正常ExternalAPI默认空models可登录/查历史但不能生成，不自动启用demo。迁移/运行身份分离；保留MySQL卷、安装ID、pepper/cursor、密码和原账本。密码仅从本地受保护文件读取，不展示.env/product/Secret。记录实际源码/镜像/迁移/协议/工具版本与URL。

| 时间 | 提示词与操作 | 预期画面及依据 | 限制/失败定位 |
|---|---|---|---|
| 0:00–2:00 启动/初始化/登录 | 按包内migrate/serve与Compose说明启动；登录同一URL | 健康后输入可编辑，首次401晚到不再清空正在输入的密码；一个Go/MySQL登录来源和CSRF | 首次检查期间输入禁用；401核凭据，403核同源/CSRF，502查Go和代理。healthz不代表模型可调用 |
| 2:00–3:00 来源/能力 | 打开Chat，查看模型和模式；另看空模型安装的禁用截图 | 受控模型明确标注；Agent仅由tools-v1/批准字段开放；无模型不发送 | 不能从别名猜供应商或工具能力。旧在线试用未装配时仅引导Chat，不再要求Key；R-P01旧405不是供应商失败 |
| 3:00–4:30 普通流式Chat | 新建会话，普通Chat，输入“用两句中文确认本次连接，并输出🙂。” | 正常AR-1流式显示中文/emoji和明确离线标记；原Run和child ID可读 | 受控回答有固定内容，不要求遵循所有自然语言指令；没有获准真实来源时不调用真实模型 |
| 4:30–6:30 Agent/两安全工具 | 切Agent，输入“计算6×7，再列出当前授权模型。” | 真实参数{a:6,b:7,op:multiply}和{}，真实结果42/授权目录；Step、ToolCall、实际attempt可读 | 本离线模型固定选择两注册工具，不冒充任意规划能力。ModelDirectory必须来自可信scope |
| 6:30–7:30 必要批准 | 核对工具名版本、参数、摘要和期限，再批准要求批准的安全计算申请 | 等待时attempt0，批准后按实际字段推进；目录按安装策略可能不需要批准 | 不在UI延长有效期。过期/权限变化查原Approval；unknown不批准重跑。只有当前profile明确支持时演示 |
| 7:30–8:30 拒绝与错误 | 在新的明确意图运行中拒绝同类申请 | failed/approval_denied，未执行工具attempt0；原失败运行已结束，不再永久“等待结果” | 拒绝工具不代表此前模型无用量或退款。保留原command/decision，不用新ID重试未知写入 |
| 8:30–9:30 停止 | 按受控说明设step_delay_ms=5000并只重启自有Go；发普通Chat，确认原child in_progress后点击停止 | ACK202后等权威cancelled；不假报AR-1格式错误，不再显示终态仍等待终止 | 自然完成不算取消成功；真实上游实际停止/计量需其权威证据，未知Token/金额不补0 |
| 9:30–10:30 断线/刷新 | 活动运行中断开事件连接→只读重连；刷新同一会话URL | 只是事件GET断开，原child仍运行；恢复同一Run，无新生成/取消POST | 若未知ACK先查原command。410整批GET重建；持续变化有界等待/提示，不无限重放。工具页故障输入单列，不冒充自然流量 |
| 10:30–12:30 Go/MySQL重启 | 对专属project顺序重启maas和mysql，不删除卷/身份；同一浏览器保持Cookie | 原可信principal/Cookie/CSRF仍有效，消息/事件/工具/child与用量哈希保持，SQL请求/usage总数不增 | 只重启本任务服务。DB不可用失败关闭；新迁移门禁与真实模型桥按后端新版本另验，不能用文件会话补缝 |
| 12:30–14:00 原父子用量/收尾 | 展开Run计量，按原child ID精确GET；对比重启前后 | known/inflight/held、aggregation_complete、币种价表独立展示；原请求不重复消费 | 本轮USD/Token为受控数据，不是真实账单。HTTP追踪ID不是计量child ID，未接入旧入口没有原ID时不编造 |

失败后保留原ID/record和截图：不要覆盖记录、清库、重建随机安装身份或再发生成。已有完整record用deployed-site的MAAS_SMOKE_VERIFY_RECORD或原安装smoke.py --phase verify只读重放；已知拒绝记录的恢复不再次提交决定。自动化参数、原工具页410输入、专属重启脚本见deployment.md。

当前功能/源码与范围见agent-features.md及site-validation-20261126.md。文件、shell、MCP、长期记忆和多Agent未实现，不列作可用工具。演示完成停止自有临时服务，保留原数据与受保护配置供复验；不留常驻站点。
