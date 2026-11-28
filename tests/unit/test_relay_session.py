"""Each George session gets its own relay on a free port (from the hardening work)."""

import http.client
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import lc_launch
import lc_proxy

SSE_CHUNKS = [b"event: a\ndata: {\"n\":1}\n\n", b"event: b\ndata: {\"n\":2}\n\n",
              b"event: c\ndata: {\"n\":3}\n\n"]


class FakeEngine:
    """Answers GET /v1/models and streams POST /v1/messages; records POST bodies."""

    def __init__(self):
        self.bodies = []
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                data = json.dumps({"data": [{"id": "m"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("content-length") or 0))
                fake.bodies.append((self.path, json.loads(raw) if raw else {}))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for c in SSE_CHUNKS:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(c), c))
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_fold_moves_system_message_into_user_text():
    body = {"messages": [{"role": "user", "content": "hi"},
                         {"role": "system", "content": [{"type": "text", "text": "SKILLS"}]}]}
    out = lc_proxy.fold_system_messages(body)
    assert [m["role"] for m in out["messages"]] == ["user"]
    last = out["messages"][0]["content"][-1]["text"]
    assert "<system-reminder>" in last and "SKILLS" in last


def test_fold_leaves_plain_conversation_untouched():
    body = {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]}
    assert lc_proxy.fold_system_messages(body) == body


def test_fold_keeps_tool_result_first():
    body = {"messages": [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        {"role": "system", "content": "NOTE"}]}
    user = lc_proxy.fold_system_messages(body)["messages"][-1]
    assert user["content"][0]["type"] == "tool_result"
    assert "NOTE" in user["content"][-1]["text"]


def test_relay_streams_and_rewrites():
    up = FakeEngine()
    relay = lc_proxy.make_server(0, up.url)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    try:
        body = {"model": "m", "messages": [{"role": "user", "content": "hi"},
                                           {"role": "system", "content": "SKILLS"}]}
        c = http.client.HTTPConnection("127.0.0.1", relay.server_address[1], timeout=10)
        c.request("POST", "/v1/messages?beta=true", body=json.dumps(body),
                  headers={"Content-Type": "application/json"})
        got = c.getresponse().read()
        path, seen = up.bodies[-1]
        assert path.startswith("/v1/messages")
        assert "system" not in [m["role"] for m in seen["messages"]]
        assert got == b"".join(SSE_CHUNKS)
    finally:
        relay.shutdown()
        relay.server_close()
        up.close()


def test_start_relay_picks_a_free_port_and_reaches_the_engine():
    up = FakeEngine()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    try:
        proc, port = lc_launch.start_relay(up.url)
        try:
            assert port != blocker.getsockname()[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=5) as r:
                assert json.loads(r.read())["data"][0]["id"] == "m"
        finally:
            proc.terminate()
            proc.wait(timeout=10)
            proc.stdout.close()
    finally:
        blocker.close()
        up.close()


def test_relay_exits_when_its_launcher_is_gone():
    up = FakeEngine()
    try:
        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
        relay = subprocess.Popen([sys.executable, str(lc_launch.ROOT / "lc_proxy.py"), "0", up.url,
                                  "--parent", str(parent.pid)], stdout=subprocess.PIPE, text=True)
        assert relay.stdout.readline().startswith("PORT ")
        parent.wait()
        deadline = time.time() + 15
        while relay.poll() is None and time.time() < deadline:
            time.sleep(0.5)
        alive = relay.poll() is None
        if alive:
            relay.kill()
        relay.wait()
        relay.stdout.close()
        assert not alive, "relay kept running after its launcher exited"
    finally:
        up.close()


def test_a_crashed_relay_is_restarted_on_the_same_port():
    up = FakeEngine()
    proc, port = lc_launch.start_relay(up.url)
    stop, current = lc_launch.keep_relay_running(proc, port, up.url, every=0.3)
    try:
        proc.kill()
        proc.wait()
        deadline = time.time() + 15
        while current[0] is proc and time.time() < deadline:
            time.sleep(0.2)
        assert current[0] is not proc, "relay was not restarted"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=5) as r:
            assert r.status == 200
    finally:
        stop.set()
        current[0].terminate()
        current[0].wait(timeout=10)
        up.close()


def test_relay_refuses_to_run_without_an_engine_address():
    r = subprocess.run([sys.executable, str(lc_launch.ROOT / "lc_proxy.py"), "0"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and "usage" in r.stderr
