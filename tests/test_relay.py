import http.client
import json
import os
import socket
import sys
import threading
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import lc_launch  # noqa: E402
import lc_proxy  # noqa: E402
from fakes import SSE_CHUNKS, FakeOllama  # noqa: E402


class FoldTests(unittest.TestCase):
    def test_fold_moves_system_message_into_user_text(self):
        body = {"messages": [{"role": "user", "content": "hi"},
                             {"role": "system", "content": [{"type": "text", "text": "SKILLS"}]}]}
        out = lc_proxy.fold_system_messages(body)
        self.assertEqual([m["role"] for m in out["messages"]], ["user"])
        last = out["messages"][0]["content"][-1]["text"]
        self.assertIn("<system-reminder>", last)
        self.assertIn("SKILLS", last)

    def test_fold_leaves_plain_conversation_untouched(self):
        body = {"messages": [{"role": "user", "content": "hi"},
                             {"role": "assistant", "content": "yo"}]}
        self.assertEqual(lc_proxy.fold_system_messages(body), body)

    def test_fold_keeps_tool_result_first(self):
        body = {"messages": [
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
            {"role": "system", "content": "NOTE"}]}
        out = lc_proxy.fold_system_messages(body)
        user = out["messages"][-1]
        self.assertEqual(user["content"][0]["type"], "tool_result")
        self.assertIn("NOTE", user["content"][-1]["text"])


class RelayServerTests(unittest.TestCase):
    def setUp(self):
        self.up = FakeOllama()
        self.relay = lc_proxy.make_server(0, self.up.url)
        self.port = self.relay.server_address[1]
        threading.Thread(target=self.relay.serve_forever, daemon=True).start()

    def tearDown(self):
        self.relay.shutdown()
        self.relay.server_close()
        self.up.close()

    def test_relay_streams_and_rewrites(self):
        body = {"model": "m", "messages": [{"role": "user", "content": "hi"},
                                           {"role": "system", "content": "SKILLS"}]}
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/v1/messages?beta=true", body=json.dumps(body),
                  headers={"Content-Type": "application/json"})
        got = c.getresponse().read()
        path, seen = self.up.bodies[-1]
        self.assertTrue(path.startswith("/v1/messages"))
        self.assertNotIn("system", [m["role"] for m in seen["messages"]])
        self.assertEqual(got, b"".join(SSE_CHUNKS))


class StartRelayTests(unittest.TestCase):
    def test_start_relay_picks_free_port(self):
        up = FakeOllama()
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        taken = blocker.getsockname()[1]
        old = os.environ.get("LC_OLLAMA_URL")
        try:
            proc, port = lc_launch.start_relay(up.url)
            try:
                self.assertNotEqual(port, taken)
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=5) as r:
                    self.assertEqual(json.loads(r.read())["version"], "0.40.16")
            finally:
                proc.terminate()
                proc.wait(timeout=10)
                proc.stdout.close()
            self.assertIsNotNone(proc.returncode)
        finally:
            blocker.close()
            up.close()
            if old is not None:
                os.environ["LC_OLLAMA_URL"] = old


    def test_relay_exits_when_parent_is_gone(self):
        import subprocess
        import time
        up = FakeOllama()
        try:
            parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
            relay = subprocess.Popen([sys.executable, str(ROOT / "lc_proxy.py"), "0", up.url,
                                      "--parent", str(parent.pid)],
                                     stdout=subprocess.PIPE, text=True)
            self.assertTrue(relay.stdout.readline().startswith("PORT "))
            parent.wait()
            deadline = time.time() + 15
            while relay.poll() is None and time.time() < deadline:
                time.sleep(0.5)
            alive = relay.poll() is None
            if alive:
                relay.kill()
            relay.wait()
            relay.stdout.close()
            if alive:
                self.fail("relay kept running after its parent exited")
        finally:
            up.close()


if __name__ == "__main__":
    unittest.main()
