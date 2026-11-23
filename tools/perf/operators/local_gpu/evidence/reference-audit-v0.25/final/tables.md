# v0.25 离线代表性审计

只重算固定v0.24原件。旧qualified=false、34/64与全部分母保持；均值差为描述性分解，不是因果效应或新门槛。

|分层|Δgap ms|Δprefix ms|Δprepare ms|Δquery ms|Δquery前后 ms|Q匹配|I匹配|
|---|---:|---:|---:|---:|---:|---:|---:|
|bare_graph/B3/mature/boundary_first|183.803233|4.333639|6.481432|172.988113|0.000050|0/2|2/2|
|bare_graph/B3/mature/interior|-114.343126|0.014553|-0.519313|-113.840271|0.001905|0/2|2/2|
|bare_graph/B3/native/boundary_first|-5.769011|-3.369738|-0.214242|-2.186672|0.001641|1/2|2/2|
|bare_graph/B3/native/interior|107.485912|-0.008849|-0.408346|107.902359|0.000749|0/2|2/2|
|bare_graph/B8/mature/boundary_first|-138.431533|-43.670242|-0.908436|-93.850356|-0.002498|0/2|2/2|
|bare_graph/B8/mature/interior|-0.383507|-0.194619|-1.494500|1.308144|-0.002532|0/2|2/2|
|bare_graph/B8/native/boundary_first|-77.891526|-6.603921|-0.853351|-70.434551|0.000298|0/2|2/2|
|bare_graph/B8/native/interior|-27.242609|-0.171721|2.018852|-29.090042|0.000302|0/2|2/2|
|full/B3/mature/boundary_first|-79.397138|-37.693278|-0.005282|-41.697750|-0.000827|1/2|2/2|
|full/B3/mature/interior|-154.797033|1.303872|-1.261933|-154.836299|-0.002673|0/2|2/2|
|full/B3/native/boundary_first|-354.137977|-203.397758|-7.094603|-143.645054|-0.000562|0/2|2/2|
|full/B3/native/interior|-71.220875|1.435329|1.108068|-73.766201|0.001929|0/2|2/2|
|full/B8/mature/boundary_first|-170.020082|-20.109316|-0.218251|-149.692075|-0.000441|0/2|2/2|
|full/B8/mature/interior|285.100994|-0.032596|0.075441|285.058061|0.000087|0/2|2/2|
|full/B8/native/boundary_first|170.086288|-47.319778|-1.613101|219.019995|-0.000827|0/2|2/2|
|full/B8/native/interior|9.650924|-1.007857|0.482611|10.139570|0.036599|0/2|2/2|

Δ均为holdout query(n=2/层)−reference query(n=3/层)；每层的精确有理数均值差可加总。表中显示值四舍五入不参与判定。median/min/max及每条原始区间见audit.json/rows.csv。

|分层|Δbookkeeping ms|Δ真实归档IO ms|Δ未细分prefix ms|
|---|---:|---:|---:|
|bare_graph/B3/mature/boundary_first|-0.038033|1.802431|2.569240|
|bare_graph/B3/mature/interior|0.013621|0.000000|0.000932|
|bare_graph/B3/native/boundary_first|-0.185345|-1.019460|-2.164933|
|bare_graph/B3/native/interior|-0.012111|0.000000|0.003262|
|bare_graph/B8/mature/boundary_first|-0.330870|-42.674397|-0.664975|
|bare_graph/B8/mature/interior|-0.191911|0.000000|-0.002708|
|bare_graph/B8/native/boundary_first|0.029528|-5.378165|-1.255284|
|bare_graph/B8/native/interior|-0.170243|0.000000|-0.001478|
|full/B3/mature/boundary_first|-0.348588|-33.693674|-3.651016|
|full/B3/mature/interior|1.303777|0.000000|0.000095|
|full/B3/native/boundary_first|-0.118413|-73.167850|-130.111495|
|full/B3/native/interior|1.434219|0.000000|0.001110|
|full/B8/mature/boundary_first|0.358633|-24.125497|3.657548|
|full/B8/mature/interior|-0.033984|0.000000|0.001388|
|full/B8/native/boundary_first|0.005526|-44.427837|-2.897468|
|full/B8/native/interior|-0.972636|0.000000|-0.035221|
