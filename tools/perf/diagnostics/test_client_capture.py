"""Local HTTP/stream correctness, never a MaaS/model performance baseline."""
import contextlib
import http.server
import json
from pathlib import Path
import threading
import time
import unittest
import uuid
from client_capture import Events, CaptureRejected, capture, associate, validate_manifest

RID=str(uuid.uuid4())
ROLE=b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
EMPTY=b'data: {"choices":[{"delta":{"content":""}}]}\n\n'
USAGE=b'data: {"usage":{"total_tokens":9},"choices":[]}\n\n'
CONTENT='data: {"choices":[{"delta":{"content":"内容"}}]}\n\n'.encode()
DONE=b'data: [DONE]\n\n'

@contextlib.contextmanager
def server(mode):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length","0")))
            self.send_response(503 if mode=="reject" else 200)
            self.send_header("Content-Type","text/event-stream")
            self.send_header("X-Request-ID",RID);self.end_headers()
            try:
                if mode=="reject":
                    self.wfile.write(b"SECRET_RESPONSE_SENTINEL");return
                for frame in (ROLE,EMPTY,USAGE):
                    self.wfile.write(frame);self.wfile.flush()
                if mode=="timeout":
                    time.sleep(1.2);return
                if mode=="error":
                    self.wfile.write(b'event: error\ndata: {"error":{"message":"SECRET_ERROR_SENTINEL"}}\n\n');self.wfile.flush();return
                if mode=="eof":return
                time.sleep(.015)
                for octet in CONTENT:
                    self.wfile.write(bytes([octet]));self.wfile.flush()
                if mode=="error_after":
                    self.wfile.write(b'event: error\ndata: {"error":{"message":"SECRET_AFTER_SENTINEL"}}\n\n');self.wfile.flush();return
                if mode=="finish_only":
                    self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n');self.wfile.flush();return
                if mode!="cancel":
                    self.wfile.write(DONE);self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError):pass
    svc=http.server.ThreadingHTTPServer(("127.0.0.1",0),Handler)
    svc.daemon_threads=False
    thread=threading.Thread(target=svc.serve_forever,kwargs={"poll_interval":.01})
    thread.start()
    try:yield f"http://127.0.0.1:{svc.server_port}/v1/chat/completions"
    finally:svc.shutdown();svc.server_close();thread.join()

def manifest(url):
    return {"schema":"client-stream-plan-1.0","run_id":"client-controlled","evidence_kind":"controlled_loopback",
        "protected_url":url,"execution_enabled":True,"approval_ref":"controlled-test",
        "source_ref":"loopback-test-only","timeout_seconds":1,"max_response_bytes":65536,"max_event_bytes":4096}

class ClientTests(unittest.TestCase):
    def observe(self,mode,stop=False):
        with server(mode) as url:
            row=capture(manifest(url),{"stream":True,"model":"controlled-test","messages":[{"role":"user","content":"SECRET_PROMPT_SENTINEL"}]},
                        "controlled-test",auth_key="SECRET_KEY_SENTINEL",stop_after_content=stop)
        self.assertNotIn("SECRET",json.dumps(row))
        return row
    def test_real_http_empty_role_usage_not_first_content(self):
        r=self.observe("content")
        self.assertEqual(r["termination"],"done_observed")
        self.assertEqual(r["content_events"],1)
        self.assertGreaterEqual(r["first_content_received_ms"],r["first_protocol_data_ms"])
        self.assertEqual(r["request_id"],RID)
        self.assertIsNone(r["actual_tokens"])
    def test_error_after_protocol_stops_without_content(self):
        r=self.observe("error");self.assertEqual(r["termination"],"error_event");self.assertIsNone(r["first_content_received_ms"])
    def test_error_after_content_is_not_success(self):
        r=self.observe("error_after");self.assertEqual(r["termination"],"error_event");self.assertIsNotNone(r["first_content_received_ms"])
    def test_finish_reason_without_done_is_not_terminal(self):
        r=self.observe("finish_only");self.assertEqual(r["termination"],"eof_without_done");self.assertIsNone(r["business_terminal_result"])
    def test_eof_not_successful_done(self):
        self.assertEqual(self.observe("eof")["termination"],"eof_without_done")
    def test_http_refusal_remains_attempt(self):
        r=self.observe("reject");self.assertEqual(r["termination"],"http_rejected");self.assertTrue(r["dispatch_attempted"])
    def test_timeout_keeps_no_content_and_elapsed(self):
        r=self.observe("timeout");self.assertEqual(r["termination"],"timeout");self.assertIsNone(r["first_content_received_ms"])
    def test_stop_after_content_does_not_claim_server_cancel_ack(self):
        r=self.observe("cancel",True);self.assertEqual(r["termination"],"client_stopped_after_content");self.assertIsNone(r["business_terminal_result"])
    def test_disabled_manifest_sends_nothing(self):
        m=manifest("http://127.0.0.1:1/a");m["execution_enabled"]=False
        with self.assertRaises(CaptureRejected):capture(m,{"stream":True},"controlled-test")
    def test_wrong_approval_rejected(self):
        with self.assertRaises(CaptureRejected):capture(manifest("http://127.0.0.1:1/a"),{"stream":True},"wrong")
    def test_loopback_manifest_cannot_target_remote(self):
        with self.assertRaises(CaptureRejected):validate_manifest(manifest("https://example.com/a"))
    def test_nonfinite_body_rejected_before_network(self):
        with self.assertRaises(ValueError):capture(manifest("http://127.0.0.1:1/a"),{"stream":True,"temperature":float("nan")},"controlled-test")
    def test_association_rejects_bad_client_clock_values(self):
        c={"schema":"client-stream-source-1.0","request_id":RID,"run_id":"r","attempt_id":"a","client_clock_scope":"c","first_protocol_data_ms":1,"first_content_received_ms":float("nan")}
        g={"schema_version":"maas-go-relay-source-1.0","request_id":RID,"run_id":"r"}
        with self.assertRaises(CaptureRejected):associate(c,g)
    def test_cross_run_association_rejected(self):
        c={"schema":"client-stream-source-1.0","request_id":RID,"run_id":"r","attempt_id":"a","client_clock_scope":"c"}
        g={"schema_version":"maas-go-relay-source-1.0","request_id":RID,"run_id":"other"}
        with self.assertRaises(CaptureRejected):associate(c,g)
    def test_go_nonfinite_clock_rejected(self):
        inst=str(uuid.uuid4());boot=str(uuid.uuid4())
        c={"schema":"client-stream-source-1.0","request_id":RID,"run_id":"r","attempt_id":"a","client_clock_scope":"c","first_protocol_data_ms":1,"first_content_received_ms":2}
        g={"schema_version":"maas-go-relay-source-1.0","request_id":RID,"run_id":"r","instance_id":inst,"boot_id":boot,"clock_scope":inst+"/"+boot+"/"+RID,"first_content_received_ms":float("nan")}
        with self.assertRaises(CaptureRejected):associate(c,g)
    def test_multiple_small_events_not_total_buffer_bound(self):
        p=Events(32);self.assertEqual(len(p.feed(b"data: {}\n\n"*8)),8)
    def test_oversized_or_partial_frames_rejected(self):
        with self.assertRaises(CaptureRejected):Events(10).feed(b"data: "+b"x"*20)
        p=Events(30);p.feed(b"data: {}")
        with self.assertRaises(CaptureRejected):p.finish()
    def test_association_does_not_merge_clocks_or_invent_trace(self):
        c={"schema":"client-stream-source-1.0","request_id":RID,"run_id":"r","attempt_id":"a","client_clock_scope":"client",
           "first_protocol_data_ms":1,"first_content_received_ms":5}
        inst=str(uuid.uuid4());boot=str(uuid.uuid4())
        g={"schema_version":"maas-go-relay-source-1.0","request_id":RID,"run_id":"r",
           "instance_id":inst,"boot_id":boot,"clock_scope":inst+"/"+boot+"/"+RID,"first_content_received_ms":2}
        r=associate(c,g);self.assertIsNone(r["cross_clock_latency_ms"]);self.assertFalse(r["d1_overall_complete"])
        g["request_id"]=str(uuid.uuid4())
        with self.assertRaises(CaptureRejected):associate(c,g)

if __name__=="__main__":unittest.main()
