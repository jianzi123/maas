"""Bounded client-side SSE observations; source record, never accounting evidence.

Use HTTP read1, timestamps on received bytes, no content/token or credential export.
Real execution requires an explicit enabled approval manifest and matching CLI ref.
"""
import argparse
import codecs
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import socket
import time
from urllib.parse import urlsplit
import uuid

class CaptureRejected(ValueError):
    pass


def validate_manifest(m):
    required={"schema","run_id","evidence_kind","protected_url","execution_enabled","approval_ref",
              "source_ref","timeout_seconds","max_response_bytes","max_event_bytes"}
    if not isinstance(m,dict) or set(m)!=required or m["schema"]!="client-stream-plan-1.0":
        raise CaptureRejected("manifest fields/version")
    if m["evidence_kind"] not in ("controlled_loopback","protected_endpoint_unverified"):
        raise CaptureRejected("source kind")
    u=urlsplit(m["protected_url"])
    if u.scheme not in ("http","https") or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise CaptureRejected("endpoint shape")
    if m["evidence_kind"]=="controlled_loopback" and u.hostname not in ("127.0.0.1","::1"):
        raise CaptureRejected("loopback required")
    if not isinstance(m["execution_enabled"],bool) or not isinstance(m["approval_ref"],str):
        raise CaptureRejected("approval shape")
    for key in ("run_id","source_ref"):
        if not isinstance(m[key],str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}",m[key]):
            raise CaptureRejected("source identity")
    for key,maximum in (("timeout_seconds",60),("max_response_bytes",1048576),("max_event_bytes",65536)):
        if type(m[key]) is not int or not 0<m[key]<=maximum:
            raise CaptureRejected("bound")
    return m


class Events:
    """Incremental UTF8 + CRLF/LF SSE parser; data lines compose one event."""
    def __init__(self,max_event):
        self.decoder=codecs.getincrementaldecoder("utf-8")("strict")
        self.text="";self.data=[];self.event="message";self.size=0;self.maximum=max_event
    def feed(self,chunk):
        self.text+=self.decoder.decode(chunk)
        result=[]
        while "\n" in self.text:
            line,self.text=self.text.split("\n",1);line=line.removesuffix("\r")
            self.size+=len(line.encode("utf-8"))+1
            if self.size>self.maximum:raise CaptureRejected("event bound")
            if line=="":
                if self.data:result.append((self.event,"\n".join(self.data)))
                self.data=[];self.event="message";self.size=0
            elif not line.startswith(":"):
                key,sep,value=line.partition(":")
                if sep and value.startswith(" "):value=value[1:]
                if key=="data":self.data.append(value)
                elif key=="event":self.event=value
        if len(self.text.encode("utf-8"))+self.size>self.maximum:
            raise CaptureRejected("unterminated event bound")
        return result
    def finish(self):
        self.decoder.decode(b"",final=True)
        if self.text or self.data:raise CaptureRejected("incomplete SSE event")


def canonical_uuid(value):
    try:return isinstance(value,str) and str(uuid.UUID(value))==value
    except (ValueError,AttributeError):return False


def capture(manifest,body,approval_ref,auth_key=None,stop_after_content=False):
    m=validate_manifest(manifest)
    if not m["execution_enabled"] or not approval_ref or approval_ref!=m["approval_ref"]:
        raise CaptureRejected("execution approval missing/mismatched")
    if not isinstance(body,dict) or body.get("stream") is not True:
        raise CaptureRejected("streaming body required")
    encoded=json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
    if len(encoded)>65536:raise CaptureRejected("request bound")
    u=urlsplit(m["protected_url"])
    attempt=str(uuid.uuid4());scope=m["run_id"]+"/"+str(uuid.uuid4())
    start=time.perf_counter_ns();deadline=start+m["timeout_seconds"]*1_000_000_000
    row={"schema":"client-stream-source-1.0","run_id":m["run_id"],"attempt_id":attempt,
        "evidence_kind":m["evidence_kind"],"source_ref":m["source_ref"],
        "client_clock_scope":scope,"dispatch_attempted":True,"request_write_completed":None,"http_status":None,"request_id":None,
        "first_protocol_data_ms":None,"first_content_received_ms":None,"last_content_received_ms":None,
        "content_events":0,"data_events":0,"termination":None,"error_type":None,
        "elapsed_ms":None,"business_terminal_result":None,"actual_tokens":None,
        "server_clock_calibration":None,"server_instance_id":None,"server_boot_id":None,
        "trace_id":None,"invocation_binding":None,"worker_time_ms":None,
        "source_identity_verified":False,"model_bottleneck":None,
        "collector_source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    conn=(http.client.HTTPSConnection if u.scheme=="https" else http.client.HTTPConnection)(
        u.hostname,u.port,timeout=m["timeout_seconds"])
    parser=Events(m["max_event_bytes"]);total=0;response=None
    try:
        headers={"Content-Type":"application/json","Accept":"text/event-stream","Accept-Encoding":"identity",
                 "X-Client-Attempt-ID":attempt}
        if auth_key:headers["Authorization"]="Bearer "+auth_key
        conn.request("POST",u.path or "/",body=encoded,headers=headers)
        row["request_write_completed"]=True
        response=conn.getresponse();row["http_status"]=response.status
        rid=response.getheader("X-Request-ID")
        if canonical_uuid(rid):row["request_id"]=rid
        if response.status!=200:
            row["termination"]="http_rejected";return row
        if response.getheader("Content-Encoding","identity").lower()!="identity":
            raise CaptureRejected("unsupported content encoding")
        if response.getheader("Content-Type","").split(";",1)[0].strip().lower()!="text/event-stream":
            raise CaptureRejected("not SSE")
        while True:
            remaining=(deadline-time.perf_counter_ns())/1e9
            if remaining<=0:raise TimeoutError()
            sock=conn.sock or getattr(getattr(getattr(response,"fp",None),"raw",None),"_sock",None)
            if sock is None:raise CaptureRejected("deadline control unavailable")
            sock.settimeout(remaining)
            chunk=response.read1(4096)
            received=time.perf_counter_ns()
            if not chunk:
                parser.finish();row["termination"]="eof_without_done";break
            total+=len(chunk)
            if total>m["max_response_bytes"]:raise CaptureRejected("response bound")
            for event,data in parser.feed(chunk):
                ms=(received-start)/1e6
                row["data_events"]+=1
                if row["first_protocol_data_ms"] is None:row["first_protocol_data_ms"]=ms
                if event=="error":
                    row["termination"]="error_event";return row
                if data.strip()=="[DONE]":
                    row["termination"]="done_observed";return row
                try:value=json.loads(data)
                except json.JSONDecodeError:raise CaptureRejected("invalid SSE JSON")
                if not isinstance(value,dict):raise CaptureRejected("event object required")
                if value.get("error") is not None:
                    row["termination"]="error_event";return row
                choices=value.get("choices",[]) if isinstance(value,dict) else []
                if not isinstance(choices,list):raise CaptureRejected("choices shape")
                visible=False
                for choice in choices:
                    if not isinstance(choice,dict):raise CaptureRejected("choice shape")
                    delta=choice.get("delta",{})
                    if not isinstance(delta,dict):raise CaptureRejected("delta shape")
                    text=delta.get("content")
                    if text is not None and not isinstance(text,str):raise CaptureRejected("content shape")
                    visible|=isinstance(text,str) and text!=""
                if visible:
                    if row["first_content_received_ms"] is None:row["first_content_received_ms"]=ms
                    row["last_content_received_ms"]=ms;row["content_events"]+=1
                    if stop_after_content:
                        row["termination"]="client_stopped_after_content";return row
    except (TimeoutError,socket.timeout):
        row["termination"]="timeout";row["error_type"]="TimeoutError"
    except (OSError,http.client.HTTPException,UnicodeError,CaptureRejected):
        row["termination"]="transport_or_protocol_error";row["error_type"]="redacted_transport_or_protocol"
    finally:
        row["elapsed_ms"]=(time.perf_counter_ns()-start)/1e6
        if response is not None:response.close()
        conn.close()
    return row


def associate(client,go):
    """Only match actual request ID; keep two clocks and missing trace/binding explicit."""
    if client.get("schema")!="client-stream-source-1.0" or go.get("schema_version")!="maas-go-relay-source-1.0":
        raise CaptureRejected("source version")
    if not canonical_uuid(client.get("request_id")) or client["request_id"]!=go.get("request_id"):
        raise CaptureRejected("request association missing/mismatched")
    for k in ("client_clock_scope","run_id","attempt_id"):
        if not client.get(k):raise CaptureRejected("client identity")
    if client["run_id"]!=go.get("run_id"):raise CaptureRejected("source run mismatch")
    for field in ("first_protocol_data_ms","first_content_received_ms","last_content_received_ms","elapsed_ms"):
        value=client.get(field)
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):
            raise CaptureRejected("client time")
    first=client.get("first_content_received_ms")
    if first is not None and (client.get("first_protocol_data_ms") is None or first<client["first_protocol_data_ms"]):
        raise CaptureRejected("client content order")
    if not all(canonical_uuid(go.get(k)) for k in ("instance_id","boot_id","request_id")):
        raise CaptureRejected("Go UUID identity")
    required="/".join(go[k] for k in ("instance_id","boot_id","request_id"))
    if go.get("clock_scope")!=required:raise CaptureRejected("Go clock binding")
    times=("first_protocol_ms","first_content_received_ms","first_content_write_ok_ms","first_content_flush_attempt_ms","end_ms")
    for field in times:
        value=go.get(field)
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):
            raise CaptureRejected("Go time")
    content=go.get("first_content_received_ms")
    for field in ("first_content_write_ok_ms","first_content_flush_attempt_ms"):
        value=go.get(field)
        if value is not None and (content is None or value<content):
            raise CaptureRejected("Go write/flush order")

    return {"schema":"client-relay-association-1.0","request_id":client["request_id"],
        "association":"request_id_only_unverified","source_identity_verified":False,
        "client_clock_scope":client["client_clock_scope"],"go_clock_scope":go["clock_scope"],
        "client_first_protocol_data_ms":client["first_protocol_data_ms"],
        "client_first_content_received_ms":client["first_content_received_ms"],
        "go_first_content_received_ms":go.get("first_content_received_ms"),
        "go_first_content_write_ok_ms":go.get("first_content_write_ok_ms"),
        "go_first_content_flush_attempt_ms":go.get("first_content_flush_attempt_ms"),
        "cross_clock_latency_ms":None,"trace_id":None,"worker_time_ms":None,
        "model_bottleneck":None,"d1_overall_complete":False,
        "missing":["trusted_trace_and_binding","live_source_run_boot_attestation","worker/provider_observation","cross_clock_calibration"]}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest",type=Path,required=True)
    p.add_argument("--body-file",type=Path)
    p.add_argument("--output",type=Path)
    p.add_argument("--execute",action="store_true")
    p.add_argument("--approval-ref")
    p.add_argument("--key-env",help="explicit credential env name; never exported")
    p.add_argument("--stop-after-content",action="store_true")
    a=p.parse_args()
    m=validate_manifest(json.loads(a.manifest.read_text(encoding="utf-8")))
    if not a.execute:
        print(json.dumps({"validated":True,"execution_enabled":m["execution_enabled"],"request_sent":False}))
        return 0
    if not a.output or a.output.exists() or not a.body_file:raise CaptureRejected("fresh output/body required")
    key=os.environ.get(a.key_env) if a.key_env else None
    if a.key_env and not key:raise CaptureRejected("explicit key env unavailable")
    row=capture(m,json.loads(a.body_file.read_text(encoding="utf-8")),a.approval_ref,key,a.stop_after_content)
    with a.output.open("x",encoding="utf-8") as f:json.dump(row,f,indent=2,allow_nan=False);f.write("\n")
    print(json.dumps({"record_written":True,"request_id_observed":row["request_id"] is not None,
                      "termination":row["termination"],"content_events":row["content_events"]}))
    return 0


if __name__=="__main__":
    try:raise SystemExit(main())
    except (CaptureRejected,OSError,ValueError,KeyError,TypeError):
        print("Client capture rejected metadata/approval/output",file=__import__("sys").stderr)
        raise SystemExit(2)
