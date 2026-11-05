#!/usr/bin/env python3
"""Bounded loopback-only HTTP/SSE fixture lab, never a MaaS or model benchmark."""
from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import math
import socket
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from analyze import InputError, distribution, sse_metrics

BODY = b'{"fixture":true}'
PARTS = [
    b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n',
    b'data: {"choices":[{"delta":{"content":"fixture-a"}}]}\n\n',
    b'data: {"choices":[{"delta":{"content":"fixture-b"}}]}\n\n',
    b'data: {"choices":[],"fixture_usage":"not_a_model"}\n\n',
    b'data: [DONE]\n\n',
]
HOST = "127.0.0.1"


class LabServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, first_ms, gap_ms, request_cap):
        self.counter_lock = threading.Lock()
        self.accepted = 0
        self.requests_seen = 0
        self.connection_ids = {}
        self.first_ms, self.gap_ms, self.request_cap = first_ms, gap_ms, request_cap
        super().__init__((HOST, 0), FixtureHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        connection.settimeout(2)
        with self.counter_lock:
            self.accepted += 1
            self.connection_ids[connection] = self.accepted
        return connection, address

    def shutdown_request(self, request):
        with self.counter_lock:
            self.connection_ids.pop(request, None)
        super().shutdown_request(request)


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass  # No URLs, request bodies, credentials or headers in routine logs.

    def do_POST(self):
        length = self.headers.get("Content-Length", "")
        if self.path != "/fixture/chat" or not length.isdigit() or int(length) > 1024:
            self.close_connection = True
            self.send_error(400, "invalid fixture request")
            return
        body = self.rfile.read(int(length))
        if body != BODY:
            self.close_connection = True
            self.send_error(400, "invalid fixture body")
            return
        with self.server.counter_lock:
            self.server.requests_seen += 1
            over_limit = self.server.requests_seen > self.server.request_cap
            connection_id = self.server.connection_ids[self.connection]
        if over_limit:
            self.close_connection = True
            self.send_error(429, "fixture request cap")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(sum(map(len, PARTS))))
        self.send_header("X-Fixture-Connection", str(connection_id))
        self.end_headers()
        try:
            for index, part in enumerate(PARTS):
                if index == 1:
                    time.sleep(self.server.first_ms / 1000)
                if index == 2:
                    time.sleep(self.server.gap_ms / 1000)
                self.wfile.write(part)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True


@contextmanager
def fixture_server(first_ms=10, gap_ms=5, request_cap=200):
    server = LabServer(first_ms, gap_ms, request_cap)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": .05}, daemon=False)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()  # joins non-daemon request handlers
        thread.join(timeout=3)
        if thread.is_alive():
            raise RuntimeError("fixture server did not terminate")


def validate_config(requests, concurrency, repeats, first_ms, gap_ms, max_seconds):
    if type(requests) is not int or not 1 <= requests <= 200:
        raise ValueError("fixture requests must be 1..200 per case")
    if type(concurrency) is not int or concurrency not in (1, 2, 4):
        raise ValueError("fixture concurrency must be 1, 2 or 4")
    if type(repeats) is not int or not 1 <= repeats <= 3:
        raise ValueError("fixture repeats must be 1..3; exploratory only")
    for value in (first_ms, gap_ms):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 50:
            raise ValueError("fixture delay must be 0..50 ms")
    if not math.isfinite(max_seconds) or not 1 <= max_seconds <= 90:
        raise ValueError("fixture deadline must be 1..90 seconds")


def run_case(requests, concurrency, variant, deadline, origin_ns,
             first_ms=10, gap_ms=5):
    validate_config(requests, concurrency, 1, first_ms, gap_ms, 90)
    if variant not in ("fresh", "reuse"):
        raise ValueError("unknown fixture connection variant")
    stop = threading.Event()
    rows = []
    # A server is private to this case, with a hard request cap and no external endpoint.
    with fixture_server(first_ms, gap_ms, requests) as server:
        port = server.server_address[1]

        def worker(worker_id):
            connection, seen = None, set()
            records = []
            try:
                for index in range(worker_id, requests, concurrency):
                    if stop.is_set() or time.monotonic() >= deadline:
                        stop.set()
                        break
                    started = time.monotonic_ns()
                    frames, connection_id = [], None
                    state, reason = "failed", None
                    try:
                        if connection is None:
                            connection = http.client.HTTPConnection(HOST, port, timeout=2)
                        connection.request("POST", "/fixture/chat", BODY,
                                           {"Content-Type": "application/json"})
                        response = connection.getresponse()
                        if response.status != 200:
                            raise InputError("fixture HTTP status")
                        connection_id = int(response.getheader("X-Fixture-Connection", "0"))
                        if connection_id < 1:
                            raise InputError("missing fixture connection identity")
                        # Timestamp complete SSE lines, not one assumed token per read.
                        byte_count = 0
                        while True:
                            line = response.readline(4097)
                            if not line:
                                break
                            byte_count += len(line)
                            if len(line) > 4096 or byte_count > 65536:
                                raise InputError("fixture response cap")
                            frames.append({"at_ms": (time.monotonic_ns() - origin_ns) / 1e6,
                                           "wire": line.decode("utf-8")})
                        response.close()
                        parsed = sse_metrics(frames)
                        if not parsed["done"] or parsed["error"] or parsed["truncated"]:
                            raise InputError("fixture incomplete SSE")
                        state = "succeeded"
                    except (OSError, http.client.HTTPException, ValueError, InputError):
                        reason = "fixture_transport_or_protocol_error"
                        stop.set()  # No generation retries or extra calls after error.
                    finished = time.monotonic_ns()
                    content = sse_metrics(frames)["content_times"] if state == "succeeded" else []
                    start_ms = (started - origin_ns) / 1e6
                    records.append({
                        "request_index": index, "worker": worker_id, "result": state,
                        "error_class": reason, "sent_ms": start_ms,
                        "end_ms": (finished - origin_ns) / 1e6,
                        "client_visible_ttft_ms": content[0] - start_ms if content else None,
                        "client_e2e_ms": (finished - started) / 1e6 if state == "succeeded" else None,
                        "connection_id": connection_id,
                        "new_connection_observed": connection_id not in seen if connection_id else None,
                        "visible_tpot_proxy_ms": None, "model_tokens": None,
                    })
                    if connection_id:
                        seen.add(connection_id)
                    if variant == "fresh" or state != "succeeded":
                        connection.close()
                        connection = None
            finally:
                if connection is not None:
                    connection.close()
            return records

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(worker, worker_id)
                       for worker_id in range(min(concurrency, requests))]
            for future in futures:
                rows.extend(future.result())
        accepted, seen_requests = server.accepted, server.requests_seen
    # The server and every handler have terminated before a result can be returned.
    rows.sort(key=lambda row: row["request_index"])
    sent = len(rows)
    succeeded = sum(row["result"] == "succeeded" for row in rows)
    start = min((row["sent_ms"] for row in rows), default=None)
    end = max((row["end_ms"] for row in rows), default=None)
    seconds = (end - start) / 1000 if sent and end > start else None
    metrics = {name: distribution([row[name] for row in rows], sent) for name in
               ("client_visible_ttft_ms", "client_e2e_ms")}
    for group, is_new in (("new_connections", True), ("reused_connections", False)):
        subset = [row for row in rows if row["new_connection_observed"] is is_new]
        metrics[group] = {name: distribution([row[name] for row in subset], len(subset))
                          for name in ("client_visible_ttft_ms", "client_e2e_ms")}
    return {
        "variant": variant, "concurrency": concurrency, "planned": requests,
        "sent": sent, "succeeded": succeeded, "failed": sent - succeeded,
        "unsent": requests - sent, "accepted_tcp_connections": accepted,
        "server_requests_seen": seen_requests,
        "complete": sent == requests and succeeded == requests,
        "window_ms": {"start": start, "end": end},
        "observed_fixture_success_rps": succeeded / seconds if seconds else None,
        "failure_over_sent": (sent - succeeded) / sent if sent else None,
        "metrics": metrics, "rows": rows,
        "cleanup": {"fixture_server_stopped_and_handlers_joined": True},
    }


def run_lab(requests=200, concurrencies=(1, 4), repeats=3,
            first_ms=10, gap_ms=5, max_seconds=90):
    if not isinstance(concurrencies, (tuple, list)) or not concurrencies:
        raise ValueError("empty fixture concurrency list")
    if len(set(concurrencies)) != len(concurrencies):
        raise ValueError("duplicate fixture concurrency")
    for concurrency in concurrencies:
        validate_config(requests, concurrency, repeats, first_ms, gap_ms, max_seconds)
    deadline = time.monotonic() + max_seconds
    origin_ns = time.monotonic_ns()
    report = {
        "report_version": "1.0", "synthetic": True,
        "evidence_level": "measured_loopback_fixture_transport",
        "purpose": "client connection reuse and SSE instrumentation readiness",
        "platform_path_exercised": False,
        "components_not_exercised": ["Go admission", "Redis", "MySQL ledger",
                                     "Higress", "SGLang", "GPU", "Vue"],
        "model_usage": None, "paid_model_calls": 0,
        "clock_scope": "one-client-process-monotonic-" + str(uuid.uuid4()),
        "input": {"requests_per_case": requests, "concurrencies": list(concurrencies),
                  "paired_repeats": repeats, "first_content_delay_ms": first_ms,
                  "next_content_gap_ms": gap_ms, "wall_limit_seconds": max_seconds},
        "cases": [],
        "limits": {"loopback_only": True, "no_user_endpoint_parameter": True,
                   "max_total_planned": requests * len(concurrencies) * 2 * repeats,
                   "no_retries": True},
        "interpretation": "exploratory fixture observations; never MaaS/GPU speedup or SLO acceptance",
    }
    for concurrency in concurrencies:
        for repeat in range(1, repeats + 1):
            order = ("fresh", "reuse") if repeat % 2 else ("reuse", "fresh")
            for variant in order:
                if time.monotonic() >= deadline:
                    break
                result = run_case(requests, concurrency, variant, deadline, origin_ns,
                                  first_ms, gap_ms)
                result.update(case_id=f"fixture-C{concurrency}-r{repeat}-{variant}",
                              replicate=repeat)
                report["cases"].append(result)
                print(json.dumps({key: result[key] for key in
                                  ("case_id", "sent", "succeeded", "accepted_tcp_connections")}),
                      flush=True)
                if not result["complete"]:
                    break
            if not report["cases"] or not report["cases"][-1]["complete"]:
                break
        if report["cases"] and not report["cases"][-1]["complete"]:
            break
    expected = len(concurrencies) * repeats * 2
    report["complete"] = len(report["cases"]) == expected and all(
        case["complete"] for case in report["cases"])
    report["total_sent"] = sum(case["sent"] for case in report["cases"])
    report["total_failed"] = sum(case["failed"] for case in report["cases"])
    report["all_fixture_processes_joined"] = all(
        case["cleanup"]["fixture_server_stopped_and_handlers_joined"]
        for case in report["cases"])
    return report


def write_report(report, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "transport-report.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")
    fields = ["case_id", "replicate", "variant", "concurrency", "sent", "succeeded",
              "failed", "unsent", "accepted_tcp_connections", "observed_fixture_success_rps",
              "ttft_p50_ms", "ttft_p95_ms", "e2e_p95_ms"]
    with (directory / "transport-cases.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for case in report["cases"]:
            row = {key: case[key] for key in fields if key in case}
            row.update(ttft_p50_ms=case["metrics"]["client_visible_ttft_ms"]["p50"],
                       ttft_p95_ms=case["metrics"]["client_visible_ttft_ms"]["p95"],
                       e2e_p95_ms=case["metrics"]["client_e2e_ms"]["p95"])
            writer.writerow(row)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        print("invalid local fixture arguments; values not echoed", file=sys.stderr)
        raise SystemExit(2)


def main():
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-seconds", type=float, default=90)
    args = parser.parse_args()
    try:
        report = run_lab(args.requests, args.concurrency, args.repeats,
                         max_seconds=args.max_seconds)
        digest = write_report(report, args.output_dir)
    except (OSError, ValueError, RuntimeError):
        print("local fixture lab failed; no endpoint or sensitive data echoed")
        return 2
    print(json.dumps({"complete": report["complete"], "total_sent": report["total_sent"],
                      "report_sha256": digest}), flush=True)
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
