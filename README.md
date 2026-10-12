# claude-bridge

Let a Claude Code session on one Mac run tasks on another Mac's Claude Code.
Doesn't use Remote Control or cloud sessions. Traffic goes peer-to-peer over Tailscale (WireGuard).

```
 this Mac (controller)                          other Mac (worker)
 ┌──────────────────────┐   HTTP + token   ┌──────────────────────────┐
 │ Claude Code session  │  over Tailscale  │ bridge_daemon.py         │
 │  └ bridge_mcp.py ────┼─────────────────▶│  └ claude -p --resume …  │
 │    remote_run/task…  │                  │    (runs in your repos)  │
 └──────────────────────┘                  └──────────────────────────┘
```

## Setup

**Both Macs:** install [Tailscale](https://tailscale.com/download) and sign in with the same Tailscale account.

**Other Mac (the one being controlled):**
1. Install Claude Code and log in (`claude`, then `/login`).
2. Get the code and install the daemon:
   ```bash
   git clone https://github.com/Jenish109/claude-bridge.git ~/claude-bridge
   cd ~/claude-bridge
   ./install_remote.sh --root ~/Projects          # dirs tasks may run in (repeatable)
   ```
   This starts the daemon at login with launchd and prints a `claude mcp add …` command that already includes the URL and token.

**This Mac (the controller):** `git clone https://github.com/Jenish109/claude-bridge.git`, then run the printed command, with the path changed to where `bridge_mcp.py` lives here (it needs [`uv`](https://docs.astral.sh/uv/)). Then restart Claude Code and check `/mcp` for `claude-bridge`.

## Use

Just ask in plain English:

> "On the remote Mac, run the test suite in ~/Projects/api and fix any failures."
> "Continue that remote session and open a PR."

| Tool | What it does |
|---|---|
| `remote_health` | Checks that the other Mac is reachable |
| `remote_run` | Starts a task (prompt, cwd, optional `session_id` to continue, permission mode, model) and waits up to `wait_seconds` |
| `remote_task` | Follows a running task's progress and gets its result |
| `remote_tasks` | Lists recent tasks with their session IDs |
| `remote_cancel` | Stops a task |

Every result includes a `session_id`. Pass it back to `remote_run` to continue the same conversation on the other Mac. You can also open it there with `claude --resume <id>`.

## Permissions & security

- Headless `claude -p` can't show approval prompts, so the daemon's `--permission-mode` decides what the remote Claude may do. The default is `acceptEdits`: it can edit files, but anything not pre-approved, like most Bash commands, is denied. Pre-approve tools with `--allowed-tools "Bash(npm test:*)" "Bash(git:*)"`, or pass `--allow-bypass` to let callers request `bypassPermissions`.
- Tasks can only run inside `--root` directories.
- The daemon binds only to the Tailscale IP and requires the token in `~/.claude-bridge/token` (chmod 600). Delete that file and reinstall to rotate the token.
- Full transcripts of each task are in `~/.claude-bridge/tasks/<id>.jsonl` on the other Mac. The task list is kept in memory, so it resets when the daemon restarts. Sessions themselves can still be resumed by ID.
