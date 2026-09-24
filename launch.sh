#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_python="$project_root/.venv/bin/python"
if [[ ! -x "$venv_python" ]]; then
    echo "Prompt2CST is not set up. Run ./setup.sh first." >&2
    exit 1
fi

cd "$project_root"
exec "$venv_python" -m prompt2cst.gui
