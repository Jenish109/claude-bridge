#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2,<2"]
# ///
"""MCP server for the controlling machine: gives Claude tools to run tasks on the
remote machine (macOS, Linux or Windows) through bridge_daemon.py.

Config (env): BRIDGE_URL=http://<tailscale-ip>:8765  BRIDGE_TOKEN=<token>
"""
import json
import os
import time
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP

BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8765").rstrip("/")
BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "")
MAX_WAIT = 600

mcp = FastMCP("claude-bridge")


def call(method, path, body=None):
    req = urllib.request.Request(
        BRIDGE_URL + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"bridge returned {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"cannot reach bridge at {BRIDGE_URL}: {exc.reason}") from None


def wait_for(task_id, since, wait_seconds):
    deadline = time.time() + min(max(wait_seconds, 0), MAX_WAIT)
    events = []
    while True:
        view = call("GET", f"/tasks/{task_id}?since={since}")
        events += view["events"]
        since = view["next_since"]
        if view["status"] != "running" or time.time() >= deadline:
            view["events"] = events
            return view
        time.sleep(2)


def render(view):
    lines = [f"task {view['task_id']} — {view['status']} ({view['elapsed_s']}s) "
             f"session_id={view['session_id']} cwd={view['cwd']}"]
    for e in view["events"]:
        lines.append(f"  [text] {e['text']}" if e["kind"] == "text" else f"  [tool] {e['name']} {e['input']}")
    if view["status"] == "running":
        lines.append(f"Still running. Call remote_task('{view['task_id']}', since={view['next_since']}) to keep following it.")
    elif view.get("result") is not None:
        cost = f" (cost ${view['cost_usd']:.4f})" if view.get("cost_usd") else ""
        lines.append(f"RESULT{cost}:\n{view['result']}")
    return "\n".join(lines)


@mcp.tool()
def remote_health() -> str:
    """Check that the remote machine's bridge is reachable; shows its hostname, allowed roots and default permission mode."""
    return json.dumps(call("GET", "/health"), indent=2)


@mcp.tool()
def remote_run(prompt: str, cwd: str = "", session_id: str = "", permission_mode: str = "",
               model: str = "", wait_seconds: int = 120) -> str:
    """Run a Claude Code task on the remote machine.

    prompt: what the remote Claude should do.
    cwd: directory on the remote machine (must be inside the daemon's allowed roots; default: first root).
    session_id: continue an existing session — from an earlier result or from remote_sessions
    (which also lists sessions someone started in the remote machine's own terminal).
    permission_mode: default | plan | acceptEdits | auto | dontAsk | bypassPermissions (if the daemon allows it).
    wait_seconds: how long to wait for completion before returning (max 600); long tasks keep running
    and can be followed with remote_task.
    """
    body = {"prompt": prompt, "cwd": cwd or None, "session_id": session_id or None,
            "permission_mode": permission_mode or None, "model": model or None}
    started = call("POST", "/tasks", body)
    return render(wait_for(started["task_id"], 0, wait_seconds))


@mcp.tool()
def remote_task(task_id: str, since: int = 0, wait_seconds: int = 60) -> str:
    """Follow a remote task: returns progress events after index `since`, waiting up to wait_seconds for it to finish."""
    return render(wait_for(task_id, since, wait_seconds))


@mcp.tool()
def remote_sessions(limit: int = 20) -> str:
    """List recent Claude Code sessions on the remote machine (bridge-started or started in its terminal);
    pass a session_id to remote_run to continue one."""
    items = call("GET", f"/sessions?limit={limit}")["sessions"]
    if not items:
        return "No sessions in the allowed folders yet."
    return "\n".join(f"{s['session_id']}  {'RUNNING ' if s['running_task'] else ''}{s['prompts']} prompts  "
                     f"{s['cwd']}  {s['title'][:80]!r}" for s in items)


@mcp.tool()
def remote_tasks() -> str:
    """List tasks the remote bridge has run since it started (status, session_id, prompt)."""
    items = call("GET", "/tasks")["tasks"]
    if not items:
        return "No tasks yet."
    return "\n".join(f"{t['task_id']}  {t['status']:9}  session={t['session_id']}  {t['prompt'][:80]!r}" for t in items)


@mcp.tool()
def remote_cancel(task_id: str) -> str:
    """Stop a running remote task."""
    view = call("POST", f"/tasks/{task_id}/cancel")
    return f"task {task_id}: {view['status']}"


if __name__ == "__main__":
    mcp.run()
