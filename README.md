# claude-bridge

**Use the Claude Code sessions on one computer from any other device**: a phone, tablet, laptop or desktop.

- **Your local sessions:** see and continue the Claude Code sessions already on that computer, including ones started in its own terminal, or start new ones.
- **Any device to control from:** iPhone, Android, iPad, Windows, macOS or Linux, through a web app you can add to your home screen. From another computer, Claude Code itself can also send tasks through MCP tools.
- **Any computer to control:** macOS, Linux or Windows.
- **Private:** devices talk directly and encrypted over [Tailscale](https://tailscale.com) (free). It doesn't use Claude Remote Control, cloud sessions or a public URL.

```
  ANY DEVICE (controller)                                 ANY COMPUTER (worker)
 ┌────────────────────────────┐                        ┌─────────────────────────────────┐
 │ 📱 Phone / tablet / browser │──┐                     │ bridge_daemon.py (auto-starts)  │
 │    web app (multi-machine)  │  │   encrypted, via    │  ├ serves the web app            │
 └────────────────────────────┘  ├──── over Tailscale ─▶│  ├ lists local Claude sessions   │
 ┌────────────────────────────┐  │   + bearer token    │  └ runs  claude -p [--resume id] │
 │ 💻 Claude Code (any OS)     │──┘                     │     inside allowed folders      │
 │    MCP tools: remote_*      │                        └─────────────────────────────────┘
 └────────────────────────────┘
```

**How it works and why I built it:** [Control Claude Code on another Mac, without the cloud](https://www.jenishvaghasiya.me/blog/control-claude-code-on-another-mac)

Install the bridge on **every computer you want to reach**. Every device you control from needs only Tailscale and a browser, or Claude Code.

---

## 1. Tailscale (every device)

Install Tailscale and log in with the **same account** everywhere:

| Device | Get it | Note |
|---|---|---|
| macOS | [tailscale.com/download/mac](https://tailscale.com/download/mac) | Approve **System Settings → General → Login Items & Extensions → Network Extension**, or the app stays stuck loading. Restart if it's still "Connecting" |
| Windows | [tailscale.com/download/windows](https://tailscale.com/download/windows) | |
| Linux | `curl -fsSL https://tailscale.com/install.sh \| sh && sudo tailscale up` | |
| iPhone / iPad | [App Store](https://apps.apple.com/app/tailscale/id1470499037) | Keep its VPN switch on |
| Android | [Google Play](https://play.google.com/store/apps/details?id=com.tailscale.ipn) | Keep its VPN switch on |

Check: `tailscale status` lists your devices.

## 2. Install the bridge (each computer you want to control)

**Requirements:** [Claude Code](https://code.claude.com) installed and logged in (`claude`, then `/login`), plus Python 3.9 or later and `git`.

**macOS / Linux**
```bash
git clone https://github.com/Jenish109/claude-bridge.git ~/claude-bridge
cd ~/claude-bridge
python3 install.py --root ~            # or e.g. --root ~/Projects --root ~/Desktop/Work
```

**Windows (PowerShell)**
```powershell
git clone https://github.com/Jenish109/claude-bridge.git $HOME\claude-bridge
cd $HOME\claude-bridge
py install.py --root $HOME
```

The installer:
- sets the bridge to start at login (macOS **launchd**, Linux **systemd --user**, Windows **Task Scheduler**);
- binds it to this computer's **Tailscale IP** only, on port 8765;
- creates a secret **token** in `~/.claude-bridge/token`;
- prints the **web address**, the **token** and the **Claude Code command** to connect.

`--root` sets which folders Claude may work in, and which folders' sessions you can see. Repeat it for more folders.

### Extra step on macOS: Full Disk Access
Without it, tasks that touch Desktop, Documents or Downloads **hang** on a hidden privacy prompt. The installer prints the exact paths. Add each one in **System Settings → Privacy & Security → Full Disk Access** (click **+**, press **⌘⇧G**, paste the path, click **Open**, then turn its switch on). Then restart the bridge with the command the installer printed.

### Keep it reachable
The computer must be **on, awake and logged in**, with Tailscale connected. Turn off automatic sleep:
- **macOS:** Battery/Energy → *Prevent automatic sleeping*
- **Windows:** Power & sleep → *Never*

On **Linux**, to keep the bridge running while you're logged out, run `sudo loginctl enable-linger $USER`.

## 3a. Control from a phone, tablet or any browser

1. Open the worker's address in any browser, for example `http://100.x.y.z:8765`.
2. Paste the token and tap **Connect**.
3. Add it to your home screen so it opens like an app:
   - **iPhone/iPad:** Share → **Add to Home Screen**
   - **Android:** ⋮ → **Add to Home screen** / **Install app**
   - **Desktop Chrome/Edge:** the install icon in the address bar

| In the app | |
|---|---|
| **Machine name ▾** (top) | Switch between computers, or **Add** another (its address and token). **One app can control all your computers** |
| **☰ Sessions** | All recent Claude Code sessions on that computer, **including ones started in its terminal**. Tap one to see its history and continue it |
| **＋** | Start a new session |
| 📁 **Folder** | Browse the allowed folders and pick where a new session runs |
| 🔒 **Mode** | Bridge default / Plan only / Accept edits / Bypass (if allowed) |
| ■ (while running) | Stop the task |

The app is plain `http`, but traffic is still encrypted, because Tailscale encrypts everything between your devices and the address can't be reached from the internet. Saved machines and tokens stay in that browser only.

## 3b. Control from Claude Code on another computer

On the controlling computer, install [`uv`](https://docs.astral.sh/uv/) and get the code:
```bash
git clone https://github.com/Jenish109/claude-bridge.git ~/claude-bridge
```
Then run the command the worker's installer printed, with the path pointing to your `bridge_mcp.py`:
```bash
claude mcp add claude-bridge-<worker-name> --scope user \
  -e BRIDGE_URL=http://<worker-tailscale-ip>:8765 -e BRIDGE_TOKEN=<token> \
  -- uv run -q --script ~/claude-bridge/bridge_mcp.py
```
Repeat with a different name for each worker. **Restart Claude Code**, then ask in plain English:
```
Check the remote machine's health.
List the Claude sessions on the remote machine and continue the latest one: run the tests.
On the remote machine, go to ~/Projects/api and fix the failing tests.
```

| Tool | What it does |
|---|---|
| `remote_health` | Checks the computer is reachable; shows its OS, allowed folders and mode |
| `remote_sessions` | Lists Claude Code sessions there, including ones started in its terminal |
| `remote_run` | Runs a task: new, or continuing a `session_id` |
| `remote_task` / `remote_tasks` | Follow one task / list recent tasks |
| `remote_cancel` | Stops a task |

---

## How sessions work

- Each task runs `claude -p` on the worker, which uses **the worker's own Claude Code login, settings, MCP servers and CLAUDE.md files**.
- Continuing a session uses `claude --resume <id>`, so the full conversation context is kept. You can switch devices mid-conversation: start at your desk, continue from your phone, then reopen it at the desk with `claude --resume <id>`.
- If the same session is also **open in a terminal right now**, that terminal won't show messages sent from your phone until you reopen it. Avoid typing in both at once.

## Permissions

The remote Claude runs headless, so it **can't stop to ask you for approval**. The installer flags decide what it may do:

| Flag | Effect |
|---|---|
| *(default)* `--permission-mode acceptEdits` | Can read and edit files; Bash commands that aren't pre-approved are denied |
| `--allowed-tools "Bash(git:*)" "Bash(npm:*)"` | Pre-approves specific commands |
| `--allow-bypass` | Lets the app/controller pick **Bypass** (everything allowed). Use only with folders you trust |
| `--root <dir>` | The only folders tasks may run in and sessions are listed from (repeatable) |

To change them, rerun `install.py` with the new flags. The token stays the same.

## Security

- The bridge listens **only on the Tailscale IP**, so it can't be reached from the internet or from local Wi-Fi.
- Every API call needs the bearer token. **Anyone with the token and access to your Tailscale network can run Claude on that computer, so keep it secret.**
- **Change the token:** delete `~/.claude-bridge/token`, rerun `install.py`, then update the app (Machines → Remove → Add) and any `claude mcp add` entries.
- Not using Tailscale? `--host <ip>` binds to another address, such as your LAN IP. Traffic is then **unencrypted** on that network, so use it only on networks you trust.

## Troubleshooting

| Problem | Fix |
|---|---|
| Tailscale (macOS) shows grey boxes and no Log in | Approve the Network Extension (step 1), then restart the Mac |
| Installer: "Tailscale has no IPv4 address" | Open Tailscale, log in and make sure it says Connected. Or use `--host` |
| App/tools: "Can't reach …" | Both devices online in Tailscale? Worker awake? Check the worker's log `~/.claude-bridge/daemon.log` |
| "Token rejected" (401) | Wrong token. Copy it again from the worker's `~/.claude-bridge/token` |
| "outside the allowed roots" | Add that folder with another `--root` and rerun the installer |
| macOS: task hangs on Desktop/Documents/Downloads | Grant Full Disk Access (step 2), then restart the bridge |
| macOS: Desktop access breaks after a Claude Code update | The `claude` path changed. Rerun the installer and add the new path it prints |
| A command was denied | Pre-approve it with `--allowed-tools`, or use `--allow-bypass` |
| Session missing from ☰ | Its folder must be inside a `--root`. The list shows the 40 most recent |
| No `remote_*` tools in Claude Code | Restart Claude Code; check `claude mcp list` |

## Manage

| | macOS | Linux | Windows |
|---|---|---|---|
| Logs | `~/.claude-bridge/daemon.log` | same | `%USERPROFILE%\.claude-bridge\daemon.log` |
| Restart | `launchctl kickstart -k gui/$(id -u)/com.claude-bridge.daemon` | `systemctl --user restart claude-bridge` | `schtasks /End /TN ClaudeBridge` then `schtasks /Run /TN ClaudeBridge` |
| Update | `git pull`, then restart | same | same |
| Remove | `python3 install.py --uninstall` | same | `py install.py --uninstall` |

Per-task transcripts from the bridge are in `~/.claude-bridge/tasks/`. Claude Code's own session files stay where they always are (`~/.claude/projects/`).

## Files

| File | Runs on | Purpose |
|---|---|---|
| `bridge_daemon.py` | Worker | HTTP API (standard library only): runs tasks, lists sessions, serves the web app |
| `install.py` | Worker | Cross-platform installer (launchd / systemd / Task Scheduler) |
| `web/` | Worker (served) | Phone/browser app: multi-machine, sessions, live progress |
| `bridge_mcp.py` | Controller | MCP server with the `remote_*` tools for Claude Code (dependencies installed automatically by `uv`) |
| `install_remote.sh` | — | Old macOS entry point; now just runs `install.py` |

## License

[MIT](LICENSE)

---

Built by [Jenish Vaghasiya](https://www.jenishvaghasiya.me). Need a custom MCP server or Claude Code workflow for your own team's tools? [I build those](https://www.jenishvaghasiya.me/services/mcp).
