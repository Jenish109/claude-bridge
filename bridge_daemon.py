#!/usr/bin/env python3
"""Claude bridge daemon: runs on the machine you want to control.

Accepts tasks over HTTP (bearer-token auth), runs them with `claude -p`
(headless, resumable sessions) and keeps the streamed events so the caller
can poll for progress. Also lists this machine's existing Claude Code sessions
(including ones started in a terminal) so they can be continued remotely, and
serves the browser/phone web app. Standard library only; macOS, Linux, Windows.

    python3 bridge_daemon.py --host <tailscale-ip> --root ~/Projects
"""
import argparse
import hmac
import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent / "web"
WEB_FILES = {  # public static files for the browser UI; every API route still needs the token
    "/": ("index.html", "text/html; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
}
STATE_DIR = Path.home() / ".claude-bridge"
TOKEN_FILE = STATE_DIR / "token"
LOG_DIR = STATE_DIR / "tasks"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
SESSION_ID = re.compile(r"[0-9a-fA-F-]{36}")
SAFE_MODES = {"default", "plan", "acceptEdits", "auto", "dontAsk"}

tasks = {}
tasks_lock = threading.Lock()
session_cache = {}  # transcript path -> (mtime, summary)
config = None


def load_token():
    if os.environ.get("BRIDGE_TOKEN"):
        return os.environ["BRIDGE_TOKEN"]
    STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    if not TOKEN_FILE.exists():
        TOKEN_FILE.write_text(secrets.token_urlsafe(32))
        TOKEN_FILE.chmod(0o600)
        print(f"Generated new token in {TOKEN_FILE}", file=sys.stderr)
    return TOKEN_FILE.read_text().strip()


def resolve_cwd(cwd):
    path = Path(os.path.expanduser(cwd or config.roots[0])).resolve()
    if not path.is_dir():
        raise ValueError(f"cwd does not exist: {path}")
    if not within_roots(path):
        raise ValueError(f"cwd {path} is outside the allowed roots: {[str(r) for r in config.roots]}")
    return path


def within_roots(path):
    path = Path(path).resolve()
    return any(path == r or r in path.parents for r in config.roots)


def prompt_text(entry):
    """Text of a real user prompt in a transcript entry, or None (tool results, meta, slash-command noise)."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return None
    content = entry.get("message", {}).get("content")
    if isinstance(content, list):
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str) or not content.strip() or content.lstrip().startswith("<"):
        return None
    return content


def read_transcript(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def summarize_session(path):
    mtime = path.stat().st_mtime
    cached = session_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    summary = {"session_id": path.stem, "cwd": None, "title": None, "last_prompt": None, "prompts": 0, "updated": mtime}
    for entry in read_transcript(path):
        summary["cwd"] = summary["cwd"] or entry.get("cwd")
        text = prompt_text(entry)
        if text:
            summary["title"] = summary["title"] or text[:120]
            summary["last_prompt"] = text[:120]
            summary["prompts"] += 1
    session_cache[path] = (mtime, summary)
    return summary


def list_sessions(limit=40):
    """Recent Claude Code sessions on this machine whose folder is inside the allowed roots."""
    files = sorted(PROJECTS_DIR.glob("*/*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
    out = []
    with tasks_lock:
        running = {t.session_id: t.id for t in tasks.values() if t.status == "running" and t.session_id}
    for f in files:
        try:
            s = summarize_session(f)
        except OSError:
            continue
        if s["prompts"] and s["cwd"] and within_roots(s["cwd"]):
            out.append({**s, "running_task": running.get(s["session_id"])})
            if len(out) >= limit:
                break
    return out


def session_messages(session_id, limit=200):
    if not SESSION_ID.fullmatch(session_id):
        raise ValueError("invalid session id")
    files = list(PROJECTS_DIR.glob(f"*/{session_id}.jsonl"))
    if not files:
        raise LookupError(f"no session {session_id}")
    messages, cwd = [], None
    for entry in read_transcript(files[0]):
        cwd = cwd or entry.get("cwd")
        if entry.get("isSidechain"):
            continue
        text = prompt_text(entry)
        if text:
            messages.append({"kind": "user", "text": text})
        elif entry.get("type") == "assistant":
            for block in entry.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    messages.append({"kind": "text", "text": block["text"]})
                elif block.get("type") == "tool_use":
                    messages.append({"kind": "tool", "name": block.get("name"),
                                     "input": json.dumps(block.get("input"))[:300]})
    if not cwd or not within_roots(cwd):
        raise ValueError("that session's folder is outside the allowed roots")
    return {"session_id": session_id, "cwd": cwd, "messages": messages[-limit:], "total": len(messages)}


class Task:
    def __init__(self, body):
        self.id = uuid.uuid4().hex[:12]
        self.prompt = body["prompt"]
        self.cwd = resolve_cwd(body.get("cwd"))
        self.resume = body.get("session_id")
        self.mode = body.get("permission_mode") or config.permission_mode
        if self.mode == "bypassPermissions" and not config.allow_bypass:
            raise ValueError("bypassPermissions is disabled (start the daemon with --allow-bypass)")
        if self.mode not in SAFE_MODES | {"bypassPermissions"}:
            raise ValueError(f"unknown permission_mode: {self.mode}")
        self.model = body.get("model")
        self.allowed_tools = body.get("allowed_tools") or config.allowed_tools
        self.status = "running"
        self.session_id = self.resume
        self.result = None
        self.cost_usd = None
        self.events = []
        self.started = time.time()
        self.finished = None
        self.proc = None

    def command(self):
        cmd = [config.claude_bin, "-p", "--output-format", "stream-json", "--verbose",
               "--permission-mode", self.mode]
        if self.resume:
            cmd += ["--resume", self.resume]
        if self.model:
            cmd += ["--model", self.model]
        if self.allowed_tools:
            cmd += ["--allowedTools", *self.allowed_tools]
        return cmd

    def run(self):
        log = (LOG_DIR / f"{self.id}.jsonl").open("w")
        try:
            self.proc = subprocess.Popen(
                self.command(), cwd=self.cwd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            self.proc.stdin.write(self.prompt)
            self.proc.stdin.close()
            for line in self.proc.stdout:
                log.write(line)
                log.flush()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.handle(event)
            stderr = self.proc.stderr.read()
            code = self.proc.wait()
            if self.status == "running":
                self.status = "cancelled" if code < 0 else ("done" if code == 0 else "error")
                if code > 0 and not self.result:
                    self.result = stderr.strip()[-4000:] or f"claude exited with code {code}"
        except Exception as exc:  # noqa: BLE001 - report any launch failure to the caller
            self.status, self.result = "error", f"{type(exc).__name__}: {exc}"
        finally:
            self.finished = time.time()
            log.close()

    def handle(self, event):
        kind = event.get("type")
        if event.get("session_id"):
            self.session_id = event["session_id"]
        if kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text" and block.get("text", "").strip():
                    self.events.append({"kind": "text", "text": block["text"]})
                elif block.get("type") == "tool_use":
                    self.events.append({"kind": "tool", "name": block.get("name"),
                                        "input": json.dumps(block.get("input"))[:300]})
        elif kind == "result":
            self.result = event.get("result")
            self.cost_usd = event.get("total_cost_usd")
            self.status = "error" if event.get("is_error") else "done"

    def view(self, since=0):
        return {
            "task_id": self.id, "status": self.status, "session_id": self.session_id,
            "cwd": str(self.cwd), "permission_mode": self.mode, "started": self.started,
            "prompt": self.prompt, "result": self.result, "cost_usd": self.cost_usd,
            "elapsed_s": round((self.finished or time.time()) - self.started, 1),
            "events": self.events[since:], "next_since": len(self.events),
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}", file=sys.stderr)

    def cors(self):
        # Token travels in a header (no cookies), so any origin may call the API: lets one web app
        # page (e.g. on your phone) switch between several machines.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if hmac.compare_digest(supplied.encode(), config.token.encode()):
            return True
        self.send(401, {"error": "unauthorized"})
        return False

    def parts(self):
        path, _, query = self.path.partition("?")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        return [p for p in path.split("/") if p], params

    def task_or_404(self, task_id):
        with tasks_lock:
            task = tasks.get(task_id)
        if not task:
            self.send(404, {"error": f"no task {task_id}"})
        return task

    def send_static(self, name, content_type):
        try:
            body = (WEB_DIR / name).read_bytes()
        except OSError:
            return self.send(404, {"error": f"missing web file {name}"})
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.partition("?")[0]
        if path in WEB_FILES:
            return self.send_static(*WEB_FILES[path])
        if not self.authorized():
            return
        parts, params = self.parts()
        if parts == ["dirs"]:
            try:
                base = resolve_cwd(urllib.parse.unquote(params.get("path", "")))
                dirs = sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
            except (ValueError, OSError) as exc:
                return self.send(400, {"error": str(exc)})
            parent = base.parent if any(base.parent == r or r in base.parent.parents for r in config.roots) else None
            self.send(200, {"path": str(base), "parent": str(parent) if parent else None, "dirs": dirs})
        elif parts == ["health"]:
            self.send(200, {"ok": True, "host": platform.node(), "os": platform.system(),
                            "roots": [str(r) for r in config.roots],
                            "permission_mode": config.permission_mode})
        elif parts == ["sessions"]:
            self.send(200, {"sessions": list_sessions(int(params.get("limit", 40)))})
        elif len(parts) == 2 and parts[0] == "sessions":
            try:
                self.send(200, session_messages(parts[1], int(params.get("limit", 200))))
            except LookupError as exc:
                self.send(404, {"error": str(exc)})
            except ValueError as exc:
                self.send(400, {"error": str(exc)})
        elif parts == ["tasks"]:
            with tasks_lock:
                items = [t.view(len(t.events)) for t in tasks.values()]
            self.send(200, {"tasks": [{k: v for k, v in t.items() if k != "events"} for t in items]})
        elif len(parts) == 2 and parts[0] == "tasks":
            if task := self.task_or_404(parts[1]):
                self.send(200, task.view(int(params.get("since", 0))))
        else:
            self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.authorized():
            return
        parts, _ = self.parts()
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self.send(400, {"error": "invalid JSON body"})
        if parts == ["tasks"]:
            if not body.get("prompt"):
                return self.send(400, {"error": "prompt is required"})
            try:
                task = Task(body)
            except ValueError as exc:
                return self.send(400, {"error": str(exc)})
            with tasks_lock:
                if task.resume and any(t.session_id == task.resume and t.status == "running"
                                       for t in tasks.values()):
                    return self.send(409, {"error": "that session already has a running task"})
                tasks[task.id] = task
            threading.Thread(target=task.run, daemon=True).start()
            self.send(202, task.view())
        elif len(parts) == 3 and parts[0] == "tasks" and parts[2] == "cancel":
            if task := self.task_or_404(parts[1]):
                if task.proc and task.status == "running":
                    task.proc.terminate()
                    task.status = "cancelled"
                self.send(200, task.view(len(task.events)))
        else:
            self.send(404, {"error": "not found"})


def main():
    global config
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to bind; use this Mac's Tailscale IP (tailscale ip -4)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--root", action="append", dest="roots",
                        help="directory tasks may run in (repeatable); default: home directory")
    parser.add_argument("--permission-mode", default="acceptEdits", choices=sorted(SAFE_MODES | {"bypassPermissions"}),
                        help="default permission mode for tasks (default: acceptEdits)")
    parser.add_argument("--allowed-tools", nargs="*", default=[],
                        help='tools pre-approved for every task, e.g. "Bash(npm test:*)" Read Edit')
    parser.add_argument("--allow-bypass", action="store_true",
                        help="let callers request bypassPermissions")
    parser.add_argument("--claude-bin", default=shutil.which("claude"))
    parser.add_argument("--log", help="append logs to this file instead of stderr")
    config = parser.parse_args()
    if config.log:
        sys.stderr = open(os.path.expanduser(config.log), "a", buffering=1, encoding="utf-8")
    if not config.claude_bin:
        sys.exit("claude not found on PATH; pass --claude-bin /path/to/claude")
    if config.permission_mode == "bypassPermissions":
        config.allow_bypass = True
    config.roots = [Path(os.path.expanduser(r)).resolve() for r in (config.roots or ["~"])]
    config.token = load_token()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((config.host, config.port), Handler)
    print(f"Claude bridge listening on http://{config.host}:{config.port}  "
          f"(roots: {', '.join(map(str, config.roots))}; mode: {config.permission_mode})", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
