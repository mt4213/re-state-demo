"""re_view — Browser-based conversation viewer for re_cur state."""

from __future__ import annotations

import argparse
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

# --------------------------------------------------------------------------- #
# Paths / config
# --------------------------------------------------------------------------- #

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "agent-core" / "state"
STATE_FILE = STATE_DIR / "messages.json"
STREAM_FILE = STATE_DIR / "stream.json"

DEFAULT_HOST = os.environ.get("HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("PORT", "5050"))


# --------------------------------------------------------------------------- #
# Front-end (single-file HTML/CSS/JS)
# --------------------------------------------------------------------------- #

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>re_view</title>
<style>
  :root {
    --bg:            #0d0d0d;
    --bg-elev:       #111;
    --bg-elev-2:     #1a1a1a;
    --border:        #222;
    --text:          #e0e0e0;
    --text-dim:      #888;
    --text-muted:    #555;
    --user:          #4caf50;
    --user-bg:       #18251a;
    --user-fg:       #e6f4ea;
    --asst:          #2196f3;
    --asst-bg:       #0d2137;
    --asst-deep:     #0d47a1;
    --tool:          #444;
    --tool-bg:       #111;
    --think:         #4caf50;
    --think-bg:      #1a2a1a;
    --warn:          #f44336;
    --radius:        8px;
    --gap:           10px;
    --max-w:         900px;
    --font-sans:     -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
                     'Helvetica Neue', Arial, sans-serif;
    --font-mono:     'SF Mono', Monaco, Menlo, Consolas, 'Liberation Mono',
                     'Courier New', monospace;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-sans);
    font-size: 14px;
    line-height: 1.5;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ---------- Header ---------- */
  header {
    flex: 0 0 auto;
    padding: 10px 20px;
    background: var(--bg-elev);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 12px;
    z-index: 10;
  }
  header h1 {
    font-size: 15px;
    font-weight: 600;
    color: #fff;
    letter-spacing: 0.05em;
  }
  #search {
    flex: 1;
    max-width: 320px;
    padding: 6px 10px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 12px;
    font-family: inherit;
    outline: none;
    transition: border-color 0.15s;
  }
  #search::placeholder { color: #555; }
  #search:focus { border-color: var(--asst); }

  #status {
    font-size: 11px;
    color: var(--text-muted);
    display: flex;
    align-items: center;
    gap: 6px;
    white-space: nowrap;
  }
  .dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--text-muted);
    transition: background 0.2s, box-shadow 0.2s;
  }
  #status.live  .dot { background: var(--user); box-shadow: 0 0 6px var(--user); }
  #status.error .dot { background: var(--warn); }

  /* ---------- Main scrollable log ---------- */
  #main {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
  }
  #main::-webkit-scrollbar       { width: 10px; }
  #main::-webkit-scrollbar-track { background: var(--bg); }
  #main::-webkit-scrollbar-thumb { background: #222; border-radius: 5px; }
  #main::-webkit-scrollbar-thumb:hover { background: #333; }

  #log {
    padding: 16px 20px 40px;
    display: flex;
    flex-direction: column;
    gap: var(--gap);
    max-width: var(--max-w);
    margin: 0 auto;
    width: 100%;
  }

  /* ---------- Messages ---------- */
  .msg {
    border-radius: var(--radius);
    padding: 10px 14px;
    max-width: 860px;
    word-break: break-word;
    animation: fade-in 0.18s ease-out;
  }
  @keyframes fade-in {
    from { opacity: 0; transform: translateY(3px); }
    to   { opacity: 1; transform: translateY(0);   }
  }
  .msg-hidden { display: none !important; }

  .msg-system {
    background: var(--bg-elev-2);
    border-left: 3px solid var(--text-muted);
    color: var(--text-dim);
    font-style: italic;
    font-size: 12px;
  }
  .msg-system:empty { display: none; }

  .msg-user {
    background: var(--user-bg);
    border-left: 3px solid var(--user);
    align-self: flex-end;
    color: var(--user-fg);
  }

  .msg-assistant, .msg-streaming {
    background: var(--asst-bg);
    border-left: 3px solid var(--asst);
    align-self: flex-start;
  }

  .msg-tool {
    background: var(--tool-bg);
    border-left: 3px solid var(--tool);
    font-family: var(--font-mono);
    font-size: 12px;
    color: #b0b0b0;
    white-space: pre-wrap;
    align-self: flex-start;
  }

  .role-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 5px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .role-label-user      { color: #81c784; }
  .role-label-assistant { color: var(--asst); }
  .role-label-tool      { color: #777; }
  .role-label-system    { color: var(--text-muted); }

  .content-text {
    margin-top: 2px;
    line-height: 1.55;
    white-space: pre-wrap;
  }

  /* ---------- Tool calls ---------- */
  .tool-call {
    display: inline-block;
    background: #1e3a5f;
    border: 1px solid var(--asst);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-family: var(--font-mono);
    margin: 2px 4px 4px 0;
    color: #90caf9;
  }
  .tool-call-args {
    margin-top: 4px;
    font-size: 12px;
    font-family: var(--font-mono);
    color: #9e9e9e;
    white-space: pre-wrap;
    background: rgba(0, 0, 0, 0.25);
    padding: 8px 10px;
    border-radius: 4px;
    overflow-x: auto;
  }

  /* ---------- Observation collapse ---------- */
  .obs-body { overflow: hidden; transition: max-height 0.2s; }
  .obs-body.collapsed {
    max-height: 3.6em;
    -webkit-mask-image: linear-gradient(to bottom, black 40%, transparent 100%);
            mask-image: linear-gradient(to bottom, black 40%, transparent 100%);
  }
  .obs-toggle {
    cursor: pointer;
    user-select: none;
    color: #777;
    font-size: 11px;
    margin-top: 6px;
    display: inline-block;
    padding: 2px 6px;
    border-radius: 3px;
    transition: color 0.15s, background 0.15s;
  }
  .obs-toggle:hover { color: #ddd; background: rgba(255, 255, 255, 0.05); }

  /* ---------- Think bubble ---------- */
  .think-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: var(--think);
    margin: 4px 0 2px;
  }
  .think-bubble {
    background: var(--think-bg);
    border-left: 3px solid var(--think);
    border-radius: 4px;
    padding: 6px 10px;
    margin: 0 0 6px;
    font-size: 12px;
    color: #a5d6a7;
    font-style: italic;
    white-space: pre-wrap;
    line-height: 1.5;
  }

  /* ---------- Streaming ---------- */
  .msg-streaming { animation: pulse 1.4s ease-in-out infinite; }
  @keyframes pulse {
    0%, 100% { border-left-color: var(--asst);     box-shadow: 0 0 0 0 rgba(33,150,243,0); }
    50%      { border-left-color: var(--asst-deep); box-shadow: 0 0 12px 0 rgba(33,150,243,.15); }
  }
  .streaming-cursor {
    display: inline-block;
    width: 6px; height: 1em;
    background: var(--asst);
    animation: blink 0.8s step-end infinite;
    vertical-align: text-bottom;
    margin-left: 2px;
    border-radius: 1px;
  }
  @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

  /* ---------- Empty / floating controls ---------- */
  #empty {
    color: #444;
    padding: 40px 20px;
    font-style: italic;
    text-align: center;
  }

  #scroll-btn {
    position: fixed;
    right: 24px;
    bottom: 24px;
    width: 40px; height: 40px;
    border: none;
    border-radius: 50%;
    background: var(--asst);
    color: #fff;
    font-size: 18px;
    cursor: pointer;
    opacity: 0;
    pointer-events: none;
    transform: translateY(8px);
    transition: opacity 0.2s, transform 0.2s, background 0.15s;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
  }
  #scroll-btn.show { opacity: 1; pointer-events: auto; transform: translateY(0); }
  #scroll-btn:hover { background: #1976d2; }

  @media (max-width: 600px) {
    header h1 { font-size: 13px; }
    #search   { max-width: 140px; }
    #log      { padding: 10px 12px 30px; }
  }
</style>
</head>
<body>
<header>
  <h1>re_view</h1>
  <input id="search" type="search" placeholder="Filter messages…  (press /)"
         spellcheck="false" autocomplete="off">
  <div id="status"><span class="dot"></span><span id="status-text">connecting…</span></div>
</header>
<main id="main">
  <div id="log"><div id="empty">No messages yet.</div></div>
</main>
<button id="scroll-btn" title="Scroll to bottom (End)" aria-label="Scroll to bottom">↓</button>

<script>
(() => {
  'use strict';

  // ---------- Config ----------
  const POLL_INTERVAL      = 2000;   // ms — full-state poll
  const STREAM_INTERVAL    = 150;    // ms — active stream poll
  const STREAM_IDLE_DELAY  = 800;    // ms — idle stream poll (after a few `done`s)
  const STREAM_IDLE_AFTER  = 4;      // # of consecutive done:true to back off
  const SCROLL_THRESHOLD   = 80;     // px — treat "near bottom" as stuck

  // ---------- DOM ----------
  const $             = sel => document.querySelector(sel);
  const logEl        = $('#log');
  const mainEl       = $('#main');
  const statusEl     = $('#status');
  const statusText   = $('#status-text');
  const searchInput  = $('#search');
  const scrollBtn    = $('#scroll-btn');

  // ---------- State ----------
  const state = {
    lastHash:      0,
    streamDiv:      null,
    streamTimer:    null,
    pollTimer:      null,
    streamIdle:    0,
    query:          '',
    stickToBottom: true,
  };

  // ---------- Utils ----------
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls)            e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  };

  // djb2-ish 32-bit hash — avoids re-serialising JSON for comparison
  const fastHash = s => {
    let h = 5381;
    for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
    return h;
  };

  const isNearBottom = () =>
    (mainEl.scrollHeight - mainEl.scrollTop - mainEl.clientHeight) < SCROLL_THRESHOLD;

  const scrollToBottom = (smooth = false) =>
    mainEl.scrollTo({ top: mainEl.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });

  const setStatus = (text, cls = '') => {
    statusText.textContent = text;
    statusEl.className = cls;
  };

  // ---------- Rendering helpers ----------
  function appendThought(parent, text, streaming = false) {
    parent.appendChild(el('div', 'think-label', streaming ? 'THINK ⟳' : 'THINK'));
    const bubble = el('div', 'think-bubble', text);
    if (streaming) bubble.appendChild(el('span', 'streaming-cursor'));
    parent.appendChild(bubble);
  }

  function appendToolCall(parent, tc) {
    const fn = tc.function || {};
    if (tc._thought) appendThought(parent, tc._thought);
    parent.appendChild(el('span', 'tool-call', fn.name || '?'));
    if (fn.arguments) {
      try {
        const args = JSON.parse(fn.arguments);
        parent.appendChild(el('div', 'tool-call-args', JSON.stringify(args, null, 2)));
      } catch { /* still streaming / malformed — skip pretty-print */ }
    }
  }

  function renderMessage(msg) {
    const role = msg.role || 'unknown';
    const div  = el('div', 'msg msg-' + role);
    div.dataset.role = role;
    let searchText = '';

    if (role === 'tool') {
      const content = msg.content || '';
      const isLong  = content.length > 300;
      div.appendChild(el(
        'div', 'role-label role-label-tool',
        'OBS / tool_call_id: ' + (msg.tool_call_id || '?')
      ));
      const body = el('div', 'obs-body' + (isLong ? ' collapsed' : ''), content);
      div.appendChild(body);
      if (isLong) {
        const toggle = el('div', 'obs-toggle', '▼ show more');
        toggle.addEventListener('click', () => {
          const collapsed = body.classList.toggle('collapsed');
          toggle.textContent = collapsed ? '▼ show more' : '▲ show less';
        });
        div.appendChild(toggle);
      }
      searchText = content;

    } else if (role === 'assistant') {
      div.appendChild(el('div', 'role-label role-label-assistant', 'assistant'));
      const thought = msg.reasoning || msg._thought;
      if (thought) appendThought(div, thought);
      if (msg.content) div.appendChild(el('div', 'content-text', msg.content));
      (msg.tool_calls || []).forEach(tc => appendToolCall(div, tc));
      searchText = (thought || '') + ' ' + (msg.content || '');

    } else if (role === 'user' || role === 'system') {
      div.appendChild(el('div', 'role-label role-label-' + role, role));
      div.appendChild(el('div', 'content-text', msg.content || '(empty)'));
      searchText = msg.content || '';

    } else {
      const raw = JSON.stringify(msg);
      div.textContent = raw;
      searchText = raw;
    }

    div.dataset.text = searchText.toLowerCase();
    return div;
  }

  // ---------- Filtering ----------
  function applyFilter() {
    const q = state.query;
    const msgs = logEl.querySelectorAll('.msg');
    msgs.forEach(m => {
      const hit = !q || (m.dataset.text || '').includes(q);
      m.classList.toggle('msg-hidden', !hit);
    });
  }

  // ---------- Full-state render ----------
  function renderAll(messages) {
    const payload = JSON.stringify(messages);
    const h = fastHash(payload);
    if (h === state.lastHash) return;
    state.lastHash = h;

    const wasStuck = state.stickToBottom || isNearBottom();

    const frag = document.createDocumentFragment();
    if (!messages.length) {
      const empty = el('div', '', 'No messages yet.');
      empty.id = 'empty';
      frag.appendChild(empty);
    } else {
      messages.forEach(m => frag.appendChild(renderMessage(m)));
    }
    logEl.replaceChildren(frag);

    applyFilter();

    // Re-attach active streaming bubble (if any) to the end
    if (state.streamDiv) logEl.appendChild(state.streamDiv);

    if (wasStuck) scrollToBottom();
  }

  // ---------- Streaming render ----------
  function renderStream(data) {
    if (data.done) {
      if (state.streamDiv) { state.streamDiv.remove(); state.streamDiv = null; }
      return;
    }
    const wasStuck = state.stickToBottom || isNearBottom();

    if (!state.streamDiv) {
      state.streamDiv = el('div', 'msg msg-streaming');
      state.streamDiv.id = 'stream-bubble';
      logEl.appendChild(state.streamDiv);
    }

    const div = state.streamDiv;
    div.replaceChildren();
    div.appendChild(el('div', 'role-label role-label-assistant', 'assistant ⟳'));

    if (data.reasoning) appendThought(div, data.reasoning, true);

    if (data.content) {
      const c = el('div', 'content-text', data.content);
      c.appendChild(el('span', 'streaming-cursor'));
      div.appendChild(c);
    }

    (data.tool_calls || []).forEach(tc => {
      const fn = tc.function || {};
      if (fn.name) div.appendChild(el('span', 'tool-call', fn.name));
      if (fn.arguments) {
        let raw = fn.arguments;
        // Progressive "thought" field extraction (raw JSON, while streaming)
        const m = raw.match(/"thought"\s*:\s*"([^]*?)(?:\",|"$)/);
        if (m) {
          const thought = m[1].replace(/\\n/g, '\n').replace(/\\"/g, '"');
          appendThought(div, thought, true);
          raw = raw.replace(/"thought"\s*:\s*"[^]*?(?:\",|"$)\s*/, '');
        }
        const args = el('div', 'tool-call-args', raw);
        args.appendChild(el('span', 'streaming-cursor'));
        div.appendChild(args);
      }
    });

    const nothing = !data.reasoning && !data.content &&
                    !(data.tool_calls && data.tool_calls.length);
    if (nothing) {
      const c = el('div', 'content-text');
      c.appendChild(el('span', 'streaming-cursor'));
      div.appendChild(c);
    }

    if (wasStuck) scrollToBottom();
  }

  // ---------- Polling ----------
  async function poll() {
    try {
      const r = await fetch('/messages', { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const data = await r.json();
      renderAll(data);
      setStatus(`live · ${data.length} message${data.length === 1 ? '' : 's'}`, 'live');
    } catch (e) {
      setStatus('error: ' + e.message, 'error');
    }
  }

  async function streamPoll() {
    try {
      const r = await fetch('/stream', { cache: 'no-store' });
      if (r.ok) {
        const data = await r.json();
        const hadBubble = !!state.streamDiv;

        if (data.done) state.streamIdle++;
        else           state.streamIdle = 0;

        renderStream(data);

        // Stream just finished — refresh the authoritative message list
        if (hadBubble && data.done) poll();
      }
    } catch { /* swallow — next tick will retry */ }
    scheduleStreamPoll();
  }

  function scheduleStreamPoll() {
    if (document.hidden) return;  // paused by visibility handler
    const delay = state.streamIdle > STREAM_IDLE_AFTER ? STREAM_IDLE_DELAY : STREAM_INTERVAL;
    state.streamTimer = setTimeout(streamPoll, delay);
  }

  function startTimers() {
    stopTimers();
    poll();
    state.pollTimer   = setInterval(poll, POLL_INTERVAL);
    state.streamIdle  = 0;
    state.streamTimer = setTimeout(streamPoll, STREAM_INTERVAL);
  }

  function stopTimers() {
    if (state.pollTimer)   clearInterval(state.pollTimer);
    if (state.streamTimer) clearTimeout(state.streamTimer);
    state.pollTimer = state.streamTimer = null;
  }

  // ---------- Event wiring ----------
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopTimers();
    else                 startTimers();
  });

  mainEl.addEventListener('scroll', () => {
    const near = isNearBottom();
    state.stickToBottom = near;
    scrollBtn.classList.toggle('show', !near);
  });

  scrollBtn.addEventListener('click', () => {
    state.stickToBottom = true;
    scrollToBottom(true);
  });

  searchInput.addEventListener('input', e => {
    state.query = e.target.value.trim().toLowerCase();
    applyFilter();
  });

  document.addEventListener('keydown', e => {
    const inField = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';
    if (inField) {
      if (e.key === 'Escape') {
        searchInput.value = '';
        state.query = '';
        applyFilter();
        searchInput.blur();
      }
      return;
    }
    if (e.key === '/') {
      e.preventDefault();
      searchInput.focus();
      searchInput.select();
    } else if (e.key === 'End') {
      e.preventDefault();
      state.stickToBottom = true;
      scrollToBottom(true);
    } else if (e.key === 'Home') {
      e.preventDefault();
      mainEl.scrollTo({ top: 0, behavior: 'smooth' });
    }
  });

  startTimers();
})();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #

class ReViewHandler(BaseHTTPRequestHandler):
    server_version = "re_view/2.0"

    # Silence default stderr access logging
    def log_message(self, format, *args):  # noqa: A002 (shadow builtin is stdlib API)
        return

    # ---- low-level helpers ----
    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.end_headers()
        self.wfile.write(body)

    def _send_json_file(self, path: Path, fallback: bytes) -> None:
        try:
            body = path.read_bytes()
            if not body.strip():  # empty or partial write — serve fallback
                body = fallback
        except (FileNotFoundError, OSError):
            body = fallback
        self._send(HTTPStatus.OK, "application/json; charset=utf-8", body)

    # ---- routing ----
    def do_GET(self) -> None:  # noqa: N802 (stdlib API)
        route = self.path.split("?", 1)[0]

        if route == "/messages":
            self._send_json_file(STATE_FILE, b"[]")
        elif route == "/stream":
            self._send_json_file(STREAM_FILE, b'{"done": true}')
        elif route == "/health":
            self._send(HTTPStatus.OK, "application/json", b'{"ok": true}')
        elif route in ("/", "/index.html"):
            self._send(HTTPStatus.OK, "text/html; charset=utf-8",
                       INDEX_HTML.encode("utf-8"))
        else:
            self._send(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8", b"not found")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="re_view — browser-based conversation viewer")
    p.add_argument("--host", default=DEFAULT_HOST,
                   help=f"bind address (default: {DEFAULT_HOST}, env: HOST)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"listen port (default: {DEFAULT_PORT}, env: PORT)")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        server = ThreadingHTTPServer((args.host, args.port), ReViewHandler)
    except OSError as exc:
        print(f"re_view: cannot bind {args.host}:{args.port} — {exc}", file=sys.stderr)
        return 1

    with server:
        print(f"re_view running at http://{args.host}:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nre_view: shutting down", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())