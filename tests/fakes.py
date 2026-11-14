"""Test helpers: a tiny fake Ollama server running in a background thread."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SSE_CHUNKS = [b"event: a\ndata: {\"n\":1}\n\n", b"event: b\ndata: {\"n\":2}\n\n",
              b"event: c\ndata: {\"n\":3}\n\n"]


class FakeOllama:
    """Answers /api/version, /api/tags, /api/show, /api/ps and streams /v1/messages.

    `models` maps name -> /api/show response; `ps` is the /api/ps response.
    Every POST body is recorded in `bodies` (path, parsed json).
    """

    def __init__(self, models=None, ps=None, version="0.40.16"):
        self.models = models or {}
        self.ps = ps or {"models": []}
        self.version = version
        self.bodies = []
        fake = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _json(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/api/version":
                    return self._json({"version": fake.version})
                if self.path == "/api/tags":
                    return self._json({"models": [{"name": n} for n in fake.models]})
                if self.path == "/api/ps":
                    return self._json(fake.ps)
                self._json({"error": "not found"}, 404)

            def do_POST(self):
                n = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(n)
                body = json.loads(raw) if raw else {}
                fake.bodies.append((self.path, body))
                if self.path == "/api/show":
                    m = fake.models.get(body.get("model"))
                    return self._json(m) if m else self._json({"error": "model not found"}, 404)
                if self.path.startswith("/v1/messages"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for c in SSE_CHUNKS:
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(c), c))
                        self.wfile.flush()
                    self.wfile.write(b"0\r\n\r\n")
                    return
                self._json({"status": "success"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def show(caps=("completion", "tools"), num_ctx=65536, max_ctx=262144, quant="Q4_K_M"):
    """Build an /api/show response."""
    params = f"num_ctx                        {num_ctx}" if num_ctx else ""
    return {"capabilities": list(caps), "parameters": params,
            "model_info": {"general.architecture": "qwen3", "qwen3.context_length": max_ctx},
            "details": {"quantization_level": quant, "parameter_size": "8B", "family": "qwen3"}}
