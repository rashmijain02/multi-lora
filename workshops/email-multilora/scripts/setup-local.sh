#!/usr/bin/env bash
set -euo pipefail

device=cpu
python_command=python3
check_only=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --device)
            [[ $# -ge 2 ]] || { echo "--device requires cpu or cuda" >&2; exit 2; }
            device="$2"; shift 2 ;;
        --python)
            [[ $# -ge 2 ]] || { echo "--python requires an executable" >&2; exit 2; }
            python_command="$2"; shift 2 ;;
        --check-only) check_only=true; shift ;;
        *) echo "Usage: bash scripts/setup-local.sh [--device cpu|cuda] [--python python3.12] [--check-only]" >&2; exit 2 ;;
    esac
done
[[ "$device" == cpu || "$device" == cuda ]] || { echo "Device must be cpu or cuda" >&2; exit 2; }
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
venv_python=.venv/bin/python
if [[ "$check_only" == false ]]; then
    if [[ ! -e .venv ]]; then
        "$python_command" -c 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 14), "Python 3.11-3.13 required"'
        "$python_command" -m venv .venv
    fi
    [[ -x "$venv_python" ]] || { echo "Existing .venv is incomplete or from another OS; recreate it explicitly. Setup never deletes it." >&2; exit 1; }
    "$venv_python" -c 'import sys; assert (3, 11) <= sys.version_info[:2] < (3, 14), "Python 3.11-3.13 required"'
    build=cpu
    [[ "$device" != cuda ]] || build=cu128
    "$venv_python" -m pip install "torch==2.10.0+$build" --index-url "https://download.pytorch.org/whl/$build"
    "$venv_python" -m pip install -e '.[training,dev]'
    "$venv_python" -m ipykernel install --sys-prefix --name email-multilora --display-name 'Python (email-multilora)'
fi
[[ -x "$venv_python" ]] || { echo "Workshop .venv is missing; run setup without --check-only." >&2; exit 1; }
"$venv_python" -m pip check
"$venv_python" scripts/check_local.py --device "$device"
