#!/usr/bin/env python3
import html
import json
import os
import shlex
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
OUT_DIR = Path(os.environ.get("IPQUALITY_OUT_DIR", "/tmp/ipquality"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
STATUS_FILE = OUT_DIR / "status.json"
RESULT_FILE = OUT_DIR / "result.json"
LOG_FILE = OUT_DIR / "run.log"

SCRIPT_ARGS = os.environ.get("IPQUALITY_ARGS", "-p -j")
RUN_TIMEOUT = int(os.environ.get("IPQUALITY_TIMEOUT", "240"))

state_lock = threading.Lock()
running = False


def write_status(status, started_at=None, finished_at=None, error=None):
    payload = {
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "error": error,
        "has_result": RESULT_FILE.exists(),
    }
    STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_status():
    if not STATUS_FILE.exists():
        write_status("idle")
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "unknown", "has_result": RESULT_FILE.exists()}


def run_check():
    global running
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_status("running", started_at=started)
    cmd = ["bash", str(ROOT / "ip.sh"), *shlex.split(SCRIPT_ARGS)]

    try:
        completed = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=RUN_TIMEOUT,
            check=False,
        )
        LOG_FILE.write_text(completed.stdout, encoding="utf-8", errors="replace")

        if completed.returncode != 0:
            raise RuntimeError(f"ip.sh exited with code {completed.returncode}")

        output = completed.stdout.strip()
        parsed = json.loads(output)
        RESULT_FILE.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        write_status("done", started_at=started, finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    except Exception as exc:
        LOG_FILE.write_text(str(exc), encoding="utf-8", errors="replace")
        write_status(
            "error",
            started_at=started,
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=str(exc),
        )
    finally:
        with state_lock:
            running = False


def start_run():
    global running
    with state_lock:
        if running:
            return False
        running = True
    threading.Thread(target=run_check, daemon=True).start()
    return True


class Handler(BaseHTTPRequestHandler):
    def send_text(self, body, status=200, content_type="text/html; charset=utf-8"):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/healthz":
            self.send_text("ok", content_type="text/plain; charset=utf-8")
            return

        if path == "/run":
            start_run()
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
            return

        if path == "/status":
            self.send_text(json.dumps(read_status(), ensure_ascii=False), content_type="application/json; charset=utf-8")
            return

        if path == "/result":
            if not RESULT_FILE.exists():
                self.send_text(json.dumps({"error": "no result yet"}, ensure_ascii=False), 404, "application/json; charset=utf-8")
                return
            self.send_text(RESULT_FILE.read_text(encoding="utf-8"), content_type="application/json; charset=utf-8")
            return

        if path == "/log":
            content = LOG_FILE.read_text(encoding="utf-8", errors="replace") if LOG_FILE.exists() else ""
            self.send_text(content, content_type="text/plain; charset=utf-8")
            return

        if path == "/":
            self.send_text(render_page())
            return

        self.send_text("not found", 404, "text/plain; charset=utf-8")

    def log_message(self, fmt, *args):
        return


def render_page():
    status = read_status()
    result = RESULT_FILE.read_text(encoding="utf-8") if RESULT_FILE.exists() else "{}"
    try:
        result = json.dumps(json.loads(result), ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        pass

    escaped_result = html.escape(result)
    escaped_status = html.escape(json.dumps(status, ensure_ascii=False, indent=2))

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>IPQuality on Render</title>
  <style>
    :root {{ color-scheme: light dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f6f7f9; color: #18202a; }}
    main {{ width: min(980px, calc(100vw - 32px)); margin: 32px auto; }}
    header {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; margin-bottom: 20px; }}
    h1 {{ font-size: 24px; margin: 0; letter-spacing: 0; }}
    p {{ color: #526071; line-height: 1.55; }}
    button, a.button {{ appearance: none; border: 0; border-radius: 6px; background: #176bff; color: white; padding: 10px 14px; font-weight: 650; text-decoration: none; display: inline-block; }}
    section {{ background: white; border: 1px solid #dde3ea; border-radius: 8px; padding: 16px; margin-top: 16px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; font-size: 13px; line-height: 1.45; }}
    .actions {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .muted {{ color: #66758a; font-size: 13px; }}
    @media (prefers-color-scheme: dark) {{
      body {{ background: #101318; color: #edf1f6; }}
      section {{ background: #171b22; border-color: #2a313c; }}
      p, .muted {{ color: #a8b3c2; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>IPQuality on Render</h1>
        <p>Results are generated from the current Render instance network.</p>
      </div>
      <div class="actions">
        <a class="button" href="/run">Run check</a>
        <a class="button" href="/result">JSON</a>
      </div>
    </header>
    <section>
      <p class="muted">Status</p>
      <pre id="status">{escaped_status}</pre>
    </section>
    <section>
      <p class="muted">Result</p>
      <pre>{escaped_result}</pre>
    </section>
    <p class="muted">Source: <a href="https://github.com/xykt/IPQuality">xykt/IPQuality</a></p>
  </main>
  <script>
    async function refreshStatus() {{
      const response = await fetch('/status');
      const data = await response.json();
      document.getElementById('status').textContent = JSON.stringify(data, null, 2);
      if (data.status === 'running') setTimeout(refreshStatus, 2500);
      if (data.status === 'done' && !location.hash) location.hash = 'done';
    }}
    refreshStatus();
  </script>
</body>
</html>"""


def main():
    port = int(os.environ.get("PORT", "10000"))
    write_status("idle")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
