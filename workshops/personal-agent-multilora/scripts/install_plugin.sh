#!/usr/bin/env bash
# Link the PersonaDesk plugin into the Hermes plugin directory and print next steps.
# Usage (from the repository root): bash workshops/personal-agent-multilora/scripts/install_plugin.sh
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_dir="$(cd "${script_dir}/../hermes_plugin" && pwd)"
hermes_home="${HERMES_HOME:-$HOME/.hermes}"
target="${hermes_home}/plugins/personadesk"

mkdir -p "${hermes_home}/plugins"
if [ -e "${target}" ] && [ ! -L "${target}" ]; then
  echo "Refusing to replace non-symlink ${target}; remove it yourself first." >&2
  exit 1
fi
ln -sfn "${source_dir}" "${target}"
echo "Linked personadesk plugin -> ${target}"
cat <<'EOF'
Each Hermes profile discovers plugins only in its own home. For the persona profiles,
run scripts/setup_hermes.py, which links the plugin into each profile, or set
HERMES_HOME to a profile directory before running this script.
EOF
