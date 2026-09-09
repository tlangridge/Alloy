#!/usr/bin/env bash
# Install the alloy skill by symlinking this repo into the skill directory of
# every supported host found on this machine, then run doctor so you see your
# panel status immediately. Two links per host: `alloy` (the skill) and
# `alloy-execute` (the /alloy-execute alias, a shim that defers to the skill).
#
# Usage:
#   ./install.sh            # every host present: Claude Code (always),
#                           # Codex (~/.codex), Grok (~/.grok),
#                           # Gemini CLI (~/.gemini), Antigravity/agy
#                           # (~/.gemini/config/skills)
#   SKILLS_DIR=/path ./install.sh   # only this directory (CI / custom)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Python 3 is the only runtime dependency.
if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found on PATH (alloy needs Python 3.8+)." >&2
  exit 1
fi

link_one() {
  local link="$1"
  local target="$2"
  local label="$3"
  if [ -L "$link" ]; then
    echo "Updating existing symlink: $link"
    rm "$link"
  elif [ -e "$link" ]; then
    echo "error: $link already exists and is not a symlink." >&2
    echo "Move or remove it, then re-run install.sh." >&2
    exit 1
  fi
  ln -s "$target" "$link"
  echo "Linked $link -> $target  ($label)"
}

install_links() {
  local skills_dir="$1"
  local label="$2"
  mkdir -p "$skills_dir"
  link_one "$skills_dir/alloy" "$REPO_DIR" "$label"
  link_one "$skills_dir/alloy-execute" "$REPO_DIR/alloy-execute" "$label"
}

if [ -n "${SKILLS_DIR:-}" ]; then
  install_links "$SKILLS_DIR" "custom"
else
  install_links "$HOME/.claude/skills" "Claude Code"
  if [ -d "$HOME/.codex" ]; then
    install_links "${CODEX_SKILLS_DIR:-$HOME/.codex/skills}" "Codex"
  fi
  if [ -d "$HOME/.grok" ]; then
    install_links "${GROK_SKILLS_DIR:-$HOME/.grok/skills}" "Grok"
  fi
  if [ -d "$HOME/.gemini" ]; then
    install_links "${GEMINI_SKILLS_DIR:-$HOME/.gemini/skills}" "Gemini CLI"
  fi
  # Antigravity (agy) reads ~/.gemini/config/skills (via ~/.gemini/antigravity/skills).
  if [ -d "$HOME/.gemini/antigravity" ] || command -v agy >/dev/null 2>&1; then
    install_links "${AGY_SKILLS_DIR:-$HOME/.gemini/config/skills}" "Antigravity (agy)"
  fi
fi

chmod +x "$REPO_DIR/bin/alloy"
echo

echo "Panel status:"
"$REPO_DIR/bin/alloy" doctor || true
echo
echo "Done. RESTART your host CLI (Claude Code, Codex, Grok, Gemini CLI, or agy)"
echo "or open a new session so it picks up the skill, then try:"
echo "  /alloy doctor        /alloy ask <your hard question>"
echo "  /alloy execute <a change you want made>   (alias: /alloy-execute)"
echo "Optional config:  cp '$REPO_DIR/alloy.config.example' ~/.config/alloy/config"
