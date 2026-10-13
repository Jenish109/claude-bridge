# claude-bridge

Control **Claude Code on another Mac** from the Claude Code session on your own Mac, or from **any phone, tablet or computer browser**.

- Doesn't use Claude Remote Control or cloud sessions.
- Doesn't use a public URL: the two Macs talk directly and encrypted over [Tailscale](https://tailscale.com) (free).
- Remote work runs in real, resumable Claude Code sessions on the other Mac, so you can continue a task across several requests.

**How it works and why I built it:** [Control Claude Code on another Mac, without the cloud](https://www.jenishvaghasiya.me/blog/control-claude-code-on-another-mac)

```
 YOUR MAC (controller)                              OTHER MAC (worker)
 ┌───────────────────────────┐   HTTP + token    ┌───────────────────────────────┐
 │ Claude Code session       │  over Tailscale   │ bridge_daemon.py (launchd)    │
 │  └ bridge_mcp.py (MCP) ───┼──────────────────▶│  └ claude -p  [--resume <id>] │
 │    remote_run / remote_*  │                   │    runs inside allowed folders│
 └───────────────────────────┘                   └───────────────────────────────┘
```

> **Two ways to control the worker:** from **Claude Code on another Mac** (MCP tools, Steps 3–4), or from **any device with a browser** (the built-in web app, [Step 5](#step-5-phone-tablet-or-any-browser-web-app)).
>
> **It only works in one direction.** The controller sends tasks to the worker. For both Macs to control each other, set it up twice, once in each direction.

---

## What you need

| | Controller (your Mac) | Worker (the other Mac) |
|---|---|---|
| macOS | ✅ | ✅ |
| [Tailscale](https://tailscale.com/download/mac), **same account on both** | ✅ | ✅ |
| [Claude Code](https://code.claude.com), logged in | ✅ | ✅ |
| `git` (`xcode-select --install`) | ✅ | ✅ |
| [`uv`](https://docs.astral.sh/uv/) (`brew install uv`) | ✅ | — |
| Python 3 (already on macOS) | — | ✅ |

---

## Step 1: Tailscale (both Macs)

1. Install Tailscale from **https://tailscale.com/download/mac** and open it.
2. **Approve the network extension.** Without this the app stays stuck loading, with grey boxes and no Log in button:
   **System Settings → General → Login Items & Extensions → Tailscale (ⓘ) → turn on _Network Extension_**
   (older macOS: **Privacy & Security → Allow**). If macOS asks to *add VPN configurations*, click **Allow**.
3. Click the Tailscale icon in the menu bar, then **Log in**. Use the **same account on both Macs**.
4. Check that both Macs are listed:
   ```bash
   tailscale status
   ```
   If it's still stuck on "Connecting" after you approve the extension, **restart the Mac**.

## Step 2: Worker Mac (the one being controlled)

1. **Install Claude Code and log in** (skip if it's already installed):
   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   claude            # type /login, sign in, then exit
   ```
2. **Install the bridge:**
   ```bash
   git clone https://github.com/Jenish109/claude-bridge.git ~/claude-bridge
   cd ~/claude-bridge
   ./install_remote.sh --root ~
   ```
   - `--root` is the folder the remote Claude may work in. You can repeat it (`--root ~/Projects --root ~/Desktop/Work`), and each folder must already exist.
   - The installer runs the daemon at login (launchd), bound to this Mac's Tailscale IP, and creates a secret token in `~/.claude-bridge/token`.
   - At the end it **prints a `claude mcp add …` command**. Copy it for Step 3.
3. **Give the bridge Full Disk Access.** Without it, tasks that touch Desktop, Documents or Downloads **hang** while waiting for a privacy prompt nobody sees.
   First, print the paths to add:
   ```bash
   /usr/libexec/PlistBuddy -c "Print :ProgramArguments:0" ~/Library/LaunchAgents/com.claude-bridge.daemon.plist
   python3 -c "import sys; print(sys.executable)"
   readlink -f "$(which claude)"
   ```
   Then open **System Settings → Privacy & Security → Full Disk Access**. For **each path**: click **+**, press **⌘⇧G**, paste the path, press Enter, click **Open**, and make sure its switch is **on**.
   Restart the daemon:
   ```bash
   launchctl kickstart -k gui/$(id -u)/com.claude-bridge.daemon
   ```
4. **Keep it awake:** **System Settings → Battery / Energy → Prevent automatic sleeping when the display is off**.

## Step 3: Controller Mac (your Mac)

1. Get the code:
   ```bash
   git clone https://github.com/Jenish109/claude-bridge.git ~/claude-bridge
   ```
2. Run the command the worker printed, with the **last path changed** to this Mac's copy of `bridge_mcp.py`:
   ```bash
   claude mcp add claude-bridge --scope user \
     -e BRIDGE_URL=http://<worker-tailscale-ip>:8765 \
     -e BRIDGE_TOKEN=<token-from-worker> \
     -- uv run -q --script ~/claude-bridge/bridge_mcp.py
   ```
   If Claude Code can't find `uv`, use its full path from `which uv`, e.g. `/opt/homebrew/bin/uv`.
3. Check that it's registered:
   ```bash
   claude mcp get claude-bridge      # should say: ✔ Connected
   ```
4. **Restart Claude Code.** MCP tools only load in a new session.

## Step 4: Use it

In a Claude Code session **on the controller Mac**, ask in plain English, **one request at a time**:

```
Check the remote Mac's health.
On the remote Mac, list the folders in ~/Desktop/Work
On the remote Mac, go to ~/Desktop/Work/myapp and run the tests, fix any failures.
Continue that remote session and commit the changes.
What remote tasks are running?
Cancel the remote task.
```

Use **paths on the worker Mac** (e.g. `/Users/<worker-user>/...`), not paths from your own Mac.

| Tool | What it does |
|---|---|
| `remote_health` | Checks the worker is reachable and shows its allowed folders and permission mode |
| `remote_run` | Starts a task (`prompt`, `cwd`, optional `session_id` to continue, `permission_mode`, `model`) and waits up to `wait_seconds` |
| `remote_task` | Follows a long-running task and gets its result |
| `remote_tasks` | Lists recent tasks with their session IDs |
| `remote_cancel` | Stops a task |

Every result includes a `session_id`. Pass it back to continue the same conversation, or open it on the worker with `claude --resume <id>`.

## Step 5: Phone, tablet or any browser (web app)

The bridge includes a web app, so **iPhone, Android, iPad, Windows and Linux** all work. You don't install anything except Tailscale.

1. Install **Tailscale** on the device ([App Store](https://apps.apple.com/app/tailscale/id1470499037) · [Google Play](https://play.google.com/store/apps/details?id=com.tailscale.ipn) · [other](https://tailscale.com/download)) and log in with the **same account**. Keep its VPN switch **on**.
2. In the device's browser, open the worker's address. `install_remote.sh` prints it:
   ```
   http://<worker-tailscale-ip>:8765
   ```
3. Paste the **bridge token** (worker: `cat ~/.claude-bridge/token`) and tap **Connect**. It's saved only in that browser.
4. **Add it to your home screen** so it opens like an app:
   - **iPhone/iPad (Safari):** Share → **Add to Home Screen**
   - **Android (Chrome):** ⋮ menu → **Add to Home screen** / **Install app**
   - **Desktop Chrome/Edge:** the install icon in the address bar

What you can do in the web app:

| | |
|---|---|
| 📁 **Folder** chip | Browse the worker's allowed folders and pick where Claude works |
| 🔒 **Mode** chip | Bridge default / Plan only / Accept edits / Bypass (if the daemon allows it) |
| Message box | Send a task. Live progress shows each tool Claude uses and its replies. Follow-ups continue the same session |
| ■ button (while running) | Stop the task |
| **＋** | Start a new session |
| **☰** | Switch between recent sessions |

It uses plain `http`, but that's safe here because Tailscale encrypts all traffic between your devices, and the address can't be reached from the internet.

---

## Permissions

The remote Claude runs headless, so it **can't ask you for approval**. The daemon's settings decide what it may do:

| Install flag | Effect |
|---|---|
| *(default)* `--permission-mode acceptEdits` | Can read and edit files; Bash commands that aren't pre-approved are denied |
| `--allowed-tools "Bash(git:*)" "Bash(npm:*)"` | Pre-approves specific commands |
| `--allow-bypass` | Lets the controller request `bypassPermissions` (everything allowed). Use only with folders you trust |
| `--root <dir>` | The only folders tasks may run in (repeatable) |

To change these, rerun `./install_remote.sh` with the new flags. The token stays the same.

## Security

- The daemon listens **only on the worker's Tailscale IP**, so it isn't reachable from the internet or from your local Wi-Fi.
- Every request needs the bearer token (`~/.claude-bridge/token`, `chmod 600`). **Anyone with the token and access to your Tailscale network can run Claude on the worker, so keep it secret.**
- **Change the token:** on the worker, run `rm ~/.claude-bridge/token && ./install_remote.sh --root ~`. Then on the controller, run `claude mcp remove claude-bridge --scope user` and add it again with the new token.

## Troubleshooting

| Problem | Fix |
|---|---|
| Tailscale window shows grey boxes, no Log in | Approve the Network Extension (Step 1.2), then restart the Mac if needed |
| `cannot reach bridge` | Both Macs online in `tailscale status`? Worker awake? Daemon running? (`tail ~/.claude-bridge/daemon.log`) |
| `unauthorized` (401) | Wrong token. Copy it again from the worker's `~/.claude-bridge/token` |
| `outside the allowed roots` | Rerun the installer with that folder as another `--root` |
| Task hangs on Desktop / Documents / Downloads | Grant Full Disk Access (Step 2.3) and restart the daemon |
| Remote Claude says a command was denied | Pre-approve it with `--allowed-tools`, or use `--allow-bypass` |
| Desktop access breaks after a Claude Code update | The `claude` path changed. Rerun `readlink -f "$(which claude)"` and add the new path to Full Disk Access |
| No `remote_*` tools in Claude | Restart Claude Code; check `claude mcp get claude-bridge` |
| Web app: page won't load on phone | Tailscale VPN on in the phone's app? Using `http://` (not https) and port `:8765`? |
| Web app: "Token rejected" | Paste the token again; it changes if you rotate it |
| Worker's own Claude says it has no bridge tool | Expected: it only works in one direction. Send requests from the controller, or set up the reverse direction too |

## Manage the daemon (worker)

```bash
tail -f ~/.claude-bridge/daemon.log                                   # logs
ls ~/.claude-bridge/tasks/                                            # full transcript per task (.jsonl)
launchctl kickstart -k gui/$(id -u)/com.claude-bridge.daemon          # restart
launchctl bootout gui/$(id -u)/com.claude-bridge.daemon               # stop
rm ~/Library/LaunchAgents/com.claude-bridge.daemon.plist              # uninstall (after stopping)
```

The task list is kept in memory and resets when the daemon restarts. Sessions can still be resumed by ID.

## Files

| File | Runs on | Purpose |
|---|---|---|
| `bridge_daemon.py` | Worker | HTTP server (standard library only) that runs `claude -p` tasks and records their progress |
| `install_remote.sh` | Worker | Installs the daemon as a launchd agent and prints the controller command |
| `web/` | Worker (served by the daemon) | Browser/phone web app (installable on the home screen) |
| `bridge_mcp.py` | Controller | MCP server providing the `remote_*` tools (dependencies installed automatically by `uv`) |

## License

[MIT](LICENSE)

---

Built by [Jenish Vaghasiya](https://www.jenishvaghasiya.me). Need a custom MCP server or Claude Code workflow for your own team's tools? [I build those](https://www.jenishvaghasiya.me/services/mcp).
