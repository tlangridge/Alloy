#!/usr/bin/env bash
# Install the alloy skill by symlinking this repo into the host skill
# directories, then run doctor so you see your panel status immediately.
#
# Usage:
#   ./install.sh            # ~/.claude/skills/alloy, plus ~/.grok/skills/alloy
#                           # when ~/.grok exists
#   SKILLS_DIR=/path ./install.sh   # only this directory (CI / custom)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Python 3 is the only runtime dependency.
if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found on PATH (alloy needs Python 3.8+)." >&2
  exit 1
fi

install_link() {
  local skills_dir="$1"
  local label="$2"
  mkdir -p "$skills_dir"
  local link="$skills_dir/alloy"
  if [ -L "$link" ]; then
    echo "Updating existing symlink: $link"
    rm "$link"
  elif [ -e "$link" ]; then
    echo "error: $link already exists and is not a symlink." >&2
    echo "Move or remove it, then re-run install.sh." >&2
    exit 1
  fi
  ln -s "$REPO_DIR" "$link"
  echo "Linked $link -> $REPO_DIR  ($label)"
}

if [ -n "${SKILLS_DIR:-}" ]; then
  install_link "$SKILLS_DIR" "custom"
else
  install_link "$HOME/.claude/skills" "Claude Code"
  if [ -d "$HOME/.grok" ]; then
    install_link "${GROK_SKILLS_DIR:-$HOME/.grok/skills}" "Grok"
  fi
fi

chmod +x "$REPO_DIR/bin/alloy"
echo

echo "Panel status:"
"$REPO_DIR/bin/alloy" doctor || true
echo
echo "Done. RESTART Claude Code or Grok (or open a new session) so it picks up"
echo "the skill, then try:  /alloy doctor   and   /alloy ask <your hard question>"
echo "Optional config:  cp '$REPO_DIR/alloy.config.example' ~/.config/alloy/config"
