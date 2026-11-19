import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
import unittest
from event_stream import probe

@contextlib.contextmanager
def server(callback):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:callback(self)
            except (BrokenPipeError,ConnectionResetError):pass
        def log_message(self,*args):pass
    httpd=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    httpd.daemon_threads=False
    thread=threading.Thread(target=httpd.serve_forever,kwargs={"poll_interval":0.01})
    thread.start()
    try:yield "http://127.0.0.1:"+str(httpd.server_port)+"/explicit-test-events"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()

def sse(h):
    h.send_response(200)
    h.send_header("Content-Type","text/event-stream; charset=utf-8")
    h.end_headers()

class StreamTransportTest(unittest.TestCase):
    def test_incremental_heartbeat_frames_and_redaction(self):
        def send(h):
            sse(h)
            h.wfile.write(b": heartbeat\n\nid: private-id\ndata: private-message\n\n")
            h.wfile.flush()
            time.sleep(0.08)
            h.wfile.write(b"data: private-tool-result\n\n")
            h.wfile.flush()
        with server(send) as url:
            r=probe(url)
        self.assertTrue(r["passed"])
        self.assertEqual((r["events"],r["comments"]),(2,1))
        self.assertLess(r["firstRecordMs"],r["elapsedMs"])
        self.assertNotIn("private",json.dumps(r))

    def test_multiline_data_is_one_event(self):
        def send(h):
            sse(h);h.wfile.write(b"data: first\r\ndata: second\r\n\r\ndata: third\n\n")
        with server(send) as url:r=probe(url)
        self.assertEqual(r["events"],2)
        self.assertTrue(r["passed"])

    def test_cursor_sent_as_header_get_only(self):
        observed=[]
        def send(h):
            observed.append((h.command,h.headers.get("Last-Event-ID"),h.headers.get("Cookie")))
            sse(h);h.wfile.write(b"data: replay\n\n")
        with server(send) as url:r=probe(url,{"Cookie":"private-cookie"},cursor="cursor-7",events=1)
        self.assertTrue(r["passed"])
        self.assertEqual(observed,[("GET","cursor-7","private-cookie")])
        self.assertNotIn("private-cookie",json.dumps(r))

    def test_unauthorized_and_redirect_not_followed(self):
        for status in (401,302):
            count=[]
            def send(h):
                count.append(1);h.send_response(status);h.send_header("Location","http://example.invalid");h.end_headers();h.wfile.write(b"private-server-error")
            with server(send) as url:r=probe(url)
            self.assertFalse(r["passed"])
            self.assertEqual(r["reason"],"http_rejected")
            self.assertEqual(len(count),1)
            self.assertNotIn("private",json.dumps(r))

    def test_json_not_event_stream(self):
        def send(h):
            h.send_response(200);h.send_header("Content-Type","application/json");h.end_headers()
        with server(send) as url:r=probe(url)
        self.assertEqual(r["reason"],"invalid_event_stream")

    def test_eof_not_completion(self):
        def send(h):sse(h);h.wfile.write(b"data: partial")
        with server(send) as url:r=probe(url,events=1)
        self.assertFalse(r["passed"]);self.assertEqual(r["events"],0)

    def test_stalled_stream_timeout(self):
        def send(h):sse(h);h.wfile.flush();time.sleep(0.12)
        with server(send) as url:r=probe(url,idle_ms=30)
        self.assertFalse(r["passed"]);self.assertEqual(r["reason"],"stream_timeout")

    def test_byte_and_line_bounds(self):
        def send(h):sse(h);h.wfile.write(b"x"*6000+b"\n")
        with server(send) as url:r=probe(url,max_bytes=50)
        self.assertEqual(r["reason"],"byte_limit")
        with server(send) as url:r=probe(url)
        self.assertEqual(r["reason"],"line_limit")

    def test_heartbeats_do_not_extend_observation_forever(self):
        def send(h):
            sse(h)
            for _ in range(30):
                h.wfile.write(b": heartbeat\n\n");h.wfile.flush();time.sleep(0.01)
        with server(send) as url:r=probe(url,idle_ms=100,observe_ms=50)
        self.assertFalse(r["passed"])
        self.assertIn(r["reason"],("observation_timeout","stream_timeout"))
        self.assertLess(r["elapsedMs"],500)

    def test_invalid_unicode_header_error_redacted(self):
        with server(lambda h: None) as url:
            result=probe(url,{"Cookie":"secret-"+chr(0x4e2d)})
        self.assertFalse(result["passed"])
        self.assertNotIn("secret",json.dumps(result))

    def test_probe_closes_http10_stream_after_bound(self):
        closed=threading.Event()
        def send(h):
            sse(h);h.wfile.write(b"data: only-frame\n\n");h.wfile.flush()
            h.connection.settimeout(0.5)
            if h.connection.recv(1)==b"":closed.set()
        with server(send) as url:
            r=probe(url,events=1)
            self.assertTrue(r["passed"])
            self.assertTrue(closed.wait(0.8),"probe left detached response socket open")

    def test_reject_external_targets_and_header_injection(self):
        for url in ("http://example.invalid/events","http://192.0.2.1/events","http://user:secret@127.0.0.1/events","https://127.0.0.1/events"):
            self.assertFalse(probe(url)["passed"])
        self.assertFalse(probe("http://127.0.0.1",{"Host":"other"})["passed"])
        self.assertFalse(probe("http://127.0.0.1",cursor="x\nsecret")["passed"])