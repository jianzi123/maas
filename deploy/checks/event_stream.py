"""Bounded GET-only loopback SSE probe. Reports metadata, never event bodies/credentials."""
import argparse
import http.client
import ipaddress
import json
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit

ALLOWED_HEADERS = {"authorization", "cookie", "origin"}
def probe(url, headers=None, cursor=None, events=2, idle_ms=1000, observe_ms=5000, max_bytes=65536):
    result = {"scope":"loopback-SSE-transport-only", "passed":False, "reason":"invalid_input",
              "events":0, "comments":0, "bytes":0, "firstRecordMs":None}
    conn = None
    response = None
    try:
        target = urlsplit(url)
        ip = ipaddress.ip_address(target.hostname or "")
        if target.scheme != "http" or not ip.is_loopback or target.username or target.password or target.fragment:
            return result
        if not 1 <= events <= 100 or not 1 <= idle_ms <= 10000 or not 1 <= observe_ms <= 60000 or not 1 <= max_bytes <= 1048576:
            return result
        supplied = headers or {}
        if any(k.lower() not in ALLOWED_HEADERS or not isinstance(v,str) or "\r" in v or "\n" in v for k,v in supplied.items()):
            return result
        if cursor is not None and (not isinstance(cursor,str) or len(cursor)>4096 or any(c in cursor for c in ("\r","\n","\x00"))):
            return result
        request_headers = {**supplied, "Accept":"text/event-stream", "Accept-Encoding":"identity", "Cache-Control":"no-cache"}
        if cursor is not None:
            request_headers["Last-Event-ID"] = cursor
        result["cursorSent"] = cursor is not None
        conn = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=idle_ms/1000)
        conn.connect()
        sock = conn.sock
        conn.request("GET", (target.path or "/") + ("?" + target.query if target.query else ""), headers=request_headers)
        response = conn.getresponse()
        result["httpStatus"] = response.status
        if response.status != 200:
            result["reason"] = "http_rejected"
            return result
        if response.getheader("Content-Type","").split(";")[0].strip().lower() != "text/event-stream" or response.getheader("Content-Encoding","identity").lower() != "identity":
            result["reason"] = "invalid_event_stream"
            return result
        started = time.monotonic()
        deadline = started + observe_ms/1000
        line = bytearray()
        has_data = False
        while result["bytes"] < max_bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result["reason"] = "observation_timeout"
                break
            sock.settimeout(min(idle_ms/1000, remaining))
            try:
                byte = response.read(1)
            except (TimeoutError, socket.timeout):
                result["reason"] = "stream_timeout"
                break
            if not byte:
                result["reason"] = "eof_before_required_events"
                break
            result["bytes"] += 1
            if byte != b"\n":
                line.extend(byte)
                if len(line)>4096:
                    result["reason"] = "line_limit"
                    break
                continue
            value = bytes(line).rstrip(b"\r")
            line.clear()
            if result["firstRecordMs"] is None:
                result["firstRecordMs"] = round((time.monotonic()-started)*1000,3)
            if value.startswith(b":"):
                result["comments"] += 1
            elif value == b"":
                if has_data:
                    result["events"] += 1
                    has_data = False
                    if result["events"] >= events:
                        result.update(passed=True,reason="required_events_received")
                        break
            elif value == b"data" or value.startswith(b"data:"):
                has_data = True
        else:
            result["reason"] = "byte_limit"
        result["elapsedMs"] = round((time.monotonic()-started)*1000,3)
    except (ValueError, TypeError, UnicodeError, OSError, http.client.HTTPException):
        result["reason"] = "transport_unavailable"
    finally:
        if response is not None:
            response.close()
        if conn is not None:
            conn.close()
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url",required=True)
    p.add_argument("--headers-file",type=Path,help="Existing local secret file; JSON Cookie/Authorization/Origin only. Never logged.")
    p.add_argument("--cursor")
    p.add_argument("--events",type=int,default=2)
    p.add_argument("--idle-ms",type=int,default=1000)
    p.add_argument("--observe-ms",type=int,default=5000)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    try:
        headers=json.loads(a.headers_file.read_text(encoding="utf-8")) if a.headers_file else {}
        if not isinstance(headers,dict):raise ValueError()
        result=probe(a.url,headers,a.cursor,a.events,a.idle_ms,a.observe_ms)
    except (ValueError,OSError):
        result={"scope":"loopback-SSE-transport-only","passed":False,"reason":"headers_unavailable"}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8",newline="\n")
    print(json.dumps(result))
    raise SystemExit(0 if result["passed"] else 1)
if __name__=="__main__":main()