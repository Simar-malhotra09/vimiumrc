
import json
import socket
from typing import Final

from aiohttp import WSMsgType, web
from pynput.keyboard import Controller as KeyboardController, Key
from Quartz import (
    CGEventCreateScrollWheelEvent,
    CGEventPost,
    kCGHIDEventTap,
    kCGScrollEventUnitPixel,
)

PORT: Final[int] = 8000
SCROLL_GAIN: Final[float] = 1.6  # finger px -> scroll px multiplier

INDEX_HTML: Final[str] = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no, viewport-fit=cover">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <title>Vimium Remote</title>
  <style>
    :root { color-scheme: dark; }
    html, body {
      margin: 0; padding: 0; height: 100%;
      overscroll-behavior: none; touch-action: none;
      background: #07070a; color: #888;
      font-family: -apple-system, system-ui, sans-serif;
      -webkit-user-select: none; user-select: none;
      -webkit-tap-highlight-color: transparent;
    }
    body { display: flex; flex-direction: column; height: 100vh; }

    #bar {
      padding: calc(8px + env(safe-area-inset-top)) 8px 6px 8px;
      background: #07070a;
      display: flex; flex-direction: column; gap: 6px;
    }
    .row { display: grid; gap: 6px; }
    .row.primary   { grid-template-columns: 1fr 1fr 1fr; }
    .row.secondary { grid-template-columns: 0.7fr 1fr 1fr 0.7fr 0.7fr; }

    .btn {
      background: #15151a; color: #ddd;
      border: 1px solid #25252b; border-radius: 10px;
      text-align: center; font-weight: 500; letter-spacing: 0.5px;
      transition: background 80ms, transform 80ms;
    }
    .btn:active { background: #2a2a32; transform: scale(0.96); }
    .btn .sub {
      display: block; font-size: 9px; color: #666;
      margin-top: 2px; font-weight: 400; letter-spacing: 0.3px;
    }
    .row.primary   .btn { padding: 14px 0; font-size: 13px; }
    .row.secondary .btn { padding: 10px 0; font-size: 12px; color: #b8b8be; }
    .row.secondary .btn .sub { font-size: 8px; }

    #pad-wrap {
      flex: 1; padding: 8px 8px calc(8px + env(safe-area-inset-bottom)) 8px;
      display: flex;
    }
    #pad {
      flex: 1; display: flex; align-items: center; justify-content: center;
      background: #1e1e24;
      border: 1px solid #303038; border-radius: 14px;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
      font-size: 12px; letter-spacing: 0.5px; color: #6a6a72;
      transition: background 120ms, color 120ms, border-color 200ms;
    }
    #pad.active { background: #2a2a32; color: #c0c0c8; }
    #pad.disconnected { border-color: #6b4a1a; color: #c9994a; }
  </style>
</head>
<body>
  <div id="bar">
    <div class="row primary">
      <div class="btn" data-cmd="prev_tab">◀ TAB<span class="sub">J</span></div>
      <div class="btn" data-cmd="next_tab">TAB ▶<span class="sub">K</span></div>
      <div class="btn" data-cmd="esc">ESC<span class="sub">esc</span></div>
    </div>
    <div class="row secondary">
      <div class="btn" data-cmd="top">⤒<span class="sub">gg</span></div>
      <div class="btn" data-cmd="page_up">PG ↑<span class="sub">u</span></div>
      <div class="btn" data-cmd="page_down">PG ↓<span class="sub">d</span></div>
      <div class="btn" data-cmd="bottom">⤓<span class="sub">G</span></div>
      <div class="btn" data-cmd="reload">↻<span class="sub">r</span></div>
    </div>
  </div>

  <div id="pad-wrap">
    <div id="pad" class="disconnected">connecting…</div>
  </div>

  <script>
    const pad = document.getElementById('pad');
    let ws = null;
    let lastY = null;
    let pendingDy = 0;
    let rafScheduled = false;

    function setConnected(ok) {
      pad.classList.toggle('disconnected', !ok);
      pad.textContent = ok ? 'drag to scroll' : 'reconnecting…';
    }

    function connect() {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => setConnected(true);
      ws.onclose = () => { setConnected(false); setTimeout(connect, 800); };
      ws.onerror = () => ws && ws.close();
    }
    connect();

    function flushScroll() {
      rafScheduled = false;
      if (pendingDy !== 0 && ws && ws.readyState === 1) {
        ws.send(JSON.stringify({ type: 'scroll', dy: pendingDy }));
        pendingDy = 0;
      }
    }

    pad.addEventListener('touchstart', (e) => {
      e.preventDefault();
      lastY = e.touches[0].clientY;
      pad.classList.add('active');
    }, { passive: false });

    pad.addEventListener('touchmove', (e) => {
      e.preventDefault();
      const y = e.touches[0].clientY;
      if (lastY !== null) {
        pendingDy += y - lastY;
        if (!rafScheduled) {
          rafScheduled = true;
          requestAnimationFrame(flushScroll);
        }
      }
      lastY = y;
    }, { passive: false });

    const release = () => { lastY = null; pad.classList.remove('active'); };
    pad.addEventListener('touchend', release);
    pad.addEventListener('touchcancel', release);

    document.querySelectorAll('.btn').forEach((btn) => {
      btn.addEventListener('touchstart', (e) => {
        e.preventDefault();
        const cmd = btn.dataset.cmd;
        if (ws && ws.readyState === 1) {
          ws.send(JSON.stringify({ type: 'cmd', name: cmd }));
        }
      }, { passive: false });
    });
  </script>
</body>
</html>
"""


def scroll_pixels(dy: int) -> None:
    """Post a single pixel-accurate scroll event. Positive dy = scroll up."""
    event = CGEventCreateScrollWheelEvent(None, kCGScrollEventUnitPixel, 1, dy)
    CGEventPost(kCGHIDEventTap, event)


def run_command(kb: KeyboardController, name: str) -> None:
    if name == "top":
        kb.press("g"); kb.release("g")
        kb.press("g"); kb.release("g")
    elif name == "bottom":
        with kb.pressed(Key.shift):
            kb.press("g"); kb.release("g")
    elif name == "page_down":
        kb.press("d"); kb.release("d")
    elif name == "page_up":
        kb.press("u"); kb.release("u")
    elif name == "next_tab":
        with kb.pressed(Key.shift):
            kb.press("k"); kb.release("k")
    elif name == "prev_tab":
        with kb.pressed(Key.shift):
            kb.press("j"); kb.release("j")
    elif name == "esc":
        kb.press(Key.esc); kb.release(Key.esc)
    elif name == "reload":
        kb.press("r"); kb.release("r")
    else:
        print(f"[warn] unknown cmd: {name}")


async def serve_index(request: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20.0)
    await ws.prepare(request)
    kb: KeyboardController = request.app["keyboard"]

    peer = request.remote
    print(f"[connect] {peer}")
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                payload = json.loads(msg.data)
            except json.JSONDecodeError:
                continue
            kind = payload.get("type")
            if kind == "scroll":
                dy = payload.get("dy")
                if not isinstance(dy, (int, float)):
                    continue
                scroll_pixels(int(dy * SCROLL_GAIN))
            elif kind == "cmd":
                name = payload.get("name")
                if isinstance(name, str):
                    run_command(kb, name)
    finally:
        print(f"[disconnect] {peer}")
    return ws


def discover_local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    finally:
        sock.close()


def build_app() -> web.Application:
    app = web.Application()
    app["keyboard"] = KeyboardController()
    app.router.add_get("/", serve_index)
    app.router.add_get("/ws", handle_websocket)
    return app


def main() -> None:
    ip = discover_local_ip()
    print()
    print(f"  Open on iPhone Safari:  http://{ip}:{PORT}")
    print()
    web.run_app(build_app(), host="0.0.0.0", port=PORT, print=lambda *_: None)


if __name__ == "__main__":
    main()
