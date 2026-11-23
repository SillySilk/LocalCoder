import time

import lc_launch

PORT = 11499  # away from the real relay so a live George session isn't touched


def wait_for(cond, secs):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def test_relay_restarts_after_it_stops():
    stop = None
    try:
        assert lc_launch.ensure_relay(PORT)
        stop = lc_launch.watch_relay(PORT, every=0.5)
        lc_launch.started_relays[-1].kill()
        assert wait_for(lambda: len(lc_launch.started_relays) >= 2, 10), "relay was not restarted"
        assert wait_for(lambda: lc_launch.relay_up(PORT), 20), "restarted relay isn't answering"
        assert lc_launch.started_relays[0].poll() is not None  # the first one really died
    finally:
        if stop:
            stop.set()
            time.sleep(1)  # let the watcher finish any restart it began
        for p in lc_launch.started_relays:
            p.kill()


def _post_through_relay(port, upstream):
    import json
    import subprocess
    import sys
    import urllib.error
    import urllib.request
    proc = subprocess.Popen([sys.executable, str(lc_launch.ROOT / "lc_proxy.py"), str(port), upstream],
                            stderr=subprocess.DEVNULL)
    try:
        assert wait_for(lambda: lc_launch.relay_up(port), 10)
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/messages", method="POST",
            data=json.dumps({"model": "x", "max_tokens": 5,
                             "messages": [{"role": "user", "content": "hi"}]}).encode(),
            headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
    finally:
        proc.kill()


def test_relay_answers_clearly_when_engine_is_unreachable():
    # Nothing listens on 11497, and starting the engine can't fix that (it
    # listens elsewhere), so the relay must give a real error reply rather than
    # dropping the connection.
    status, body = _post_through_relay(11496, "http://127.0.0.1:11497")
    assert status == 503
    assert b"engine is not running" in body


def _fake_engine(port, status, body):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length") or 0))
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _logged_request(tmp_path, status, body):
    import os
    import subprocess
    import sys
    import urllib.error
    import urllib.request
    log = tmp_path / "relay.log"
    srv = _fake_engine(11493, status, body)
    proc = subprocess.Popen([sys.executable, str(lc_launch.ROOT / "lc_proxy.py"), "11494",
                             "http://127.0.0.1:11493"], stderr=subprocess.DEVNULL,
                            env={**os.environ, "LC_RELAY_EVENTS": str(log)})
    try:
        assert wait_for(lambda: lc_launch.relay_up(11494), 10)
        req = urllib.request.Request(
            "http://127.0.0.1:11494/v1/messages", method="POST",
            data=b'{"model": "m1", "messages": [{"role": "user", "content": "hi"}]}')
        try:
            urllib.request.urlopen(req, timeout=30).read()
        except urllib.error.HTTPError as e:
            e.read()
        assert wait_for(lambda: log.exists() and "done status" in log.read_text(), 10)
        return log.read_text()
    finally:
        proc.kill()
        srv.shutdown()


def test_relay_log_records_each_request(tmp_path):
    text = _logged_request(tmp_path, 200, b'{"ok": true}')
    assert "relay started on port 11494" in text
    assert "start POST /v1/messages model=m1 messages=1" in text
    assert "first reply after" in text
    assert "done status 200" in text


def test_relay_log_records_engine_errors(tmp_path):
    text = _logged_request(tmp_path, 500, b'{"error": "model ran out of memory"}')
    assert "done status 500" in text
    assert "model ran out of memory" in text
