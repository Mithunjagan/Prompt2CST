#!/usr/bin/env bash
# Local app setup for Linux and macOS. Native openEMS is installed separately.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_python="$project_root/.venv/bin/python"

is_python311() {
    "$1" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 11))' \
        >/dev/null 2>&1
}

if [[ ! -x "$venv_python" ]]; then
    python311=""
    for candidate in python3.11 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && is_python311 "$candidate"; then
            python311="$candidate"
            break
        fi
    done
    if [[ -z "$python311" ]]; then
        echo "CPython 3.11 is required. Install it, then rerun ./setup.sh." >&2
        exit 1
    fi
    "$python311" -m venv "$project_root/.venv"
fi

if ! is_python311 "$venv_python"; then
    echo "Existing .venv does not use Python 3.11; move it aside and rerun setup." >&2
    exit 1
fi

"$venv_python" -m pip install --upgrade pip setuptools wheel
"$venv_python" -m pip install -e "$project_root"
mkdir -p "$project_root/outputs"

echo
echo "Prompt2CST installed. Current local capability check:"
"$venv_python" -m prompt2cst doctor
echo
echo "Run ./launch.sh to open the desktop app."
echo "openEMS native solver/bindings are optional and installed separately."
