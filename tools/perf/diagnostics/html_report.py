"""Self-contained diagnostic HTML; every imported value is escaped."""

import html, json


def render(report):
    esc = lambda value: html.escape(str(value))
    table = (
        lambda headers, rows: "<table><thead><tr>"
        + "".join("<th>" + esc(h) + "</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join("<td>" + esc(v) + "</td>" for v in row) + "</tr>"
            for row in rows
        )
        + "</tbody></table>"
    )
    assets = table(
        ["asset", "capability", "evidence scope", "gap"],
        [
            [r["id"], r["capability"], r["evidence"], r["gap"]]
            for r in report["asset_inventory"]
        ],
    )
    boxes = [
        (15, "客户端", "sent / SSE / content"),
        (225, "Go / Redis / MySQL", "准入 / 锁 / commit / held"),
        (435, "Higress / 网络", "固定路由 / transport"),
        (645, "Worker", "queue / batch / KV"),
        (855, "GPU / 通信", "kernel / copy / rank"),
    ]
    diagram = '<svg viewBox="0 0 1070 220" role="img" style="display:block;width:100%;height:auto"><title>采集责任地图，非实测时间线</title><rect width="1070" height="220" fill="#f4f8fb"/>'
    for index, (x, label, sub) in enumerate(boxes):
        diagram += (
            '<rect x="'
            + str(x)
            + '" y="20" width="195" height="85" rx="8" fill="#e6f1f7" stroke="#9cb8cb"/><text x="'
            + str(x + 12)
            + '" y="48" font-size="17">'
            + html.escape(label)
            + '</text><text x="'
            + str(x + 12)
            + '" y="78" font-size="12">'
            + html.escape(sub)
            + "</text>"
        )
        if index < 4:
            diagram += (
                f'<line x1="{x+196}" y1="62" x2="{x+208}" y2="62" stroke="#6b879b"/>'
                f'<polygon points="{x+208},62 {x+203},58 {x+203},66" fill="#6b879b"/>'
            )
    diagram += '<text x="20" y="145" font-size="16">CR活动修订 / 工件 × 原request / run × 实例boot / batch / rank</text><text x="20" y="180" font-size="15">受控导出 → 关联与时钟校验 → 原指标 + 观察区间/依赖链 + 缺口</text><text x="20" y="207" font-size="13">采集责任地图；不是已执行链路、因果推断或模型瓶颈结论。</text></svg>'
    counts = report["metric_report"]["counts"]
    requests = table(
        [
            "request",
            "result",
            "protocol data ms",
            "client content TTFT ms",
            "Go first_chunk ms",
            "Worker native ms",
            "intervals",
        ],
        [
            [
                r["request_id"],
                r["result"],
                r["client_protocol_data_wait_ms"],
                r["client_visible_ttft_ms"],
                r["go_server_first_chunk_ms"],
                r["worker_native_ttft_ms"],
                r["interval_count"],
            ]
            for r in report["request_diagnostics"]
        ],
    )
    coverage = table(
        [
            "stage",
            "owner",
            "complete intervals / eligible",
            "interval coverage",
            "metric-only requests",
            "combined coverage",
            "source",
        ],
        [
            [
                r["stage"],
                r["owner"],
                str(r["known_requests"]) + " / " + str(r["denominator"]),
                (
                    None
                    if r["coverage"] is None
                    else str(round(r["coverage"] * 100, 1)) + "%"
                ),
                r["existing_metric_only_requests"],
                (
                    None
                    if r["combined_measurement_coverage"] is None
                    else str(round(r["combined_measurement_coverage"] * 100, 1)) + "%"
                ),
                r["source"],
            ]
            for r in report["coverage_by_stage"]
        ],
    )
    intervals = table(
        [
            "id",
            "stage",
            "local [start,end] ms",
            "local duration ms",
            "observed self ms",
            "missing / attribution",
            "evidence",
        ],
        [
            [
                r["id"],
                r["stage"],
                str([r["start_ms"], r["end_ms"]]),
                r["local_duration_ms"],
                r["exclusive_self_ms"],
                r["exclusive_missing_reason"] or r["attribution"],
                r["evidence_ref"],
            ]
            for r in report["timeline"]["intervals"]
        ],
    )
    chains = table(
        [
            "request",
            "observed active chain ms",
            "chain elapsed ms",
            "known dependency gaps ms",
            "interval IDs",
        ],
        [
            [
                r["request_id"],
                r["observed_active_dependency_chain_ms"],
                r["observed_chain_elapsed_ms"],
                r["known_dependency_gaps_ms"],
                " → ".join(r["interval_ids"]),
            ]
            for r in report["timeline"]["observed_dependency_chains"]
        ],
    )
    detail = (
        lambda value: "<pre>"
        + html.escape(json.dumps(value, ensure_ascii=False, indent=2))
        + "</pre>"
    )
    body = (
        '<h1>MaaS 请求到内核诊断报告</h1><div class="banner"><strong>'
        + esc(report["evidence_kind"])
        + "</strong> · synthetic="
        + esc(report["synthetic"])
        + ".<br>时钟映射与活动独占性来自导出声明；没有真实模型瓶颈、完整端到端关键路径或性能提升结论。</div>"
    )
    body += (
        "<p>数据 hash：<code>"
        + esc(report["dataset_sha256"])
        + "</code><br>sidecar hash：<code>"
        + esc(report["sidecar_sha256"])
        + "</code></p>"
    )
    body += (
        '<h2 id="assets">资产与证据盘点</h2>'
        + assets
        + "<p>历史证据不计作本轮复跑，生产collector缺口仍保留。</p>"
    )
    body += '<h2 id="counts">原指标与完整分母</h2>' + detail(counts)
    body += "<p>原报告 goodput/usage 保留原计算。未知 actual、held 与缺失覆盖率保持；其synthetic值不表示真实SLO通过。</p>"
    body += '<h2 id="requests">首事件与各层测点</h2>' + requests
    body += '<h2 id="coverage">采集覆盖与责任</h2>' + diagram + coverage
    body += (
        '<h2 id="timeline">区间与重叠处理</h2><p>observed self = 父区间减可比较的已导出直接子区间并集；可能还有未导出的工作，不等于某设备忙碌时间。共享batch不拆成逐请求独占。</p>'
        + intervals
    )
    body += (
        '<h2 id="chains">显式依赖链</h2><p>只在时钟可比较的已知活动中计算。活跃链权重不含依赖间隙；它不证明所有关键路径已覆盖。</p>'
        + chains
    )
    body += "<h3>被阻断的跨域/缺测边</h3>" + detail(report["timeline"]["blocked_edges"])
    body += (
        "<h2>取消与未恢复观察</h2>"
        + detail(report["recovery_groups"])
        + detail(report["recovery_missing_request_ids"])
    )
    body += '<h2 id="gaps">真实实验缺口</h2>' + detail(report["manifest_missing"])
    body += (
        "<details><summary>采集缺口清单</summary>"
        + detail(report["collection_gaps"])
        + "</details>"
    )
    body += '<h2 id="evidence">证据索引</h2>' + detail(report["evidence_index"])
    body += "<details><summary>完整诊断JSON</summary>" + detail(report) + "</details>"
    css = 'body{font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif;max-width:1400px;margin:30px auto;padding:0 28px;color:#183247;background:#f7f9fc}h1,h2{color:#123c5b}h2{margin-top:36px;border-bottom:2px solid #d7e3ed}table{display:block;overflow-x:auto;border-collapse:collapse;font-size:13px;background:white;margin:18px 0}th,td{border:1px solid #c5d5e2;padding:9px 11px;vertical-align:top}th{background:#eaf2f7;text-align:left}pre{overflow:auto;white-space:pre-wrap;background:#152e43;color:#edf5ff;padding:18px;border-radius:7px;font:12px/1.6 Consolas,monospace}.banner{padding:18px 22px;border-left:5px solid #178080;background:#e3f3f0}details{margin:15px 0}summary{cursor:pointer;font-weight:600}code{overflow-wrap:anywhere}nav a{margin-right:20px;color:#126da2}'
    nav = (
        "<nav>"
        + "".join(
            '<a href="#' + i + '">' + label + "</a>"
            for i, label in [
                ("assets", "资产"),
                ("counts", "分母"),
                ("requests", "测点"),
                ("coverage", "覆盖"),
                ("timeline", "区间"),
                ("chains", "依赖链"),
                ("gaps", "缺口"),
                ("evidence", "证据"),
            ]
        )
        + "</nav>"
    )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MaaS 推理诊断</title><style>'
        + css
        + "</style></head><body>"
        + nav
        + body
        + "</body></html>"
    )
