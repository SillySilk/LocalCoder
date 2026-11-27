// bow-images: an MCP add-on that hands image downloading to AgentBow.
//
// AgentBow searches six image engines at once, skips small images and error
// pages, removes duplicates and can have a vision model check each picture.
// This add-on starts AgentBow when needed — headless, and pointed at the
// shared Engine Manager engine (BOW_ENGINE_URL) so it never starts a second
// copy of a model — then runs one download over its WebSocket.
//
// AgentBow exits after BOW_IDLE_SECS (default 120) with nothing to do, so it
// isn't left in memory; the next call starts it again (a few seconds' delay).
//
// Settings (environment): BOW_DIR (AgentBow folder), ENGINE_URL (shared engine),
// BOW_IDLE_SECS.

import { spawn } from "node:child_process";
import { readFileSync, existsSync, mkdirSync, copyFileSync, statSync, unlinkSync } from "node:fs";
import { join, basename, resolve } from "node:path";
import { tmpdir } from "node:os";
import { createInterface } from "node:readline";

const BOW_DIR = process.env.BOW_DIR || "C:\\AI\\Apps\\agent Bow";
const ENGINE_URL = process.env.ENGINE_URL || "http://127.0.0.1:8090";
// AgentBow shuts itself down after this many idle seconds (it restarts on the next call).
const IDLE_SECS = process.env.BOW_IDLE_SECS || "120";
const EXE = join(BOW_DIR, "desktop", "src-tauri", "target", "debug", "bow-desktop.exe");

function bowEnv() {
  const env = {};
  const file = join(BOW_DIR, "desktop", ".env");
  if (existsSync(file)) {
    for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)\s*$/);
      if (m) env[m[1]] = m[2].replace(/^"(.*)"$/, "$1").replace(/\\\\/g, "\\");
    }
  }
  return env;
}

const cfg = bowEnv();
// AgentBow falls back to another port when its usual one is busy; it writes
// the port it actually got to this file.
const PORT_FILE = join(tmpdir(), "bow-images.port");
let port = Number(cfg.BOW_WS_PORT || 9357);
const WORKSPACE = cfg.BOW_WORKSPACE || "C:\\AI\\workspace";

async function healthy(p) {
  try {
    const r = await fetch(`http://127.0.0.1:${p}/api/health`, { signal: AbortSignal.timeout(2000) });
    return r.ok;
  } catch { return false; }
}

async function bowUp() {
  const candidates = [port];
  try { candidates.unshift(Number(readFileSync(PORT_FILE, "utf8").trim())); } catch {}
  for (const p of candidates) {
    if (p && await healthy(p)) { port = p; return true; }
  }
  return false;
}

async function ensureBow() {
  if (await bowUp()) return;
  try { unlinkSync(PORT_FILE); } catch {}
  if (!existsSync(EXE)) throw new Error(`AgentBow is not built yet (${EXE}). Run bow.bat once.`);
  const child = spawn(EXE, [], {
    cwd: join(BOW_DIR, "desktop", "src-tauri", "target", "debug"),
    env: { ...process.env, BOW_ENGINE_URL: ENGINE_URL, BOW_NO_BROWSER: "1", BOW_IDLE_EXIT_SECS: IDLE_SECS, BOW_PORT_FILE: PORT_FILE },
    detached: true, stdio: "ignore", windowsHide: true,
  });
  let spawnError = null;
  child.on("error", (e) => { spawnError = e; });
  child.unref();
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 500));
    if (spawnError) throw new Error(`AgentBow could not start: ${spawnError.message}`);
    if (await bowUp()) return;
  }
  throw new Error("AgentBow did not start within 30 seconds.");
}

function slug(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 60) || "images";
}

async function download({ query, count = 10, dest_dir, verify = false, min_side = 512, delay_ms = 1500, sources }) {
  if (!query) throw new Error("query is required");
  await ensureBow();
  // AgentBow only writes inside its workspace; download there, then copy out.
  const staging = join(WORKSPACE, "bow-images", slug(query));
  mkdirSync(staging, { recursive: true });

  const ws = new WebSocket(`ws://127.0.0.1:${port}/ws`);
  const log = [];
  const result = await new Promise((resolveP, rejectP) => {
    const timer = setTimeout(() => { ws.close(); rejectP(new Error("download timed out after 20 minutes")); }, 20 * 60 * 1000);
    ws.onerror = () => { clearTimeout(timer); rejectP(new Error("could not connect to AgentBow")); };
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: cfg.BOW_SECRET || "", session_id: "bow-images" }));
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "auth_ok") {
        ws.send(JSON.stringify({
          type: "scrape_request", query, count, dest_dir: staging, verify, min_side, delay_ms,
          dedupe: true, ...(sources ? { sources } : {}),
        }));
      } else if (m.type === "auth_error") {
        clearTimeout(timer); ws.close(); rejectP(new Error("AgentBow rejected the login (BOW_SECRET)"));
      } else if (m.type === "error") {
        clearTimeout(timer); ws.close(); rejectP(new Error(m.message || m.code));
      } else if (m.type === "scrape_event") {
        if (m.kind === "source") log.push(`${m.source}: ${m.count} found${m.error ? ` (${m.error})` : ""}`);
        if (m.kind === "candidates") log.push(`candidates: ${m.total} (filtered ${m.filtered})`);
        if (m.kind === "failed") log.push(`skipped: ${m.reason}`);
        if (m.kind === "error") { clearTimeout(timer); ws.close(); rejectP(new Error(m.message)); }
        if (m.kind === "done") { clearTimeout(timer); ws.close(); resolveP(m); }
      }
    };
  });

  let saved = result.downloaded || [];
  if (dest_dir) {
    const out = resolve(dest_dir);
    mkdirSync(out, { recursive: true });
    saved = saved.map((p) => { const to = join(out, basename(p)); copyFileSync(p, to); return to; });
  }
  const sizes = saved.map((p) => `${p} (${Math.round(statSync(p).size / 1024)} KB)`);
  const skipped = log.filter((l) => l.startsWith("skipped")).length;
  return [
    `Saved ${saved.length} of ${count} images for "${query}"${dest_dir ? ` to ${dest_dir}` : ""}.`,
    ...sizes,
    "",
    ...log.filter((l) => !l.startsWith("skipped")),
    skipped ? `${skipped} candidates skipped (too small, not an image, duplicate${verify ? ", or rejected by the vision check" : ""}).` : "",
  ].join("\n");
}

const TOOLS = [{
  name: "image_download",
  description:
    "Find and download images of a subject from six image search engines (Bing, DuckDuckGo, Yandex, Brave, Qwant, SearXNG). " +
    "Skips small images, error pages and duplicates. Use this instead of hand-written download scripts when you need " +
    "N pictures of a person, character, object or style. Call once per subject. Set verify=true to have the vision " +
    "model reject pictures that don't match (slower; needs a vision model loaded).",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", description: "What to search for, e.g. \"Florence Henderson Carol Brady 1970s\"" },
      count: { type: "integer", minimum: 1, maximum: 200, default: 10 },
      dest_dir: { type: "string", description: "Folder to copy the images into (created if missing)" },
      verify: { type: "boolean", default: false },
      min_side: { type: "integer", default: 512, description: "Skip images whose shorter side is below this (pixels)" },
      delay_ms: { type: "integer", default: 1500, description: "Pause between downloads" },
      sources: { type: "array", items: { type: "string" }, description: "Limit to these engines, e.g. [\"bing\",\"duckduckgo\"]" },
    },
    required: ["query"],
  },
}];

function reply(id, result) { process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id, result }) + "\n"); }
function fail(id, message) { process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id, error: { code: -32603, message } }) + "\n"); }

createInterface({ input: process.stdin }).on("line", async (line) => {
  let msg;
  try { msg = JSON.parse(line); } catch { return; }
  const { id, method, params } = msg;
  if (method === "initialize") {
    reply(id, {
      protocolVersion: params?.protocolVersion || "2024-11-05",
      capabilities: { tools: {} },
      serverInfo: { name: "bow-images", version: "1.0.0" },
    });
  } else if (method === "tools/list") {
    reply(id, { tools: TOOLS });
  } else if (method === "tools/call") {
    try {
      const text = await download(params?.arguments || {});
      reply(id, { content: [{ type: "text", text }] });
    } catch (e) {
      reply(id, { content: [{ type: "text", text: `image_download failed: ${e.message}` }], isError: true });
    }
  } else if (method === "ping") {
    reply(id, {});
  } else if (id !== undefined) {
    fail(id, `unknown method ${method}`);
  }
});
