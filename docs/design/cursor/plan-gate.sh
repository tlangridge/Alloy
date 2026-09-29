#!/bin/bash
set -eu
f=docs/design/cursor/CURSOR-PROVIDER-PLAN.md
test -s "$f"
for s in "Public name" "Famil" "Checker" "Maker" "Prompt" "Auth" "Effort" "Usage" "Lane" "Risk"; do grep -qi "$s" "$f" || { echo "missing section about: $s"; exit 1; }; done
n=$(git diff --name-only HEAD | grep -v "^$f$" | wc -l | tr -d ' '); u=$(git ls-files --others --exclude-standard | grep -v "^$f$" | wc -l | tr -d ' ')
[ "$n" = 0 ] && [ "$u" = 0 ] || { echo "other files changed"; exit 1; }
echo PLAN_GATE_OK
