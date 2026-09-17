#!/usr/bin/env bash
# User-level Alloy CLI + skills installation. No sudo or shell-profile edits.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP=0
UNINSTALL=0
DOCTOR=1
for arg in "$@"; do
  case "$arg" in
    --setup) SETUP=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --skip-doctor) DOCTOR=0 ;;
    *) echo "Usage: ./install.sh [--setup] [--skip-doctor] [--uninstall]" >&2; exit 2 ;;
  esac
done
if ! command -v python3 >/dev/null 2>&1; then
  echo 'error: install Python 3.8+ first, then re-run this installer.' >&2
  exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else "Alloy requires Python 3.8+")'
BIN_DIR="${ALLOY_INSTALL_BIN_DIR:-$HOME/.local/bin}"
LINKS=("$BIN_DIR/alloy")
TARGETS=("$REPO_DIR/bin/alloy")
add_skills() {
  LINKS+=("$1/alloy" "$1/alloy-execute" "$1/alloy-usage")
  TARGETS+=("$REPO_DIR" "$REPO_DIR/alloy-execute" "$REPO_DIR/alloy-usage")
}
if [ -n "${SKILLS_DIR:-}" ]; then
  add_skills "$SKILLS_DIR"
else
  if [ -d "$HOME/.claude" ] || command -v claude >/dev/null 2>&1; then
    add_skills "${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
  fi
  if [ -d "$HOME/.codex" ] || command -v codex >/dev/null 2>&1; then
    add_skills "${CODEX_SKILLS_DIR:-$HOME/.codex/skills}"
  fi
  if [ -d "$HOME/.grok" ] || command -v grok >/dev/null 2>&1; then
    add_skills "${GROK_SKILLS_DIR:-$HOME/.grok/skills}"
  fi
  if [ -d "$HOME/.gemini/antigravity" ] || command -v agy >/dev/null 2>&1; then
    add_skills "${AGY_SKILLS_DIR:-$HOME/.gemini/config/skills}"
  fi
fi
# Validate every destination before changing anything.
for i in "${!LINKS[@]}"; do
  link="${LINKS[$i]}"
  target="${TARGETS[$i]}"
  if [ "$UNINSTALL" = 0 ] && { [ -e "$link" ] || [ -L "$link" ]; }; then
    if [ ! -L "$link" ] || [ ! "$link" -ef "$target" ]; then
      echo "error: $link belongs to another installation; choose a different directory or move it first." >&2
      exit 1
    fi
  fi
done
for i in "${!LINKS[@]}"; do
  link="${LINKS[$i]}"
  target="${TARGETS[$i]}"
  if [ "$UNINSTALL" = 1 ]; then
    if [ -L "$link" ] && [ "$link" -ef "$target" ]; then
      rm "$link"
      echo "Removed $link"
    fi
  else
    mkdir -p "$(dirname "$link")"
    if [ ! -L "$link" ]; then ln -s "$target" "$link"; fi
    echo "Ready: $link"
  fi
done
if [ "$UNINSTALL" = 1 ]; then
  echo 'Uninstalled Alloy links. Configuration, credentials and run history retained.'
  exit 0
fi
chmod +x "$REPO_DIR/bin/alloy"
# Print a literal $PATH for the user to paste into their shell configuration.
# shellcheck disable=SC2016
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) printf 'Add this directory to PATH, or invoke %s/alloy directly:\n  export PATH="%s:$PATH"\n' "$BIN_DIR" "$BIN_DIR" ;;
esac
if [ "$DOCTOR" = 1 ]; then "$REPO_DIR/bin/alloy" doctor || true; fi
if [ "$SETUP" = 1 ]; then
  "$REPO_DIR/bin/alloy" setup
else
  printf 'Next: %s/alloy setup\n' "$BIN_DIR"
fi
echo 'Open a new host session to discover the Alloy skills.'
