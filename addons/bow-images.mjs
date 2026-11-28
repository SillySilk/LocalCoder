// bow-images: George's bridge to AgentBow, its image toolbox.
//
// Offers AgentBow's image tools to George: search-and-download from four image
// engines, grab every image on a web page (both over AgentBow's WebSocket, with
// progress), and AgentBow's own tools (photo check, duplicates, captions,
// stats, resize), passed straight through to its /api/tools/call.
// AgentBow is started when needed (headless, on the shared Engine Manager
// engine, so it never loads a second copy of a model).
//
// AgentBow exits after BOW_IDLE_SECS with nothing to do, so it isn't left in
// memory; the next call starts it again (about 20 seconds).
//
// Settings (environment, all required): BOW_DIR (AgentBow folder), ENGINE_URL
// (shared engine), BOW_IDLE_SECS. AgentBow's own desktop\.env supplies its
// port, workspace and login secret.

import { spawn, execFileSync } from "node:child_process";
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

const STALL_MS = 10 * 60 * 1000;   // no progress this long: ask AgentBow to stop
const STOP_GRACE_MS = 2 * 60 * 1000; // then wait this long for it to wrap up

/** One job (search download or page grab) over AgentBow's WebSocket.
 *  `progress(message, done, target)` is called as photos are kept or rejected. */
function runJob(cfg, port, message, label, target, log, progress, onKept) {
  let kept = 0;
  let rejected = 0;
  return new Promise((resolveP, rejectP) => {
    const ws = new WebSocket(`ws://127.0.0.1:${port}/ws`);
    let inside = false;
    let settled = false;
    let stopping = null; // set when we asked AgentBow to stop; says why
    let lastActivity = Date.now();
    const finish = (fn, v) => {
      if (!settled) { settled = true; clearInterval(watchdog); fn(v); }
      try { ws.close(); } catch {}
    };
    // A slow run (the photo check takes ~15 s a photo) is fine; a run that has
    // stopped moving is not. After STALL_MS with nothing kept, rejected or
    // searched, ask AgentBow to stop: it then finishes normally with whatever it
    // has saved, so those photos are still handed over.
    const watchdog = setInterval(() => {
      const idle = Date.now() - lastActivity;
      if (!stopping && idle > STALL_MS) {
        stopping = `stopped after ${Math.round(STALL_MS / 60000)} minutes without progress`;
        log.push(`note: ${stopping}; kept what was saved`);
        try { ws.send(JSON.stringify({ type: "stop_scrape" })); } catch {}
      } else if (stopping && idle > STALL_MS + STOP_GRACE_MS) {
        finish(rejectP, new Error(`AgentBow did not finish after being asked to stop (${stopping})`));
      }
    }, 5000);
    const lost = (why) =>
      finish(rejectP, inside ? new Error(`AgentBow ${why} during the job`) : new NotConnected(why));
    ws.onerror = () => lost("connection failed");
    ws.onclose = () => lost("closed the connection");
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: cfg.secret, session_id: "bow-images" }));
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (!stopping) lastActivity = Date.now();
      if (m.type === "auth_ok") {
        inside = true;
        ws.send(JSON.stringify(message));
      } else if (m.type === "auth_error") {
        finish(rejectP, new Error("AgentBow rejected the login (BOW_SECRET)"));
      } else if (m.type === "error") {
        finish(rejectP, new Error(m.message || m.code));
      } else if (m.type === "scrape_event") {
        if (m.kind === "source") log.push(`${m.source}: ${m.count} found${m.error ? ` (${m.error})` : ""}`);
        if (m.kind === "candidates") log.push(`candidates: ${m.total} (filtered ${m.filtered})`);
        if (m.kind === "failed") log.push(`skipped: ${m.reason}`);
        if (m.kind === "phase" && /^could not open /.test(m.label || "")) log.push(`note: ${m.label}`);
        if (m.kind === "phase" && /captcha/i.test(m.label || "")) {
          // AgentBow has put the engine's check in front in its browser window and
          // waits two minutes for someone to solve it.
          const engine = (m.label.match(/captcha for (\w+)/i) || [])[1] || "A search engine";
          const text = `${engine} wants you to prove you're human. Solve its check in the AgentBow browser ` +
            `window (Edge) within 2 minutes and the download carries on; otherwise ${engine} is skipped.`;
          log.push(`note: ${text}`);
          progress(text, kept, target);
          notifyUser("Image download needs you", text);
        }
        if (m.kind === "downloaded") { kept = m.done; onKept(m.path); }
        if (m.kind === "failed") rejected++;
        if (m.kind === "downloaded" || m.kind === "failed") {
          progress(`${label}: ${kept} of ${target} kept, ${rejected} rejected`, kept, target);
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

/** Run a job into AgentBow's folder `staging`, copying each picture to
 *  `dest_dir` the moment it is kept, then describe the result. Pictures are
 *  checked before AgentBow saves them, so everything copied has passed; copying
 *  as they come means the folder fills while the run goes, and a run that is
 *  cut short has still delivered what it kept. */
async function runAndCollect(cfg, staging, message, label, target, dest_dir, progress) {
  const log = [];
  const out = dest_dir ? resolve(dest_dir) : null;
  if (out) mkdirSync(out, { recursive: true });
  const delivered = new Map(); // AgentBow's path -> the copy in dest_dir
  const deliver = (p) => {
    if (!out || !p || delivered.has(p)) return;
    try {
      const to = join(out, basename(p));
      copyFileSync(p, to);
      delivered.set(p, to);
    } catch (e) {
      log.push(`note: could not copy ${p} to ${out}: ${e.message}`);
    }
  };
  let result;
  // Retry once if AgentBow went away between the check and the connection
  // (it was just closing itself after sitting idle).
  for (let attempt = 1; ; attempt++) {
    const port = await ensureBow(cfg);
    try {
      result = await runJob(cfg, port, message, label, target, log, progress, deliver);
      break;
    } catch (e) {
      if (e instanceof NotConnected && attempt === 1) { await sleep(1000); continue; }
      const got = out ? `${delivered.size} photos kept before this are in ${out}` :
        `any photos saved before this are in ${staging}`;
      throw new Error(`${e.message} (${got})`);
    }
  }

  // Anything the live copy missed (a dropped message) is copied now.
  for (const p of result.downloaded || []) deliver(p);
  const saved = out ? [...delivered.values()] : (result.downloaded || []);
  const sizes = saved.map((p) => `${p} (${Math.round(statSync(p).size / 1024)} KB)`);
  const skipped = log.filter((l) => l.startsWith("skipped")).length;
  return [
    `Saved ${saved.length} of ${target} images for ${label}${dest_dir ? ` to ${dest_dir}` : ""}.`,
    ...sizes,
    "",
    ...log.filter((l) => !l.startsWith("skipped")),
    skipped ? `${skipped} candidates skipped (too small, not an image, duplicate, or not matching the search).` : "",
  ].join("\n");
}

async function download({ query, count = 10, dest_dir, min_side = 512, delay_ms = 1500, sources,
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
  // The photo check is always on. Searches run with the engines' adult filters
  // off, so without it a name search can return anything (a test search for a
  // TV character came back mostly adult images of unrelated people). It checks
  // that each photo matches the search, not what kind of content it is, so an
  // adult search still gets adult results. Left optional, the model switched it
  // off to save time, so it is not offered as an option.
  const message = { type: "scrape_request", query, count, dest_dir: staging, verify: true, single_subject,
                    min_side, delay_ms, dedupe: true, ...(sources ? { sources } : {}) };
  return runAndCollect(cfg, staging, message, `"${query}"`, count, dest_dir, progress);
}

async function pageGrab({ url, count = 50, dest_dir, scrolls = 3 }, progress) {
  if (!url || !/^https?:\/\//i.test(url)) throw new Error("url must be a full http(s) address");
  const cfg = settings();
  const staging = join(cfg.workspace, "bow-images", slug(`page ${new URL(url).hostname} ${new URL(url).pathname}`));
  mkdirSync(staging, { recursive: true });
  const message = { type: "page_scrape_request", url, count, dest_dir: staging, scrolls };
  return runAndCollect(cfg, staging, message, url, count, dest_dir, progress);
}

/** AgentBow's own tools, read from `bow-desktop --list-tools` (starts nothing). */
let bowToolCache = null;
function bowTools() {
  if (bowToolCache) return bowToolCache;
  const cfg = settings();
  if (!existsSync(cfg.exe)) throw new Error(`AgentBow is not built yet (${cfg.exe}). Run bow.bat once.`);
  const out = execFileSync(cfg.exe, ["--list-tools"], { encoding: "utf8", windowsHide: true, timeout: 30000 });
  bowToolCache = JSON.parse(out).tools;
  return bowToolCache;
}

/** Run one of AgentBow's own tools through its /api/tools/call. */
async function callBowTool(name, args) {
  const cfg = settings();
  for (let attempt = 1; ; attempt++) {
    const port = await ensureBow(cfg);
    let r;
    try {
      r = await fetch(`http://127.0.0.1:${port}/api/tools/call`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-bow-token": cfg.secret },
        body: JSON.stringify({ name, arguments: args }),
      });
    } catch (e) {
      if (attempt === 1) { await sleep(1000); continue; } // AgentBow was just closing; start it again
      throw new Error(`could not reach AgentBow: ${e.message}`);
    }
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || `AgentBow answered ${r.status}`);
    return typeof body.result === "string" ? body.result : JSON.stringify(body.result, null, 2);
  }
}

// AgentBow's names for the engines its downloader runs.
const ENGINES = ["yandex", "bing", "brave", "ddg"];

const OWN_TOOLS = [{
  name: "image_download",
  description:
    "Find and download images of a subject from four image search engines at once (Yandex, Bing, Brave, DuckDuckGo). " +
    "Leave `sources` out: each engine fails on different names (Bing reads \"Reed\" as \"red\"), and all four together " +
    "cover for each other. " +
    "Skips small images, error pages and duplicates. Use this instead of hand-written download scripts when you need " +
    "N pictures of a person, character, object or style. Call once per subject. Every picture is checked by the " +
    "vision model and kept only if it matches the search; that takes ~15 s a picture, so 25 pictures can take " +
    "10-20 minutes. Wait for it: a slow run is working, and progress updates show how far it has got.",
  inputSchema: {
    type: "object",
    properties: {
      query: { type: "string", description: "What to search for, e.g. \"Florence Henderson Carol Brady 1970s\"" },
      count: { type: "integer", minimum: 1, maximum: 200, default: 10 },
      dest_dir: { type: "string", description: "Folder to copy the images into (created if missing)" },
      single_subject: {
        type: "boolean", default: false,
        description: "Only when the user asks for the subject alone (\"only that person\", \"just her\", " +
          "\"no one else in the picture\"): reject images where anyone else appears. Leave it off otherwise; " +
          "other people in a shot are often wanted (they help anchor a style set).",
      },
      min_side: { type: "integer", default: 512, description: "Skip images whose shorter side is below this (pixels)" },
      delay_ms: { type: "integer", default: 1500, description: "Pause between downloads" },
      sources: { type: "array", items: { type: "string", enum: ["yandex", "bing", "brave", "ddg"] },
                 description: "Only to rule an engine out; normally leave this out and all four are used" },
    },
    required: ["query"],
  },
}, {
  name: "image_page_grab",
  description:
    "Download the images on one web page (a gallery, a wiki category, a fan site's episode stills) in a real " +
    "browser, so pages that block scripts still work. Use when you have found a good page; use image_download to " +
    "search instead. Skips small images and duplicates; no photo check, so review the result.",
  inputSchema: {
    type: "object",
    properties: {
      url: { type: "string", description: "Full address of the page" },
      count: { type: "integer", minimum: 1, maximum: 500, default: 50, description: "Most images to save" },
      dest_dir: { type: "string", description: "Folder to copy the images into (created if missing)" },
      scrolls: { type: "integer", minimum: 0, maximum: 20, default: 3,
                 description: "Scroll the page this many times first, to load lazy images" },
    },
    required: ["url"],
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
      serverInfo: { name: "bow-images", version: "2.0.0" },
    });
  } else if (method === "tools/list") {
    try {
      reply(id, { tools: [...OWN_TOOLS, ...bowTools()] });
    } catch (e) {
      fail(id, e.message);
    }
  } else if (method === "tools/call") {
    const name = params?.name;
    const args = params?.arguments || {};
    // Progress updates while a job runs, for clients that ask for them (MCP
    // progress notifications), and on stderr for the client's log.
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
      let text;
      if (name === "image_download") text = await download(args, progress);
      else if (name === "image_page_grab") text = await pageGrab(args, progress);
      else if (bowTools().some((t) => t.name === name)) text = await callBowTool(name, args);
      else throw new Error(`unknown tool ${name}`);
      reply(id, { content: [{ type: "text", text }] });
    } catch (e) {
      reply(id, { content: [{ type: "text", text: `${name} failed: ${e.message}` }], isError: true });
    }
  } else if (method === "ping") {
    reply(id, {});
  } else if (id !== undefined) {
    fail(id, `unknown method ${method}`);
  }
});
