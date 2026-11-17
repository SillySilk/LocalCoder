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
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 11435
UPSTREAM = urlsplit(sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:11434")
DEBUG_LOG = os.environ.get("LC_RELAY_LOG")  # optional: record requests/responses here
_start_lock = threading.Lock()


def _open_upstream(method, path, body, headers):
    """Send the request to Ollama. If Ollama isn't running (stopped, or being
    restarted by Model Manager), start it and try once more."""
    for attempt in (1, 2):
        conn = http.client.HTTPConnection(UPSTREAM.hostname, UPSTREAM.port or 80, timeout=1800)
        try:
            conn.request(method, path, body=body, headers=headers)
            return conn, conn.getresponse()
        except ConnectionRefusedError:
            conn.close()
            if attempt == 2:
                raise
            with _start_lock:
                try:
                    from lc_ollama import start_ollama
                    start_ollama()
                except SystemExit:  # start_ollama gives up this way
                    raise ConnectionRefusedError("Ollama did not start") from None


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
        try:
            conn, resp = _open_upstream(self.command, self.path, body, headers)
        except ConnectionRefusedError:
            # A real reply instead of a dropped connection: Claude Code shows the
            # message and retries, rather than reporting a network failure.
            msg = json.dumps({"type": "error", "error": {
                "type": "api_error",
                "message": "Ollama is not running and could not be started. "
                           "Open the Ollama app, then try again."}}).encode()
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
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


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Relay).serve_forever()
