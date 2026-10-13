#!/usr/bin/env python3
"""Install the Claude bridge daemon on the machine you want to control (macOS, Linux or Windows).

It runs at login (launchd / systemd --user / Task Scheduler), bound to this machine's
Tailscale IP, then prints how to connect from Claude Code, a phone or any browser.

    python3 install.py --root ~/Projects                 # macOS / Linux
    py install.py --root %USERPROFILE%\\Projects          # Windows
    python3 install.py --uninstall

Any extra flags (--permission-mode, --allowed-tools, --allow-bypass, --port) go to bridge_daemon.py.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DAEMON = HERE / "bridge_daemon.py"
STATE = Path.home() / ".claude-bridge"
LOG = STATE / "daemon.log"
LABEL = "com.claude-bridge.daemon"          # macOS launchd label
UNIT = "claude-bridge.service"              # Linux systemd user unit
TASK = "ClaudeBridge"                       # Windows scheduled task
SYSTEM = platform.system()


def run(cmd, check=True, timeout=60):
    return subprocess.run(cmd, check=check, capture_output=True, text=True, timeout=timeout)


def tailscale_candidates():
    found = [shutil.which("tailscale"),
             "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
             r"C:\Program Files\Tailscale\tailscale.exe"]
    return [c for c in dict.fromkeys(found) if c and Path(c).exists()]


def tailscale_ip():
    # Try every Tailscale CLI found: a stale standalone CLI can shadow the working app's one.
    candidates = tailscale_candidates()
    if not candidates:
        sys.exit("Tailscale not found. Install it from https://tailscale.com/download, log in, then rerun.\n"
                 "(Or pass --host <ip> to bind to another address, e.g. your LAN IP.)")
    for ts in candidates:
        try:
            ip = run([ts, "ip", "-4"], check=False, timeout=20).stdout.split()
        except (OSError, subprocess.TimeoutExpired):
            continue
        if ip:
            return ip[0]
    sys.exit("Tailscale has no IPv4 address. Open Tailscale, log in, make sure it says Connected, then rerun.\n"
             "(Or pass --host <ip> to bind to another address.)")


# ---------- per-OS service setup ----------

def install_macos(argv):
    plist = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
    path_env = os.pathsep.join(dict.fromkeys([str(Path(argv[argv.index("--claude-bin") + 1]).parent),
                                              "/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin"]))
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    args = "\n".join(f"    <string>{esc(a)}</string>" for a in argv)
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key><array>
{args}
  </array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{esc(path_env)}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
</dict></plist>
""")
    domain = f"gui/{os.getuid()}"
    run(["launchctl", "bootout", f"{domain}/{LABEL}"], check=False)
    run(["launchctl", "bootstrap", domain, str(plist)])
    return f"launchctl kickstart -k {domain}/{LABEL}", f"launchctl bootout {domain}/{LABEL}"


def uninstall_macos():
    run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], check=False)
    (Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist").unlink(missing_ok=True)


def install_linux(argv):
    unit = Path.home() / ".config/systemd/user" / UNIT
    unit.parent.mkdir(parents=True, exist_ok=True)
    quote = lambda a: '"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"'
    path_env = os.pathsep.join(dict.fromkeys([str(Path(argv[argv.index("--claude-bin") + 1]).parent),
                                              os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")]))
    unit.write_text(f"""[Unit]
Description=Claude bridge daemon
After=network-online.target

[Service]
ExecStart={' '.join(quote(a) for a in argv)}
Environment={quote('PATH=' + path_env)}
Restart=always
RestartSec=15

[Install]
WantedBy=default.target
""")
    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "enable", UNIT])
    run(["systemctl", "--user", "restart", UNIT])
    print("Tip: to keep it running while you're logged out, run:  sudo loginctl enable-linger $USER")
    return f"systemctl --user restart {UNIT}", f"systemctl --user disable --now {UNIT}"


def uninstall_linux():
    run(["systemctl", "--user", "disable", "--now", UNIT], check=False)
    (Path.home() / ".config/systemd/user" / UNIT).unlink(missing_ok=True)
    run(["systemctl", "--user", "daemon-reload"], check=False)


def install_windows(argv):
    # Scheduled-task commands are limited to ~260 chars, so the task starts a tiny launcher
    # (pythonw = no console window) that holds the full argument list.
    launcher = STATE / "launch.pyw"
    launcher.write_text("import runpy, sys\n"
                        f"sys.argv = {argv[1:]!r}\n"
                        f"runpy.run_path({str(DAEMON)!r}, run_name='__main__')\n", encoding="utf-8")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else sys.executable)
    run(["schtasks", "/End", "/TN", TASK], check=False)
    run(["schtasks", "/Create", "/TN", TASK, "/SC", "ONLOGON", "/RL", "LIMITED", "/F",
         "/TR", f'"{exe}" "{launcher}"'])
    run(["schtasks", "/Run", "/TN", TASK])
    return f'schtasks /End /TN {TASK} && schtasks /Run /TN {TASK}', f"schtasks /End /TN {TASK}"


def uninstall_windows():
    run(["schtasks", "/End", "/TN", TASK], check=False)
    run(["schtasks", "/Delete", "/TN", TASK, "/F"], check=False)
    (STATE / "launch.pyw").unlink(missing_ok=True)


INSTALLERS = {"Darwin": (install_macos, uninstall_macos),
              "Linux": (install_linux, uninstall_linux),
              "Windows": (install_windows, uninstall_windows)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", default=[], help="folder tasks may run in (repeatable)")
    parser.add_argument("--host", help="address to bind (default: this machine's Tailscale IP)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--uninstall", action="store_true")
    args, daemon_flags = parser.parse_known_args()

    if SYSTEM not in INSTALLERS:
        sys.exit(f"Unsupported OS: {SYSTEM}")
    install, uninstall = INSTALLERS[SYSTEM]
    if args.uninstall:
        uninstall()
        print("Claude bridge removed. (Token and logs remain in", STATE, ")")
        return

    claude = shutil.which("claude")
    if not claude:
        sys.exit("`claude` isn't on PATH. Install Claude Code (https://code.claude.com), run `claude` and /login, then rerun.")
    roots = [str(Path(os.path.expanduser(r)).resolve()) for r in (args.root or ["~"])]
    for r in roots:
        if not Path(r).is_dir():
            sys.exit(f"--root folder doesn't exist: {r}")
    host = args.host or tailscale_ip()
    STATE.mkdir(mode=0o700, exist_ok=True)

    argv = [sys.executable, str(DAEMON), "--host", host, "--port", str(args.port),
            "--claude-bin", claude, "--log", str(LOG)]
    for r in roots:
        argv += ["--root", r]
    argv += daemon_flags

    restart_cmd, stop_cmd = install(argv)

    token_file = STATE / "token"
    for _ in range(30):
        if token_file.exists():
            break
        time.sleep(0.5)
    else:
        sys.exit(f"The daemon didn't start. Check the log: {LOG}")
    token = token_file.read_text().strip()
    url = f"http://{host}:{args.port}"

    print(f"""
✅ Claude bridge is running on {platform.node()} ({SYSTEM}) at {url}
   Allowed folders: {', '.join(roots)}

── Connect from a phone, tablet or any browser ──────────────────────────────
   1. Install Tailscale on that device and log in with the same account.
   2. Open  {url}
   3. Paste this token:  {token}

── Connect from Claude Code on another computer ──────────────────────────────
   claude mcp add claude-bridge-{platform.node().split('.')[0].lower()} --scope user \\
     -e BRIDGE_URL={url} -e BRIDGE_TOKEN={token} \\
     -- uv run -q --script <path-to>/claude-bridge/bridge_mcp.py

   Keep the token secret: anyone with it (on your Tailscale network) can run Claude here.

── Manage ────────────────────────────────────────────────────────────────────
   Logs:     {LOG}
   Restart:  {restart_cmd}
   Stop:     {stop_cmd}
   Remove:   {Path(sys.executable).name} {Path(__file__).name} --uninstall""")

    if SYSTEM == "Darwin":
        real_py = run([sys.executable, "-c", "import sys; print(sys.executable)"]).stdout.strip()
        paths = "\n".join(f"     {p}" for p in dict.fromkeys([sys.executable, real_py, os.path.realpath(claude)]))
        print(f"""
── macOS: one more step ──────────────────────────────────────────────────────
   So tasks can use Desktop, Documents and Downloads, add these to
   System Settings → Privacy & Security → Full Disk Access (+, then ⌘⇧G, paste path):
{paths}
   then restart:  {restart_cmd}""")
    if SYSTEM == "Darwin" or SYSTEM == "Windows":
        print("\n   Keep this computer awake while you want to reach it (sleep settings).")


if __name__ == "__main__":
    main()
