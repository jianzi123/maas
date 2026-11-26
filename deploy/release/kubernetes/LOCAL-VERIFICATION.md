# 自有本地原生 K8s 验证与升级

此入口复用原生 YAML、正常 `maas-service`、MySQL、既有 Chat/工具/取消 smoke，不创建平行内核，不代替独立 QA。不使用当前默认 Kubernetes context；所有写入仅允许本入口新建的 `maas8-*` kind 集群、专属 kubeconfig 和带本任务归属标签的 namespace。不会接管已有同名集群，也不推镜像或调用真实模型。

本轮基线为统一远端 Merge commit `4402c456a155646ee4111e5f4a1f285621c11273`（含已交 d27）。历史 Compose/作者/独立 QA 证据保持原 SHA。**新增脚本的夹具或 schema 通过不表示本轮 K8s 已实装**；本轮真实执行范围及环境原件见任务交付。

## 环境与前置

- Windows 或 Linux：Python3.10+、`source/deploy/checks/requirements.txt` 所列依赖、Git、Docker Linux Engine、kubectl、kind；原生构建另需 Go1.26.0 和 Node22.23.4。
- 本地测试预设使用 [kind v0.33.0 官方版本](https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0)、其 v1.36.4 节点 `kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed`。按[官方安装入口](https://kind.sigs.k8s.io/docs/user/quick-start/)安装 CLI，校验官方 release digest，不必改全局 PATH。
- 预检默认要求至少4096 MiB当前可用物理内存，给新增控制平面/MySQL/应用及宿主留余量；这是测试门槛，不是容量或性能保证。WSL还核对Windows宿主余量；只看VM空闲页不够。资源不足不自动停止任何现有项目，不修改Docker/WSL全局配置。
- 空闲端口默认18686；kind API仅loopback。默认ExternalAPI没有获准模型；运行验证必须**显式**选择offline-controlled，且不混真实models/management。模型、rate/来源等证明为离线替身，工具/HTTP/MySQL/原计量仍为实际实现。

以下命令从仓库根运行，`RUN`换成自己的**新**受保护目录。源码必须先提交并运行标准四锁脚本，工作树不能有未提交或未跟踪输入；脚本实际校验同一ref的后端/前端/部署清单。Windows可用 `--docker "C:/Program Files/Docker/Docker/resources/bin/docker.exe" --kubectl "C:/Program Files/Docker/Docker/resources/bin/kubectl.exe" --kind <本地kind.exe>` 显式传工具路径。

```sh
python deploy/release/kubernetes/local_verify.py probe --root RUN
```

退出0才表示环境具备创建条件；2表示预检未满足，见 `RUN/evidence/environment.json`、commands.json和各stdout/stderr。仅探测本地Unix socket/named pipe，不连接ssh/tcp Docker。kubectl只查客户端版本，不写默认context。kind缺失、Docker不可达、超时（124）和内存不足分别记录，不改记成产品断言失败。

## 首次安装

```sh
python deploy/release/kubernetes/local_verify.py prepare --root RUN --source . --profile offline-controlled --cluster maas8-native-1126 --namespace maas8-native-1126 --port 18686
# 显式离线取消演示采用step_delay_ms=5000，保留实际limits，不能据其声明真实供应商时延。
python deploy/release/kubernetes/local_verify.py create --root RUN
# 环境门槛通过后才执行依赖/构建，不在内存不足时放大编译并发。
python deploy/release/build_native.py --root . --go-jobs 1
```

共享宿主可显式设置标准Go `GOMEMLIMIT=256MiB`；构建器实际消费此值和`--go-jobs`，不新增产品运行环境变量。`prepare`不安装集群，只生成新的Secret/配置/原生资源和owner.json；遇既有Secret/配置拒绝覆盖。

读取 `RUN/owner.json` 的 `revision`、`tag`，分别替换下面的 CODE/TAG；是源代码锁版本，不以浮动latest作为验收依据：

```sh
docker build --target app -t maas-app:TAG --build-arg SOURCE_REVISION=CODE -f deploy/release/Dockerfile.native .
docker build --target web -t maas-web:TAG --build-arg SOURCE_REVISION=CODE -f deploy/release/Dockerfile.native .
docker build --target migrate -t maas-migrate:TAG --build-arg SOURCE_REVISION=CODE -f deploy/release/Dockerfile.native .
docker pull mysql:8.4.7@sha256:0426ec38c7a10aa45ba383887df7878f74ee70e2fd589c7b69207f3577901903
python deploy/release/kubernetes/local_verify.py install --root RUN
python deploy/release/kubernetes/local_verify.py verify --root RUN
```

安装先核三镜像OCI source标签并加载到本任务节点，再创建namespace/Secret/配置/MySQL与PVC。旧应用存在时先缩为0、等旧Pod消失，再执行版本化迁移Job；Job失败不恢复旧调度器或启动新应用。Job成功后仍以**运行源码内所有product迁移**的版本/Applied/checksum核对，再装应用并等探针。1/2等必需版本Applying、缺失或checksum不一致均拒绝继续，不把Job历史complete当作当前数据库就绪。

正式服务内部也必须执行相同必需版本门禁。本入口的部署顺序不修复或掩盖旧4402中仅检查001的服务启动缺口；MAAS-20原作者负责修复、marker-only/缺表/恢复回归，后续组合需另验。

## 运行、分权与恢复验证

`verify`仅接受本入口记录的自有集群/namespace及显式离线profile。它按以下步骤采证，任何失败保留原记录，不自动重试生成：

1. 核实际Deployment仅挂maas-runtime、UID65532/只读根；独立Job用实际runtime client配置核CURRENT_USER/恰好四个default roles、Session读取/CAS；DDL/mysql.user/payload/Operations必须出现真实权限错误，连接失败不算越权被拒。
2. 在空闲loopback端口启动自有kubectl port-forward；正常共享登录，复用原Chat＋Agent两工具/一次批准、JSON/SSE游标、原命令幂等与child用量smoke，再复用已准入取消脚本。文件预存operation/Run/decision；已有记录只GET验证，未完成记录拒绝，绝不删记录重发。
3. 保持同Cookie/admin/CSRF，先重启应用，再删除本namespace的mysql-0 Pod由StatefulSet重建；PVC UID/volumeName必须不变。每次原Chat/Agent/取消记录只读回放，完整Session文档SHA、原请求/唯一usage计数保持，必需迁移仍Applied。
4. 所有命令都有deadline，结果存evidence。port-forward属于本次前台验证，finally终止并等待该精确子进程，不留后台等待。日志不输出Cookie、密码、DSN或Secret对象；**config.yaml/.secrets/kubeconfig不作为公开证据上传**。

测试集群内能创建NetworkPolicy对象不等于目标CNI已经执行网络隔离；网络策略的实际阻断需另测，脚本不宣称该项通过。离线测试也不关闭真实供应商/Higress/正式tools-v1/生产管理装配或A01–A34。

## 升级、停止与数据保留

升级前使用批准的备份流程备份MySQL和安装身份/Secret，保留原request/usage/held、消息/事件/checkpoint/审批。新源码先提交/重锁并构建对应CODE/TAG三镜像，再使用同一个RUN：

```sh
python NEW_SOURCE/deploy/release/kubernetes/local_verify.py upgrade --root RUN --source NEW_SOURCE
python NEW_SOURCE/deploy/release/kubernetes/local_verify.py verify --root RUN
```

`upgrade`不重新运行随机配置生成器，不覆盖config.yaml/.secrets、origin/cluster/admin/预算/pepper/cursor、PVC；先核新镜像存在/source标签，再备份旧owner记录、渲染新版本资源并沿停止旧调度器→新迁移→应用顺序安装。新backend有必需字段时按其实际消费手动核准既有配置，缺输入失败关闭，不复制未消费环境变量。失败只读原Job/Pod日志，保持原ID，不自动改旧checksum、降迁移或清库。此入口不证明任意旧镜像向前兼容，回滚须审定schema兼容或隔离备份恢复。

```sh
python deploy/release/kubernetes/local_verify.py stop --root RUN
```

默认停止仅将本namespace应用/MySQL缩为0，保留PVC/Secret与owner记录。仅资源验证而非持久服务交付的Agent运行，采完证据后还应对**自己创建并记录**的测试节点完成清理：先作受保护备份，明确需要销毁本次临时PVC时再执行 `kind delete cluster --name maas8-native-1126`；它会删除该临时节点上的local-path数据，不能拿来做普通产品卸载/回滚。不要删除已有集群、默认namespace、成员目标或他人项目。未执行销毁时必须准确交接保留资源，不能声称已释放。

主集成负责最终同SHA两包，本入口只交代码/脚本/准确验证证据。最终版本仍运行标准四锁脚本，再由MAAS-21用既有package.py/verify-delivery.py统一重生和校验两包，不能并行制作同版本不同内容。
