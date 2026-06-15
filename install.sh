#!/usr/bin/env bash
# Install the alloy skill for Claude Code by symlinking this repo into the
# skills directory, then run doctor so you see your panel status immediately.
#
# Usage:
#   ./install.sh            # symlink into ~/.claude/skills/alloy
#   SKILLS_DIR=/path ./install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="${SKILLS_DIR:-$HOME/.claude/skills}"
LINK="$SKILLS_DIR/alloy"

# Python 3 is the only runtime dependency.
if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found on PATH (alloy needs Python 3.8+)." >&2
  exit 1
fi

mkdir -p "$SKILLS_DIR"

if [ -L "$LINK" ]; then
  echo "Updating existing symlink: $LINK"
  rm "$LINK"
elif [ -e "$LINK" ]; then
  echo "error: $LINK already exists and is not a symlink." >&2
  echo "Move or remove it, then re-run install.sh." >&2
  exit 1
fi

ln -s "$REPO_DIR" "$LINK"
chmod +x "$REPO_DIR/bin/alloy"
echo "Linked $LINK -> $REPO_DIR"
echo

echo "Panel status:"
"$REPO_DIR/bin/alloy" doctor || true
echo
echo "Done. RESTART Claude Code (or open a new session) so it picks up the skill,"
echo "then try:  /alloy doctor   and   /alloy ask <your hard question>"
echo "Optional config:  cp '$REPO_DIR/alloy.config.example' ~/.config/alloy/config"
