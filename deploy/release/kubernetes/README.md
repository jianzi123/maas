# MaaS 原生 Kubernetes YAML 安装包

本包为可由kubectl执行的原生资源，非Helm包装。完整source与Compose包同一VERSION/四锁，镜像不预设存在于公开仓库。使用本包源码重建三镜像，并按目标获准方式加载到节点或推送到批准私库；本任务不公开推镜像。

## 准备 / 构建

需要Docker、Python3.10+、Go1.26.0、Node22.23.4和已获准K8s上下文。验证schema基线1.36.0；实际集群安装情况见VALIDATION.md。单实例MySQL/PVC需要默认StorageClass或在mysql.yaml明确设置批准存储类。

```sh
python -m pip install -r source/deploy/checks/requirements.txt
python source/deploy/release/verify_bundle.py --root .
python source/deploy/release/configure.py --format kubernetes --directory . --port 18080
python source/deploy/release/build_native.py --root .
# VERSION.json imageTag 即以下 <tag>，三目标来自同一个source
docker build --target app -t maas-app:<tag> --build-arg SOURCE_REVISION=<codeCommit> -f source/deploy/release/Dockerfile.native source
docker build --target web -t maas-web:<tag> --build-arg SOURCE_REVISION=<codeCommit> -f source/deploy/release/Dockerfile.native source
docker build --target migrate -t maas-migrate:<tag> --build-arg SOURCE_REVISION=<codeCommit> -f source/deploy/release/Dockerfile.native source
```

对自己的隔离kind集群可用kind load docker-image三镜像；远端节点需先按授权私库映射修改application.yaml/migration.yaml镜像名或digest及imagePullSecrets。未经批准不写已有目标集群。容器runtime/迁移/代理与Compose完全相同。

专属离线演示可在首次生成时显式加`--profile offline-controlled`，默认external-api不启用替身。此profile使用同正常入口/MySQL及原计量，不能混用真实models或management；模型/rate/来源证明为受限合成，工具、审批、历史和账本为实际实现。当前核心运行账号仅kernel+release_reader+agent+auth，检测到历史额外角色会拒绝迁移，不自动撤权。

正式管理装配另需四个独立DSN/单角色及批准Registry/kubeconfig/授权域，详见source/docs/product-management-and-offline.md。将文件加入maas-runtime Secret并精确挂载；不得复用core，不默认获得集群权限。缺前置保持management关闭，原生YAML安装成功不等于模型/发布链Ready。

## 原生应用顺序

确认当前context为明确批准目标，namespace maas未被其他项目占用或这是保留原Secret的同一安装。
```sh
kubectl apply -f namespace.yaml
kubectl apply -f config.yaml
kubectl apply -f mysql.yaml
kubectl -n maas rollout status statefulset/mysql --timeout=300s
kubectl apply -f migration.yaml
kubectl -n maas wait --for=condition=complete job/maas-migrate-<tag> --timeout=180s
kubectl apply -f application.yaml
kubectl -n maas rollout status deployment/maas --timeout=180s
kubectl -n maas rollout status deployment/web --timeout=180s
kubectl -n maas port-forward service/web 18080:8080
```

config.yaml由生成器实际生成Secret与ConfigMap，须留本地受保护位置、不提交Git/评论；包含mysql root、独立runtime和migration三类Secret及公开console配置。浏览器 http://localhost:18080；admin初始化密码仅在.secrets/migration/maas_bootstrap_password。若使用批准域名/TLS，应在生成器--origin选择真实URL，设置secure_cookie并按目标入口安装；默认不创建公网Ingress/LoadBalancer。

应用Recreate/replicas=1，避免新旧scheduler并发争锁；挂载运行Secret，不挂迁移DSN/bootstrap。MySQL有独立StatefulSet/Service/PVC，业务Session/事件/消费均走MySQL，不使用应用本地卷。web只公开console-config.json，私有product.json只给Go。未有模型不伪造Callable，真实text/tools能力、Higress/平台Key输入及验收范围同source/docs/product-service.md。

## 停止 / 升级 / 数据保留

停止只缩容maas/web与MySQL，保留PVC/Secret/ConfigMap，别删除namespace或原事件/unknown-held。升级保留所有安装ID、pepper/cursor、数据库与Secret；先停止旧maas→备份→使用新版本独立Job迁移→新镜像启动→重新启动web解析服务。失败查看本版本Job日志，不清schema或修改旧checksum。数据回滚只在批准的灾难恢复流程，不是普通应用回滚。

检查：kubectl -n maas get pods,pvc,job；logs deployment/maas、job/maas-migrate-<tag>。ready失败不等于模型故障，先核MySQL/迁移/角色/调度所有权；空models或tools拒绝属于明确能力边界。

外置MySQL时不要应用mysql.yaml，生成器--database-host指向批准数据库，并按Compose README同样的安装/运行凭证和DBA预配说明配置；migration Job与app仍只用各自DSN。shared实例禁止默认叠加全局同名角色，DBA预置后在Job环境设置MAAS_INSTALL_PROVISION_ROLES=0。未验证目标、TLS、存储或权限时不能声称已完成安装。

10–15分钟演示、工具接口/功能状态见source/console/docs；无GPU基础安装保留自托管源代码和既有配置但不自动部署GPU/LWS。原生产Higress/Secret/validation/真实模型与独立QA结果分开记录。
