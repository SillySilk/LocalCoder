// bow-images: an MCP add-on that hands image downloading to AgentBow.
//
// AgentBow searches four image engines at once, skips small images and error
// pages, removes duplicates and can have a vision model check each picture.
// This add-on starts AgentBow when needed — headless, and pointed at the
// shared Engine Manager engine (BOW_ENGINE_URL) so it never starts a second
// copy of a model — then runs one download over its WebSocket.
//
// AgentBow exits after BOW_IDLE_SECS with nothing to do, so it isn't left in
// memory; the next call starts it again (about 20 seconds).
//
// Settings (environment, all required): BOW_DIR (AgentBow folder), ENGINE_URL
// (shared engine), BOW_IDLE_SECS. AgentBow's own desktop\.env supplies its
// port, workspace and login secret.

import { spawn } from "node:child_process";
import { readFileSync, existsSync, mkdirSync, copyFileSync, statSync, unlinkSync, openSync, closeSync } from "node:fs";
import { join, basename, resolve } from "node:path";
import { tmpdir } from "node:os";
import { createInterface } from "node:readline";

// A missing setting is reported, never guessed.
function required(value, name) {
  if (value === undefined || value === "") throw new Error(`bow-images: ${name} is not set`);
  return value;
}

function bowEnv(dir) {
  const env = {};
  const file = join(dir, "desktop", ".env");
  if (!existsSync(file)) throw new Error(`bow-images: AgentBow settings not found (${file})`);
  for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)\s*$/);
    if (m) env[m[1]] = m[2].replace(/^"(.*)"$/, "$1").replace(/\\\\/g, "\\");
  }
  return env;
}

function settings() {
  const dir = required(process.env.BOW_DIR, "BOW_DIR");
  const idle = required(process.env.BOW_IDLE_SECS, "BOW_IDLE_SECS");
  if (!/^[1-9][0-9]*$/.test(idle)) {
    throw new Error(`bow-images: BOW_IDLE_SECS must be a whole number of seconds above 0, got "${idle}"`);
  }
  const env = bowEnv(dir);
  return {
    dir,
    idle,
    engineUrl: required(process.env.ENGINE_URL, "ENGINE_URL"),
    exe: join(dir, "desktop", "src-tauri", "target", "debug", "bow-desktop.exe"),
    port: Number(required(env.BOW_WS_PORT, "BOW_WS_PORT in AgentBow's .env")),
    workspace: required(env.BOW_WORKSPACE, "BOW_WORKSPACE in AgentBow's .env"),
    secret: required(env.BOW_SECRET, "BOW_SECRET in AgentBow's .env"),
  };
}

// AgentBow writes the port it actually bound here (it moves off its usual port
// when that is busy) and deletes the file when it exits. Shared by every
// George window, as is the start-up lock.
const PORT_FILE = join(tmpdir(), "bow-images.port");
const LOCK_FILE = join(tmpdir(), "bow-images.lock");
const LOCK_STALE_MS = 45_000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** True only if AgentBow itself answers on this port. */
async function isBow(port) {
  try {
    const r = await fetch(`http://127.0.0.1:${port}/api/health`, { signal: AbortSignal.timeout(2000) });
    return r.ok && r.headers.get("x-app") === "bow";
  } catch {
    return false;
  }
}

/** The port of a running AgentBow, or null. */
async function runningPort(cfg) {
  let advertised = null;
  try { advertised = Number(readFileSync(PORT_FILE, "utf8").trim()); } catch {}
  // No file means an AgentBow started by hand (bow.bat), on its configured port.
  const port = advertised || cfg.port;
  return (await isBow(port)) ? port : null;
}

/** Take the start-up lock. Returns false if AgentBow came up while waiting. */
async function takeLock(cfg) {
  for (let waited = 0; waited < 60_000; waited += 500) {
    try {
      closeSync(openSync(LOCK_FILE, "wx"));
      return true;
    } catch (e) {
      if (e.code !== "EEXIST") throw e;
    }
    try {
      if (Date.now() - statSync(LOCK_FILE).mtimeMs > LOCK_STALE_MS) {
        unlinkSync(LOCK_FILE); // left by a start-up that crashed
        continue;
      }
    } catch {
      continue; // released between our two checks
    }
    if (await runningPort(cfg)) return false;
    await sleep(500);
  }
  throw new Error("another window has been starting AgentBow for over a minute");
}

/** Make sure AgentBow is running; returns its port. Only one caller starts it. */
async function ensureBow(cfg) {
  let port = await runningPort(cfg);
  if (port) return port;
  if (!(await takeLock(cfg))) {
    port = await runningPort(cfg);
    if (port) return port;
    throw new Error("AgentBow started in another window but stopped answering");
  }
  try {
    port = await runningPort(cfg);
    if (port) return port;
    if (!existsSync(cfg.exe)) throw new Error(`AgentBow is not built yet (${cfg.exe}). Run bow.bat once.`);
    const child = spawn(cfg.exe, [], {
      cwd: join(cfg.dir, "desktop", "src-tauri", "target", "debug"),
      env: {
        ...process.env,
        BOW_ENGINE_URL: cfg.engineUrl,
        BOW_NO_BROWSER: "1",
        BOW_IDLE_EXIT_SECS: cfg.idle,
        BOW_PORT_FILE: PORT_FILE,
      },
      detached: true, stdio: "ignore", windowsHide: true,
    });
    let spawnError = null;
    child.on("error", (e) => { spawnError = e; });
    child.unref();
    for (let i = 0; i < 60; i++) {
      await sleep(500);
      if (spawnError) throw new Error(`AgentBow could not start: ${spawnError.message}`);
      port = await runningPort(cfg);
      if (port) return port;
    }
    throw new Error("AgentBow did not start within 30 seconds.");
  } finally {
    try { unlinkSync(LOCK_FILE); } catch {}
  }
}

function slug(s) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 60) || "images";
}

/** A Windows pop-up (tray balloon) that doesn't wait for a click. For moments the
 *  user has to act: an engine's "are you a robot?" check. */
function notifyUser(title, text) {
  if (process.platform !== "win32") return;
  const esc = (s) => s.replace(/'/g, "''");
  const ps =
    "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing;" +
    "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information;" +
    `$n.BalloonTipTitle = '${esc(title)}'; $n.BalloonTipText = '${esc(text)}'; $n.Visible = $true;` +
    "$n.ShowBalloonTip(15000); Start-Sleep -Seconds 16; $n.Dispose()";
  const child = spawn("powershell", ["-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
    { detached: true, stdio: "ignore", windowsHide: true });
  child.on("error", () => {});
  child.unref();
}

/** AgentBow went away before the download started; safe to retry. */
class NotConnected extends Error {}

/** One download over AgentBow's WebSocket. `progress(message, done, target)` is
 *  called as photos are kept or rejected. */
function scrape(cfg, port, req, log, progress) {
  let kept = 0;
  let rejected = 0;
  return new Promise((resolveP, rejectP) => {
    const ws = new WebSocket(`ws://127.0.0.1:${port}/ws`);
    let inside = false;
    let settled = false;
    const finish = (fn, v) => {
      if (!settled) { settled = true; clearTimeout(timer); fn(v); }
      try { ws.close(); } catch {}
    };
    const timer = setTimeout(() => finish(rejectP, new Error("download timed out after 20 minutes")), 20 * 60 * 1000);
    const lost = (why) =>
      finish(rejectP, inside ? new Error(`AgentBow ${why} during the download`) : new NotConnected(why));
    ws.onerror = () => lost("connection failed");
    ws.onclose = () => lost("closed the connection");
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: cfg.secret, session_id: "bow-images" }));
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === "auth_ok") {
        inside = true;
        ws.send(JSON.stringify({ type: "scrape_request", ...req, dedupe: true }));
      } else if (m.type === "auth_error") {
        finish(rejectP, new Error("AgentBow rejected the login (BOW_SECRET)"));
      } else if (m.type === "error") {
        finish(rejectP, new Error(m.message || m.code));
      } else if (m.type === "scrape_event") {
        if (m.kind === "source") log.push(`${m.source}: ${m.count} found${m.error ? ` (${m.error})` : ""}`);
        if (m.kind === "candidates") log.push(`candidates: ${m.total} (filtered ${m.filtered})`);
        if (m.kind === "failed") log.push(`skipped: ${m.reason}`);
        if (m.kind === "phase" && /captcha/i.test(m.label || "")) {
          // AgentBow has put the engine's check in front in its browser window and
          // waits two minutes for someone to solve it.
          const engine = (m.label.match(/captcha for (\w+)/i) || [])[1] || "A search engine";
          const text = `${engine} wants you to prove you're human. Solve its check in the AgentBow browser ` +
            `window (Edge) within 2 minutes and the download carries on; otherwise ${engine} is skipped.`;
          log.push(`note: ${text}`);
          progress(text, kept, req.count);
          notifyUser("Image download needs you", text);
        }
        if (m.kind === "downloaded") kept = m.done;
        if (m.kind === "failed") rejected++;
        if (m.kind === "downloaded" || m.kind === "failed") {
          progress(`${req.query}: ${kept} of ${req.count} kept, ${rejected} rejected`, kept, req.count);
        }
        if (m.kind === "error") {
          // Keep any "solve the check" note: it is usually why nothing came back.
          const notes = log.filter((l) => l.startsWith("note: ")).map((l) => l.slice(6));
          finish(rejectP, new Error([m.message, ...notes].join(" ")));
        }
        if (m.kind === "done") finish(resolveP, m);
      }
    };
  });
}

async function download({ query, count = 10, dest_dir, verify = false, min_side = 512, delay_ms = 1500, sources,
                          single_subject = false }, progress) {
  if (!query) throw new Error("query is required");
  const cfg = settings();
  // AgentBow only writes inside its workspace; download there, then copy out.
  const staging = join(cfg.workspace, "bow-images", slug(query));
  mkdirSync(staging, { recursive: true });
  if (sources) {
    // AgentBow ignores names it doesn't know, which silently narrows the search
    // (a model asking for "duckduckgo" got Bing alone). Refuse them instead.
    const unknown = sources.filter((s) => !ENGINES.includes(String(s).toLowerCase()));
    if (unknown.length) {
      throw new Error(`unknown engine ${unknown.join(", ")}; use any of ${ENGINES.join(", ")}, or leave sources out to use all`);
    }
  }
  // "Only that person" is a photo-check rule, so it switches the check on.
  const req = { query, count, dest_dir: staging, verify: verify || single_subject, single_subject,
                min_side, delay_ms, ...(sources ? { sources } : {}) };

  const log = [];
  let result;
  // Retry once if AgentBow went away between the check and the connection
  // (it was just closing itself after sitting idle).
  for (let attempt = 1; ; attempt++) {
    const port = await ensureBow(cfg);
    try {
      result = await scrape(cfg, port, req, log, progress);
      break;
    } catch (e) {
      if (!(e instanceof NotConnected) || attempt === 2) throw e;
      await sleep(1000);
    }
  }

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

// AgentBow's names for the engines its downloader runs.
const ENGINES = ["yandex", "bing", "brave", "ddg"];

const TOOLS = [{
  name: "image_download",
  description:
    "Find and download images of a subject from four image search engines at once (Yandex, Bing, Brave, DuckDuckGo). " +
    "Leave `sources` out: each engine fails on different names (Bing reads \"Reed\" as \"red\"), and all four together " +
    "cover for each other. " +
    "Skips small images, error pages and duplicates. Use this instead of hand-written download scripts when you need " +
    "N pictures of a person, character, object or style. Call once per subject. Set verify=true to have the vision " +
    "model reject pictures that don't match (slower; needs a vision model loaded). Searches are unfiltered, so a bare " +
    "name can match unrelated adult or off-topic pages; use verify=true when only the subject should appear.",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", description: "What to search for, e.g. \"Florence Henderson Carol Brady 1970s\"" },
      count: { type: "integer", minimum: 1, maximum: 200, default: 10 },
      dest_dir: { type: "string", description: "Folder to copy the images into (created if missing)" },
      verify: { type: "boolean", default: false },
      single_subject: {
        type: "boolean", default: false,
        description: "Only when the user asks for the subject alone (\"only that person\", \"just her\", " +
          "\"no one else in the picture\"): reject images where anyone else appears. Leave it off otherwise; " +
          "other people in a shot are often wanted (they help anchor a style set). Turns verify on.",
      },
      min_side: { type: "integer", default: 512, description: "Skip images whose shorter side is below this (pixels)" },
      delay_ms: { type: "integer", default: 1500, description: "Pause between downloads" },
      sources: { type: "array", items: { type: "string", enum: ["yandex", "bing", "brave", "ddg"] },
                 description: "Only to rule an engine out; normally leave this out and all four are used" },
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
      serverInfo: { name: "bow-images", version: "1.1.0" },
    });
  } else if (method === "tools/list") {
    reply(id, { tools: TOOLS });
  } else if (method === "tools/call") {
    // Progress updates while the download runs, for clients that ask for them
    // (MCP progress notifications), and on stderr for the client's log.
    const token = params?._meta?.progressToken;
    const progress = (message, done, total) => {
      process.stderr.write(`bow-images: ${message}\n`);
      if (token !== undefined) {
        process.stdout.write(JSON.stringify({
          jsonrpc: "2.0", method: "notifications/progress",
          params: { progressToken: token, progress: done, total, message },
        }) + "\n");
      }
    };
    try {
      const text = await download(params?.arguments || {}, progress);
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
