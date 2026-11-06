# 入门教程：从一次请求到可信结果

准备开发推理运行时或推理部署框架，请先读[工程主教材六章](foundations/README.md)。本页保留原练习路线，配合主教材使用。

适合有基本Python/命令行能力、尚未熟悉LLM推理和GPU性能的新成员。学习目标不是记住一批参数名，而是能回答：数据从哪里来、计算是否正确、时钟/分母是否一致、结论能用于哪一层。

建议分两次学习，每次45–60分钟；时间是学习安排建议，不是完成时限。先读概念、自己推导，再运行练习。答案见[答案页](exercises/answer-key.md)。

## 0. 准备一个无需GPU的学习环境

本手册对应包含5020d5c及后续文档修订的分支。全新clone可用：

~~~text
git clone https://github.com/jianzi123/maas
cd maas
git fetch origin
git switch --track origin/agent/MAAS-10-operator-runtime-lab
~~~

已有工作树先检查git status；不要覆盖同事未提交文件。默认分支或旧controlled-lab-team-docs分支未必有最新算子和finite门禁。

完整课程使用Python3.11+、jsonschema4.25.0、NumPy2.3.5；后者安装元数据要求Python>=3.11。原离线分析器单独使用与完整课程的最低依赖不同。本轮验证解释器为Python3.13.9。

~~~text
python --version
python -c "import importlib.metadata as m; print(m.version('jsonschema')); print(m.version('numpy'))"
~~~

版本匹配可直接继续。缺依赖时用项目venv和团队批准的离线包目录；下列<WHEELHOUSE>须先替换为实际路径，不可原样运行：

~~~text
python -m venv tools/perf/.venv
./tools/perf/.venv/Scripts/python.exe -m pip install --no-index --find-links <WHEELHOUSE> -r tools/perf/requirements.txt -r tools/perf/operators/requirements-cpu.txt
~~~

Windows后续用该venv解释器替换python；Linux对应tools/perf/.venv/bin/python。课程不安装Torch、CUDA或Triton。宿主C++单元另需GCC/Clang兼容编译器；没有时先完成纯Python部分，skip必须如实记录。

## 1. 先理解请求、token和两段推理

用户发来的是文本/协议消息。tokenizer与chat template决定真正进入模型的token序列；字符数、SSE片段数都不是token数。

prefill处理已有输入，建立后续生成所需状态。decode基于已有状态继续生成；KV保存attention相关状态。相同前缀可复用部分计算，但没有省掉业务准入、真实usage或全部decode。

例如一个序列输入256 token、上限128输出，不代表一定生成128；EOS可以提前结束。改变长度、精度或GPU后，得到的是新条件，不能直接算原条件优化。

### B01：为什么decode mask容易写错？

考虑q长度1、KV长度3，且q/k全0、v为[0,2,4]。这是“最后一个query看全部既有KV”，三个score相等，权重均为1/3，结果应为2。若错误地按左上三角只看第一个key，会得到0。

下面代码可从仓库根运行，或存为临时.py后运行：

<!-- smoke:B01 -->
~~~python
import sys
import numpy as np
sys.path.insert(0, "tools/perf/operators")
from reference import attention_dense
q = np.zeros((1, 1, 1, 1))
k = np.zeros((1, 1, 3, 1))
v = np.array([0.0, 2.0, 4.0]).reshape(1, 1, 3, 1)
print(attention_dense(q, k, v).ravel().tolist())
~~~

通过条件：输出[2.0]，并能解释为什么不是0。拓展问题：当Sq=2、Sk=3时两个query应分别看几个key？

## 2. 理解指标：慢在哪里，先区分测量点

- 客户端可见TTFT：实际sent到首个非空content完整事件；role/心跳/usage-only/空delta不算。
- Go first_chunk_ms：Go自己的服务端口径，不等于客户端TTFT。
- TPOT代理：(末内容−首内容)/(冻结tokenizer计数N−1)，N≤1为null；只有chunk不能报真实ITL。
- 成功E2E：sent到合法成功终止；HTTP200的流内error、raw EOF、缺DONE不是成功。
- 吞吐使用共同观察窗T，失败/拒绝仍在完整sent分母；pending/删失明确。

server/engine可在自身scope里算时长；两个不同客户端monotonic原点未经映射不能共享T。同一个标签也不能独立证明实际同步。

### B02：把报告算明白

~~~text
python tools/perf/analyze.py --input tools/perf/fixtures/synthetic.json --output tools/perf/reports/course/first-report.json
~~~

读报告后先写下五个值：sent=9、admitted=8、succeeded=4、known total=41、unknown token held=420。这些是固定人工夹具，不是MaaS实测。

<!-- smoke:B02 -->
~~~python
import json
from pathlib import Path
p = Path("tools/perf/reports/course/first-report.json")
r = json.loads(p.read_text(encoding="utf-8"))
print(r["counts"]["sent"], r["counts"]["admitted"], r["counts"]["succeeded"])
print(r["usage"]["total_tokens"]["known_sum"])
print(r["diagnostic_reconciliation"]["unknown_held_not_actual"]["token"])
print(r["rows"][0]["client_visible_ttft_ms"], r["rows"][0]["server_first_chunk_ms"])
~~~

通过条件：分别得到9/8/4、41、420、100/60。解释：为何不能把41+420写成实际消费？为何不能把100−60直接叫“网络p95”？

### B03：让一个错误输入被拒绝

~~~text
python tools/perf/fixtures/clock_scope_reproducer.py .
~~~

预期PASS，表示混合且未归一化的client scope被拒绝。原始反例脚本在内存中修改合成数据，不改仓库输入。能说明“request与自身observation相同”为什么还不够，才算完成。

## 3. 正确性先于速度

输出可能是有限错误值、NaN或±Inf。仅判断abs(actual-reference)>tolerance不够：NaN参与大小比较会让判断为false，甚至让maxerr看起来仍为0。

误差需要同时考虑绝对与相对尺度：abs(error)<=atol+rtol*abs(reference)，并先检查candidate、成熟baseline、reference和相关算术finite。阈值要按dtype和业务目标预登记，不能出结果后放宽。

### B04：跑一个不碰GPU的算子参考

~~~text
python tools/perf/operators/bench.py --output tools/perf/reports/course/operator-cpu.json
~~~

预期8组float64 CPU参考全部通过，gpu_executed=false，GPU timings=null。它覆盖小shape/边界/GQA等指定行为；不能据此宣布FP16、CUDA、FlashInfer或模型质量通过。

### B05：用真正编译的宿主程序检查门禁

~~~text
python tools/perf/operators/check_gemm_host.py --output tools/perf/reports/course/gemm-host.json
~~~

有编译器时，预期21场景通过：17拒绝路径exit1、stdout空，warmup/timing/reporting均0；4正常路径exit0；fast-math构建被拒绝。CUDA与此程序共用同一个header和成功continuation，但本练习没有编译CUDA文件或运行GPU。

无编译器时本步标未执行；不能将Python测试的skip当作这项通过。宿主GCC版本也不等于可用于CUDA的host工具链认证。

## 4. 最后一课：观察到了什么，结论能走多远？

### B06：读一次本地传输练习

可选，小规模命令会启动并自动结束127.0.0.1临时fixture：

~~~text
python tools/perf/controlled_transport.py --output-dir tools/perf/reports/course/http --requests 20 --concurrency 1 4 --repeats 1 --max-seconds 20
~~~

每case20请求；fresh预计20个连接，reuse在C1/C4下预计1/4个，实际以报告为准。检查sent/failed、共同窗口、冷/复用分组与cleanup。这里没有Go预算内核、Higress、模型或GPU，所以减少连接数不等于平台已提速。

## 自测与交付

先回答再看[答案](exercises/answer-key.md)：
1. decode q长度1为什么可看全部KV？
2. TTFT、Go首片、Worker指标的起止点为何不能交换？
3. N=1或不知道tokenizer时TPOT写什么？
4. rejected/failed/pending是否可从分母里删除？
5. NaN为什么不能只靠误差大于tol判断？
6. CPU参考、宿主C++、loopback结果分别能支持什么？

入门通过标准：交一页练习结果，标明环境、输出/hash、跳过项和结论边界，并正确解释上述六题。不要求GPU，不按“跑了多少测试”毕业。随后进入[进阶教程](advanced.md)。
