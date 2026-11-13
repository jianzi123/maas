# 本地服务交接

根目录 `npm run dev` 仍以前台方式运行。Windows当前Multica环境监管尚不支持；成员要求服务在编码回合后继续可用时，可使用独立Node宿主，隐藏启动并分别重定向stdout/stderr到 `.cache/workbench-service/`。

启动程序为 `node scripts/workbench-service.mjs start`，默认127.0.0.1:4179；启动进程可通过环境变量MAAS_LOCAL_SERVICE_PORT改端口，不开放公网监听。状态、PID、实际URL和到期时间保存在 `.cache/workbench-service/status.json`，日志为同目录stdout.log/stderr.log，不包含会话原值。

在仓库根目录用 PowerShell 隐藏启动（已有实例时先停止并确认清理完成）：

```powershell
$repoPath = (Get-Location).Path
$logPath = Join-Path $repoPath '.cache/workbench-service'
New-Item -ItemType Directory -Force -Path $logPath | Out-Null
Start-Process -FilePath (Get-Command node.exe).Source `
  -ArgumentList 'scripts/workbench-service.mjs','start' `
  -WorkingDirectory $repoPath -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $logPath 'stdout.log') `
  -RedirectStandardError (Join-Path $logPath 'stderr.log')
```

状态变为 `ready` 后再打开其中的URL；`starting` 期间仍在构建或初始化。重复启动由独占锁拒绝，不接管已有宿主。

```sh
node scripts/workbench-service.mjs status
node scripts/workbench-service.mjs stop
```

stop按本次宿主ID请求停止，宿主关闭原工作台stdin，让Go/API-server/etcd和私有MySQL按既有路径清理。以status的stopped/cleaned=true确认停止；停止后本次临时数据清空。独立宿主最多保留8小时，到期同样清理。它不依赖编码回合，但系统退出/休眠或强制结束进程仍可能中断；本回退不冒充Multica守护进程监管。

工作台仍为本地管理链路：目录、Key/预算/撤销、发布管理和原操作查询可用。真实Higress/Secret/validation及模型推理未接通，不因启动本地环境而放行生产。页面本地会话到期可重新连接。
