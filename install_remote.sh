#!/bin/bash
# Kept for older instructions: the installer is now cross-platform Python (install.py).
exec python3 "$(cd "$(dirname "$0")" && pwd)/install.py" "$@"
