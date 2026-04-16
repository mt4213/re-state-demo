"""re_view — Browser-based conversation viewer for re_cur state."""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "messages.json")
PORT = 5000

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>re_view</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d0d0d; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; font-size: 14px; }
  #header { padding: 12px 20px; background: #111; border-bottom: 1px solid #222; display: flex; align-items: center; gap: 12px; }
  #header h1 { font-size: 16px; font-weight: 600; color: #fff; letter-spacing: 0.05em; }
  #status { font-size: 12px; color: #555; margin-left: auto; }
  #status.live { color: #4caf50; }
  #log { padding: 16px 20px; display: flex; flex-direction: column; gap: 10px; max-width: 900px; margin: 0 auto; width: 100%; }
  .msg { border-radius: 8px; padding: 10px 14px; max-width: 860px; word-break: break-word; }
  .msg-system { background: #1a1a1a; border-left: 3px solid #555; color: #888; font-style: italic; font-size: 12px; }
  .msg-system:empty, .msg-system.hidden { display: none; }
  .msg-assistant { background: #0d2137; border-left: 3px solid #2196f3; align-self: flex-start; }
  .msg-tool { background: #111; border-left: 3px solid #444; font-family: monospace; font-size: 12px; color: #b0b0b0; white-space: pre-wrap; align-self: flex-start; }
  .role-label { font-size: 10px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 5px; }
  .role-label-assistant { color: #2196f3; }
  .role-label-tool { color: #777; }
  .role-label-system { color: #555; }
  .tool-call { display: inline-block; background: #1e3a5f; border: 1px solid #2196f3; border-radius: 4px; padding: 2px 8px; font-size: 11px; font-family: monospace; margin: 2px 2px 4px 0; color: #90caf9; }
  .tool-call-args { margin-top: 4px; font-size: 12px; font-family: monospace; color: #9e9e9e; white-space: pre-wrap; }
  .content-text { margin-top: 2px; line-height: 1.5; }
  #empty { color: #444; padding: 40px 20px; font-style: italic; }
  .obs-toggle { cursor: pointer; user-select: none; color: #777; font-size: 11px; margin-bottom: 4px; }
  .obs-toggle:hover { color: #aaa; }
  .obs-body { overflow: hidden; }
  .obs-body.collapsed { max-height: 3.6em; -webkit-mask-image: linear-gradient(to bottom, black 40%, transparent 100%); mask-image: linear-gradient(to bottom, black 40%, transparent 100%); }
  .think-bubble { background: #1a2a1a; border-left: 3px solid #4caf50; border-radius: 4px; padding: 4px 10px; margin: 4px 0; font-size: 12px; color: #81c784; font-style: italic; }
  .think-label { font-size: 10px; font-weight: 700; letter-spacing: 0.1em; color: #4caf50; margin-bottom: 2px; }
</style>
</head>
<body>
<div id="header">
  <h1>re_view</h1>
  <span id="status">connecting...</span>
</div>
<div id="log"><div id="empty">No messages yet.</div></div>
<script>
const log = document.getElementById('log');
const status = document.getElementById('status');
let lastCount = -1;

function escape(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function render(messages) {
  if (messages.length === lastCount) return;
  lastCount = messages.length;
  log.innerHTML = '';
  if (!messages.length) { log.innerHTML = '<div id="empty">No messages yet.</div>'; return; }
  messages.forEach(msg => {
    const role = msg.role || 'unknown';
    const div = document.createElement('div');
    div.className = 'msg msg-' + role;

    const label = document.createElement('div');
    label.className = 'role-label role-label-' + role;

    if (role === 'tool') {
      const content = msg.content || '';
      const isLong = content.length > 300;
      label.textContent = 'OBS / tool_call_id: ' + (msg.tool_call_id || '?');
      div.appendChild(label);
      const body = document.createElement('div');
      body.className = 'obs-body' + (isLong ? ' collapsed' : '');
      body.textContent = content;
      div.appendChild(body);
      if (isLong) {
        const toggle = document.createElement('div');
        toggle.className = 'obs-toggle';
        toggle.textContent = '▼ show more';
        toggle.addEventListener('click', () => {
          const collapsed = body.classList.toggle('collapsed');
          toggle.textContent = collapsed ? '▼ show more' : '▲ show less';
        });
        div.appendChild(toggle);
      }
    } else if (role === 'assistant') {
      label.textContent = 'assistant';
      div.appendChild(label);
      if (msg.content) {
        const c = document.createElement('div');
        c.className = 'content-text';
        c.textContent = msg.content;
        div.appendChild(c);
      }
      (msg.tool_calls || []).forEach(tc => {
        const fn = (tc.function || {});
        if (tc._thought) {
          const tl = document.createElement('div');
          tl.className = 'think-label';
          tl.textContent = 'THINK';
          div.appendChild(tl);
          const tb = document.createElement('div');
          tb.className = 'think-bubble';
          tb.textContent = tc._thought;
          div.appendChild(tb);
        }
        const badge = document.createElement('span');
        badge.className = 'tool-call';
        badge.textContent = fn.name || '?';
        div.appendChild(badge);
        if (fn.arguments) {
          try {
            const args = JSON.parse(fn.arguments);
            const pre = document.createElement('div');
            pre.className = 'tool-call-args';
            pre.textContent = JSON.stringify(args, null, 2);
            div.appendChild(pre);
          } catch(_) {}
        }
      });
    } else if (role === 'system') {
      label.textContent = 'system';
      div.appendChild(label);
      const c = document.createElement('div');
      c.className = 'content-text';
      c.textContent = msg.content || '(empty)';
      div.appendChild(c);
    } else {
      div.textContent = JSON.stringify(msg);
    }
    log.appendChild(div);
  });
  window.scrollTo(0, document.body.scrollHeight);
}

async function poll() {
  try {
    const r = await fetch('/messages');
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    render(data);
    status.textContent = 'live · ' + data.length + ' messages';
    status.className = 'live';
  } catch(e) {
    status.textContent = 'error: ' + e.message;
    status.className = '';
  }
}

poll();
setInterval(poll, 2000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence access logs

    def do_GET(self):
        if self.path == "/messages":
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    body = f.read().encode("utf-8")
            except FileNotFoundError:
                body = b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"re_view running at http://127.0.0.1:{PORT}")
    server.serve_forever()
