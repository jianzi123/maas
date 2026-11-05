# 新成员入门与本地练习

目标：先理解一次请求的身份、时间和账本，再复现一个可解释的小结果。所有练习都无需平台Key、供应商凭证、GPU或集群。

## 0. 进入正确分支

项目仓库为https://github.com/jianzi123/maas。入门工作台在本交付分支，未合并前默认分支不一定包含它：

    git clone https://github.com/jianzi123/maas
    cd maas
    git fetch origin
    git switch --track origin/agent/MAAS-10-controlled-lab-team-docs

已有工作树先检查未提交改动，不覆盖同事文件。Go控制器与Python工具目录独立；本入门练习不需要运行Go、Docker、kubectl或Helm。

## 1. 准备Python

Python至少3.10；原分析器依赖jsonschema==4.25.0，新增算子CPU参考/完整回归还需NumPy2.3.5（operators/requirements-cpu.txt）。本轮使用Python3.13.9，无需Torch或GPU即可跑CPU参考。先检查已安装版本：

    python --version
    python -c "import importlib.metadata; print(importlib.metadata.version('jsonschema'))"

缺依赖时在工具自己的venv内使用团队批准的离线wheelhouse：

    python -m venv tools/perf/.venv
    tools/perf/.venv/Scripts/python -m pip install --no-index --find-links <approved-wheelhouse> -r tools/perf/requirements.txt -r tools/perf/operators/requirements-cpu.txt

Windows后续将python替换成该venv解释器；Linux使用tools/perf/.venv/bin/python。不要因为练习失败就升级团队共享工具链。

## 2. 第一个离线结果

    python tools/perf/analyze.py --input tools/perf/fixtures/synthetic.json --output tools/perf/reports/first-report.json

先只核对五个事实：sent=9、admitted=8、succeeded=4、known total token=41、unknown token held=420。41与420不能相加作为实际消费。这里的1秒逻辑窗是人工构造，不是平台吞吐。

再运行原始时钟反例：

    python tools/perf/fixtures/clock_scope_reproducer.py .

预期PASS：两个未经归一化的客户端monotonic坐标不能共用一个吞吐窗。server/engine可在自身时钟内算时长，不能跨坐标直接相减。

## 3. 小规模本地HTTP/SSE练习

    python tools/perf/controlled_transport.py --output-dir tools/perf/reports/local-first --requests 20 --concurrency 1 4 --repeats 1 --max-seconds 20

该命令自己启动127.0.0.1随机端口fixture，固定合成请求，只比较fresh/reuse连接方式，结束前停止并join所有线程。没有任意endpoint参数、自动重试或外部调用模式。输出transport-report.json与transport-cases.csv。

检查每个case：sent/succeeded/failed、实际accepted_tcp_connections、首内容TTFT、E2E、冷/复用连接分组、窗口与cleanup。token/model字段为null或不适用；SSE片段数不能当token数。fresh预计每请求一个连接；reuse预计每worker一个连接，实际结果以报告为准。

## 4. 如何读测试和源码

    python -m unittest discover -s tools/perf -p "test_*.py" -v

优先读test_analyze.py的手算断言，再读analyze.py；受控HTTP实验看controlled_transport.py和test_controlled_transport.py。入门时不要先改expected-report文件来让测试变绿。

后端入门按[集成说明](../integration.md)与[MySQL实现](../mysql-release.md)继续。发布屏障库已经有受控数据库验证，不代表生产Operator已装配真实调用内核/网关证据。

## 5. 常见误读

| 现象 | 正确处理 |
|---|---|
| ModuleNotFoundError/jsonschema版本不符 | 准备锁定依赖，不运行真实端点代替测试 |
| 端口/安全策略拒绝loopback | 记录错误及受影响case；不改为访问外部API |
| CLI退出2没有新报告 | 输入/版本/时钟或文件访问被拒绝；先检查退出码，别读旧报告 |
| 看到48项或更多测试通过 | 只说明列出的行为通过，不能推断全部性能/时钟同步/账本验收 |
| 看到controller Ready缺依赖 | 是故障关闭边界；不能用假receipt补成可调用 |
| “为什么还没有模型性能数字” | 先看[阶段总结](progress-and-summary.md)中哪些真实运行依赖未具备 |

提交一个改动前，在[实验记录模板](templates/experiment-record.md)填写证据级别、固定条件、结果、未执行项及回退方式。
