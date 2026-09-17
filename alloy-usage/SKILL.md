---
name: alloy-usage
description: >-
  Show remaining subscription quota and reset times across local AI providers.
  Use when the user types /alloy-usage or asks for Alloy usage meters.
license: MIT
allowed-tools:
  - Bash
  - Read
---

# Alloy usage

Run the Alloy usage command and render its Markdown output in chat.

1. Prefer `ALLOY_BIN` if set. Otherwise locate `../bin/alloy` relative to this
   directory's real location, or `../alloy/bin/alloy` beside the installed skill.
   If neither exists, report that Alloy needs installation.
2. Run `"$ALLOY_BIN" usage` with the user's supplied usage options, such as
   `--refresh`, `--cached`, or `--format json`. Default to Markdown.
3. Show the returned meter, preserving unknown/stale status and reset times.
   If `--if-changed` returns nothing, say the usage snapshot is unchanged.

This command reads cached or live provider billing data without model inference.
Do not dispatch a panel, invoke Jev, change subscriptions, or redeem reset credits.
