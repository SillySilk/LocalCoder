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


def test_relay_answers_clearly_when_ollama_is_unreachable():
    # Nothing listens on 11497, and starting Ollama can't fix that, so the relay
    # must give a real error reply rather than dropping the connection.
    status, body = _post_through_relay(11496, "http://127.0.0.1:11497")
    assert status == 503
    assert b"Ollama is not running" in body
