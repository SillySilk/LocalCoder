"""LocalCoder relay between Claude Code and Ollama.

Claude Code sends some context (skill list, deferred tool names, SessionStart
hook output) as a role "system" message inside `messages`. Ollama's
Anthropic-compatible endpoint silently drops those, so the local model never
sees them. This relay rewrites each such message into a user-side
<system-reminder> text block, then forwards everything else to Ollama
untouched, streaming responses back as they arrive.

Usage: python lc_proxy.py [listen_port] [ollama_url]
"""

import http.client
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DEBUG_LOG = os.environ.get("LC_RELAY_LOG")  # optional: record requests/responses here
HOP = {"host", "content-length", "transfer-encoding", "connection", "keep-alive"}


def _text(block_or_str):
    if isinstance(block_or_str, str):
        return block_or_str
    return "\n".join(b.get("text", "") for b in block_or_str if b.get("type") == "text")


def _as_blocks(content):
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return list(content)


def fold_system_messages(body):
    """Turn in-conversation system messages into user text and merge neighbours."""
    msgs = body.get("messages")
    if not isinstance(msgs, list) or not any(m.get("role") == "system" for m in msgs):
        return body
    out = []
    for m in msgs:
        if m.get("role") == "system":
            text = _text(m.get("content", ""))
            m = {"role": "user",
                 "content": [{"type": "text", "text": f"<system-reminder>\n{text}\n</system-reminder>"}]}
        if out and out[-1]["role"] == m["role"] == "user":
            out[-1] = {**out[-1], "content": _as_blocks(out[-1]["content"]) + _as_blocks(m["content"])}
        else:
            out.append(m)
    return {**body, "messages": out}


class Relay(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream = urlsplit("http://127.0.0.1:11434")  # replaced per server by make_server

    def log_message(self, *args):
        pass

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass  # client closed an idle keep-alive connection

    def _relay(self):
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n) if n else None
        if body and self.path.startswith("/v1/messages"):
            try:
                body = json.dumps(fold_system_messages(json.loads(body))).encode()
            except ValueError:
                pass
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        if body is not None:
            headers["Content-Length"] = str(len(body))
        up = self.upstream
        conn = http.client.HTTPConnection(up.hostname, up.port or 80, timeout=1800)
        conn.request(self.command, self.path, body=body, headers=headers)
        resp = conn.getresponse()
        self.send_response(resp.status, resp.reason)
        for k, v in resp.getheaders():
            if k.lower() not in HOP:
                self.send_header(k, v)
        if self.command == "HEAD":
            self.send_header("Content-Length", "0")
            self.end_headers()
            conn.close()
            return
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        debug = open(DEBUG_LOG, "ab") if DEBUG_LOG and self.path.startswith("/v1/messages") else None
        if debug:
            debug.write(b"\n===REQUEST " + (body or b"") + b"\n===RESPONSE\n")
        while True:
            chunk = resp.read1(65536)
            if not chunk:
                break
            if debug:
                debug.write(chunk)
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.flush()
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        if debug:
            debug.close()
        conn.close()

    do_GET = do_POST = do_HEAD = do_DELETE = do_PUT = _relay


def make_server(port, upstream):
    """Relay on 127.0.0.1:<port> (0 = any free port) forwarding to `upstream`."""
    handler = type("BoundRelay", (Relay,), {"upstream": urlsplit(upstream)})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def parent_alive(pid):
    """True while process `pid` exists (no signals sent; safe on Windows)."""
    if sys.platform == "win32":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT = still running
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def watch_parent(pid, server, every=2.0):
    """Shut the relay down once the launcher that started it is gone."""
    import threading
    import time

    def loop():
        while parent_alive(pid):
            time.sleep(every)
        server.shutdown()
    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    args = sys.argv[1:]
    parent = None
    if "--parent" in args:
        i = args.index("--parent")
        parent = int(args[i + 1])
        del args[i:i + 2]
    port = int(args[0]) if args else 11435
    upstream = args[1] if len(args) > 1 else "http://127.0.0.1:11434"
    srv = make_server(port, upstream)
    print(f"PORT {srv.server_address[1]}", flush=True)
    if parent:
        watch_parent(parent, srv)
    srv.serve_forever()
