# Cursor CLI facts (2026-09-29)

- Binary: ~/.local/bin/cursor-agent and ~/.local/bin/agent -> ~/.local/share/cursor-agent/versions/2026.09.28-64d2043/cursor-agent
- Version: 2026.09.28-64d2043
- Status: ✓ Logged in as tl***@gmail.com

## --help
```
Usage: agent [options] [command] [prompt...]

Start the Cursor Agent

Arguments:
  prompt                       Initial prompt for the agent

Options:
  -v, --version                Output the version number
  --api-key <key>              API key for authentication (can also use
                               CURSOR_API_KEY env var)
  -H, --header <header>        Add custom header to agent requests (format:
                               'Name: Value', can be used multiple times)
  -e, --endpoint <url>         Target API endpoint URL (can also use
                               CURSOR_API_ENDPOINT env var) (default:
                               "https://api2.cursor.sh", env:
                               CURSOR_API_ENDPOINT)
  -p, --print                  Print responses to console (for scripts or
                               non-interactive use). Has access to all tools,
                               including write and shell. (default: false)
  --output-format <format>     Output format (only works with --print): text |
                               json | stream-json (default: "text")
  --stream-partial-output      Stream partial output as individual text deltas
                               (only works with --print and stream-json format)
                               (default: false)
  --mode <mode>                Start in the given execution mode. plan:
                               read-only/planning (analyze, propose plans, no
                               edits). ask: Q&A style for explanations and
                               questions (read-only). (choices: "plan", "ask")
  --plan                       Start in plan mode (shorthand for --mode=plan).
                               (default: false)
  --resume [chatId]            Select a session to resume (default: false)
  --continue                   Continue previous session (default: false)
  --model <model>              Model to use (e.g., gpt-5, sonnet-4-thinking).
                               Parameterized models accept quoted bracket
                               overrides, e.g.
                               'claude-opus-4-8[context=1m,effort=high,fast=false]'
  --list-models                List available models and exit (default: false)
  -f, --force                  Force allow commands unless explicitly denied
                               (default: false)
  --yolo                       Alias for --force (Run Everything) (default:
                               false)
  --auto-review                Use Auto-review (Smart Auto): a server classifier
                               auto-runs safe tool calls and prompts for the
                               rest (default: false)
  --sandbox <mode>             Explicitly enable or disable sandbox mode
                               (overrides config) (choices: "enabled",
                               "disabled")
  --approve-mcps               Automatically approve all MCP servers (default:
                               false)
  --trust                      Trust the current workspace without prompting
                               (default: false)
  --workspace <path-or-name>   Workspace directory or saved workspace name to
                               use (defaults to current working directory)
  --add-dir <path>             Add an additional workspace root directory (can
                               be specified multiple times)
  --plugin-dir <path>          Load a local plugin directory (can be specified
                               multiple times)
  -w, --worktree [name]        Start in an isolated git worktree at
                               ~/.cursor/worktrees/<reponame>/<name>. If
                               omitted, a name is generated.
  --worktree-base <branch>     Branch or ref to base the new worktree on
                               (default: current HEAD)
  --skip-worktree-setup        Skip running worktree setup scripts from
                               .cursor/worktrees.json (default: false)
  -h, --help                   Display help for command

Commands:
  persist                      Start or manage a session that survives terminal
                               disconnects
  install-shell-integration    Install shell integration to ~/.zshrc
  uninstall-shell-integration  Remove shell integration from ~/.zshrc
  login                        Authenticate with Cursor. Set NO_OPEN_BROWSER to
                               disable browser opening.
  logout                       Sign out and clear stored authentication
  mcp                          Manage MCP servers
  plugin                       Manage plugins and plugin marketplaces
  worker [options]             Run a self-hosted Cloud Agent worker that
                               connects to Cursor and executes agent tool calls
                               on this machine. Without --pool it is a personal
                               My Machines worker (no Enterprise plan needed);
                               with --pool it joins a team Self-Hosted Pool
                               (Enterprise plan + service account API key).
  status|whoami [options]      View authentication status
  models                       List available models for this account
  team                         View or switch the active team for this account
  bedrock                      Configure AWS Bedrock usage for CLI
  about [options]              Display version, system, and account information
  update                       Update Cursor Agent to the latest version
  create-chat                  Create a new empty chat and return its ID
  generate-rule|rule           Generate a new Cursor rule with interactive
                               prompts
  agent [prompt...]            Start the Cursor Agent
  ls                           Resume a chat session
  resume                       Resume the latest chat session
  help [command]               Display help for command
```

## --list-models
```
Available models

auto - Auto (current, default)
gpt-5.3-codex-low - Codex 5.3 Low
gpt-5.3-codex-low-fast - Codex 5.3 Low Fast
gpt-5.3-codex - Codex 5.3
gpt-5.3-codex-fast - Codex 5.3 Fast
gpt-5.3-codex-high - Codex 5.3 High
gpt-5.3-codex-high-fast - Codex 5.3 High Fast
gpt-5.3-codex-xhigh - Codex 5.3 Extra High
gpt-5.3-codex-xhigh-fast - Codex 5.3 Extra High Fast
gpt-5.2 - GPT-5.2
composer-2.5 - Composer 2.5
claude-opus-5-thinking-high - Claude Opus 5 1M Thinking
claude-opus-5-thinking-high-fast - Claude Opus 5 1M Thinking Fast
gpt-5.6-sol-high - GPT-5.6 Sol 1M High
gpt-5.6-sol-high-fast - GPT-5.6 Sol 1M High Fast
gpt-5.6-sol-xhigh - GPT-5.6 Sol 1M Extra High
gpt-5.6-sol-xhigh-fast - GPT-5.6 Sol 1M Extra High Fast
claude-fable-5-thinking-high - Claude Fable 5 1M Thinking (NO ZDR)
claude-fable-5-thinking-xhigh - Claude Fable 5 1M Extra High Thinking (NO ZDR)
cursor-grok-4.5-high - Grok 4.5
cursor-grok-4.5-high-fast - Grok 4.5 Fast
gemini-3.7-flash-high - Gemini 3.7 Flash
claude-sonnet-5-thinking-high - Claude Sonnet 5 1M Thinking
claude-sonnet-5-thinking-xhigh - Claude Sonnet 5 1M Extra High Thinking
gpt-5.6-luna-high - GPT-5.6 Luna 1M High
grok-4.7-low - Grok 4.7  Low
grok-4.7-low-fast - Grok 4.7  Low Fast​​
grok-4.7-medium - Grok 4.7  Medium
grok-4.7-medium-fast - Grok 4.7  Medium Fast​​
grok-4.7-high - Grok 4.7  High
grok-4.7-high-fast - Grok 4.7  High Fast​​
grok-4.7-xhigh - Grok 4.7  Extra High
grok-4.7-xhigh-fast - Grok 4.7  Extra High Fast​​
cursor-grok-4.6-low - Grok 4.6 Low
cursor-grok-4.6-low-fast - Grok 4.6 Low Fast
cursor-grok-4.6-medium - Grok 4.6 Medium
cursor-grok-4.6-medium-fast - Grok 4.6 Medium Fast
cursor-grok-4.6-high - Grok 4.6
cursor-grok-4.6-high-fast - Grok 4.6 Fast
cursor-grok-4.6-xhigh - Grok 4.6 Extra High
cursor-grok-4.6-xhigh-fast - Grok 4.6 Extra High Fast
composer-2.5-fast - Composer 2.5 Fast
claude-opus-5-5-low - Claude Opus 5.5 1M Low
claude-opus-5-5-low-fast - Claude Opus 5.5 1M Low Fast
claude-opus-5-5-medium - Claude Opus 5.5 1M
claude-opus-5-5-medium-fast - Claude Opus 5.5 1M Fast
claude-opus-5-5-high - Claude Opus 5.5 1M High
claude-opus-5-5-high-fast - Claude Opus 5.5 1M High Fast
claude-opus-5-5-xhigh - Claude Opus 5.5 1M Extra High
claude-opus-5-5-xhigh-fast - Claude Opus 5.5 1M Extra High Fast
claude-opus-5-5-max - Claude Opus 5.5 1M Max
claude-opus-5-5-max-fast - Claude Opus 5.5 1M Max Fast
claude-opus-5-low - Claude Opus 5 1M Low
claude-opus-5-low-fast - Claude Opus 5 1M Low Fast
claude-opus-5-medium - Claude Opus 5 1M Medium
claude-opus-5-medium-fast - Claude Opus 5 1M Medium Fast
claude-opus-5-high - Claude Opus 5 1M
claude-opus-5-high-fast - Claude Opus 5 1M Fast
claude-opus-5-thinking-low - Claude Opus 5 1M Low Thinking
claude-opus-5-thinking-low-fast - Claude Opus 5 1M Low Thinking Fast
claude-opus-5-thinking-medium - Claude Opus 5 1M Medium Thinking
claude-opus-5-thinking-medium-fast - Claude Opus 5 1M Medium Thinking Fast
claude-opus-5-thinking-xhigh - Claude Opus 5 1M Extra High Thinking
claude-opus-5-thinking-xhigh-fast - Claude Opus 5 1M Extra High Thinking Fast
claude-opus-5-thinking-max - Claude Opus 5 1M Max Thinking
claude-opus-5-thinking-max-fast - Claude Opus 5 1M Max Thinking Fast
claude-opus-4-8-low - Claude Opus 4.8 1M Low
claude-opus-4-8-low-fast - Claude Opus 4.8 1M Low Fast
claude-opus-4-8-medium - Claude Opus 4.8 1M Medium
claude-opus-4-8-medium-fast - Claude Opus 4.8 1M Medium Fast
claude-opus-4-8-high - Claude Opus 4.8 1M
claude-opus-4-8-high-fast - Claude Opus 4.8 1M Fast
claude-opus-4-8-xhigh - Claude Opus 4.8 1M Extra High
claude-opus-4-8-xhigh-fast - Claude Opus 4.8 1M Extra High Fast
claude-opus-4-8-max - Claude Opus 4.8 1M Max
claude-opus-4-8-max-fast - Claude Opus 4.8 1M Max Fast
claude-opus-4-8-thinking-low - Claude Opus 4.8 1M Low Thinking
claude-opus-4-8-thinking-low-fast - Claude Opus 4.8 1M Low Thinking Fast
claude-opus-4-8-thinking-medium - Claude Opus 4.8 1M Medium Thinking
claude-opus-4-8-thinking-medium-fast - Claude Opus 4.8 1M Medium Thinking Fast
claude-opus-4-8-thinking-high - Claude Opus 4.8 1M Thinking
claude-opus-4-8-thinking-high-fast - Claude Opus 4.8 1M Thinking Fast
claude-opus-4-8-thinking-xhigh - Claude Opus 4.8 1M Extra High Thinking
claude-opus-4-8-thinking-xhigh-fast - Claude Opus 4.8 1M Extra High Thinking Fast
claude-opus-4-8-thinking-max - Claude Opus 4.8 1M Max Thinking
claude-opus-4-8-thinking-max-fast - Claude Opus 4.8 1M Max Thinking Fast
gpt-5.6-sol-none - GPT-5.6 Sol 1M None
gpt-5.6-sol-none-fast - GPT-5.6 Sol 1M None Fast
gpt-5.6-sol-low - GPT-5.6 Sol 1M Low
gpt-5.6-sol-low-fast - GPT-5.6 Sol 1M Low Fast
gpt-5.6-sol-medium - GPT-5.6 Sol 1M
gpt-5.6-sol-medium-fast - GPT-5.6 Sol 1M Fast
gpt-5.6-sol-max - GPT-5.6 Sol 1M Max
gpt-5.6-sol-max-fast - GPT-5.6 Sol 1M Max Fast
gpt-5.5-none - GPT-5.5 1M None
gpt-5.5-none-fast - GPT-5.5 None Fast
gpt-5.5-low - GPT-5.5 1M Low
gpt-5.5-low-fast - GPT-5.5 Low Fast
gpt-5.5-medium - GPT-5.5 1M
gpt-5.5-medium-fast - GPT-5.5 Fast
gpt-5.5-high - GPT-5.5 1M High
gpt-5.5-high-fast - GPT-5.5 High Fast
gpt-5.5-extra-high - GPT-5.5 1M Extra High
gpt-5.5-extra-high-fast - GPT-5.5 Extra High Fast
claude-fable-5-1-low - Claude Fable 5.1 1M Low (NO ZDR)
claude-fable-5-1-medium - Claude Fable 5.1 1M Medium (NO ZDR)
claude-fable-5-1-high - Claude Fable 5.1 1M (NO ZDR)
claude-fable-5-1-xhigh - Claude Fable 5.1 1M Extra High (NO ZDR)
claude-fable-5-1-max - Claude Fable 5.1 1M Max (NO ZDR)
claude-fable-5-1-thinking-low - Claude Fable 5.1 1M Low Thinking (NO ZDR)
claude-fable-5-1-thinking-medium - Claude Fable 5.1 1M Medium Thinking (NO ZDR)
claude-fable-5-1-thinking-high - Claude Fable 5.1 1M Thinking (NO ZDR)
claude-fable-5-1-thinking-xhigh - Claude Fable 5.1 1M Extra High Thinking (NO ZDR)
claude-fable-5-1-thinking-max - Claude Fable 5.1 1M Max Thinking (NO ZDR)
claude-fable-5-low - Claude Fable 5 1M Low (NO ZDR)
claude-fable-5-medium - Claude Fable 5 1M Medium (NO ZDR)
claude-fable-5-high - Claude Fable 5 1M (NO ZDR)
claude-fable-5-xhigh - Claude Fable 5 1M Extra High (NO ZDR)
claude-fable-5-max - Claude Fable 5 1M Max (NO ZDR)
claude-fable-5-thinking-low - Claude Fable 5 1M Low Thinking (NO ZDR)
claude-fable-5-thinking-medium - Claude Fable 5 1M Medium Thinking (NO ZDR)
claude-fable-5-thinking-max - Claude Fable 5 1M Max Thinking (NO ZDR)
cursor-grok-4.5-low - Grok 4.5 Low
cursor-grok-4.5-low-fast - Grok 4.5 Low Fast
cursor-grok-4.5-medium - Grok 4.5 Medium
cursor-grok-4.5-medium-fast - Grok 4.5 Medium Fast
gemini-3.8-flash-low - Gemini 3.8 Flash Low
gemini-3.8-flash-medium - Gemini 3.8 Flash Medium
gemini-3.8-flash-high - Gemini 3.8 Flash High
gemini-3.7-flash-low - Gemini 3.7 Flash Low
gemini-3.7-flash-medium - Gemini 3.7 Flash Medium
muse-spark-1.3-minimal - Muse Spark 1.3 1M Minimal
muse-spark-1.3-low - Muse Spark 1.3 1M Low
muse-spark-1.3-medium - Muse Spark 1.3 1M Medium
muse-spark-1.3-high - Muse Spark 1.3 1M
muse-spark-1.3-xhigh - Muse Spark 1.3 1M Extra High
muse-spark-1.3-max - Muse Spark 1.3 1M Max
gpt-5.6-terra-none - GPT-5.6 Terra 1M None
gpt-5.6-terra-none-fast - GPT-5.6 Terra 1M None Fast
gpt-5.6-terra-low - GPT-5.6 Terra 1M Low
gpt-5.6-terra-low-fast - GPT-5.6 Terra 1M Low Fast
gpt-5.6-terra-medium - GPT-5.6 Terra 1M
gpt-5.6-terra-medium-fast - GPT-5.6 Terra 1M Fast
gpt-5.6-terra-high - GPT-5.6 Terra 1M High
gpt-5.6-terra-high-fast - GPT-5.6 Terra 1M High Fast
gpt-5.6-terra-xhigh - GPT-5.6 Terra 1M Extra High
gpt-5.6-terra-xhigh-fast - GPT-5.6 Terra 1M Extra High Fast
gpt-5.6-terra-max - GPT-5.6 Terra 1M Max
gpt-5.6-terra-max-fast - GPT-5.6 Terra 1M Max Fast
claude-sonnet-5-5-low - Claude Sonnet 5.5  Low
claude-sonnet-5-5-medium - Claude Sonnet 5.5  Medium
claude-sonnet-5-5-high - Claude Sonnet 5.5  High
claude-sonnet-5-5-xhigh - Claude Sonnet 5.5  Extra High
claude-sonnet-5-5-max - Claude Sonnet 5.5  Max
claude-sonnet-5-low - Claude Sonnet 5 1M Low
claude-sonnet-5-medium - Claude Sonnet 5 1M Medium
claude-sonnet-5-high - Claude Sonnet 5 1M
claude-sonnet-5-xhigh - Claude Sonnet 5 1M Extra High
claude-sonnet-5-max - Claude Sonnet 5 1M Max
claude-sonnet-5-thinking-low - Claude Sonnet 5 1M Low Thinking
claude-sonnet-5-thinking-medium - Claude Sonnet 5 1M Medium Thinking
claude-sonnet-5-thinking-max - Claude Sonnet 5 1M Max Thinking
claude-4.6-sonnet-medium - Claude Sonnet 4.6 1M
claude-4.6-sonnet-medium-thinking - Claude Sonnet 4.6 1M Thinking
claude-opus-4-7-low - Claude Opus 4.7 1M Low
claude-opus-4-7-low-fast - Claude Opus 4.7 1M Low Fast
claude-opus-4-7-medium - Claude Opus 4.7 1M Medium
claude-opus-4-7-medium-fast - Claude Opus 4.7 1M Medium Fast
claude-opus-4-7-high - Claude Opus 4.7 1M High
claude-opus-4-7-high-fast - Claude Opus 4.7 1M High Fast
claude-opus-4-7-xhigh - Claude Opus 4.7 1M
claude-opus-4-7-xhigh-fast - Claude Opus 4.7 1M Fast
claude-opus-4-7-max - Claude Opus 4.7 1M Max
claude-opus-4-7-max-fast - Claude Opus 4.7 1M Max Fast
claude-opus-4-7-thinking-low - Claude Opus 4.7 1M Low Thinking
claude-opus-4-7-thinking-low-fast - Claude Opus 4.7 1M Low Thinking Fast
claude-opus-4-7-thinking-medium - Claude Opus 4.7 1M Medium Thinking
claude-opus-4-7-thinking-medium-fast - Claude Opus 4.7 1M Medium Thinking Fast
claude-opus-4-7-thinking-high - Claude Opus 4.7 1M High Thinking
claude-opus-4-7-thinking-high-fast - Claude Opus 4.7 1M High Thinking Fast
claude-opus-4-7-thinking-xhigh - Claude Opus 4.7 1M Thinking
claude-opus-4-7-thinking-xhigh-fast - Claude Opus 4.7 1M Thinking Fast
claude-opus-4-7-thinking-max - Claude Opus 4.7 1M Max Thinking
claude-opus-4-7-thinking-max-fast - Claude Opus 4.7 1M Max Thinking Fast
gpt-5.4-low - GPT-5.4 1M Low
gpt-5.4-medium - GPT-5.4 1M
gpt-5.4-medium-fast - GPT-5.4 Fast
gpt-5.4-high - GPT-5.4 1M High
gpt-5.4-high-fast - GPT-5.4 High Fast
gpt-5.4-xhigh - GPT-5.4 1M Extra High
gpt-5.4-xhigh-fast - GPT-5.4 Extra High Fast
claude-4.6-opus-high - Claude Opus 4.6 1M
claude-4.6-opus-max - Claude Opus 4.6 1M Max
claude-4.6-opus-high-thinking - Claude Opus 4.6 1M Thinking
claude-4.6-opus-max-thinking - Claude Opus 4.6 1M Max Thinking
claude-4.5-opus-high - Claude Opus 4.5
claude-4.5-opus-high-thinking - Claude Opus 4.5 Thinking
gpt-5.2-low - GPT-5.2 Low
gpt-5.2-low-fast - GPT-5.2 Low Fast
gpt-5.2-fast - GPT-5.2 Fast
gpt-5.2-high - GPT-5.2 High
gpt-5.2-high-fast - GPT-5.2 High Fast
gpt-5.2-xhigh - GPT-5.2 Extra High
gpt-5.2-xhigh-fast - GPT-5.2 Extra High Fast
gpt-5.6-luna-none - GPT-5.6 Luna 1M None
gpt-5.6-luna-none-fast - GPT-5.6 Luna 1M None Fast
gpt-5.6-luna-low - GPT-5.6 Luna 1M Low
gpt-5.6-luna-low-fast - GPT-5.6 Luna 1M Low Fast
gpt-5.6-luna-medium - GPT-5.6 Luna 1M
gpt-5.6-luna-medium-fast - GPT-5.6 Luna 1M Fast
gpt-5.6-luna-high-fast - GPT-5.6 Luna 1M High Fast
gpt-5.6-luna-xhigh - GPT-5.6 Luna 1M Extra High
gpt-5.6-luna-xhigh-fast - GPT-5.6 Luna 1M Extra High Fast
gpt-5.6-luna-max - GPT-5.6 Luna 1M Max
gpt-5.6-luna-max-fast - GPT-5.6 Luna 1M Max Fast
gemini-3.6-flash-minimal - Gemini 3.6 Flash Minimal
gemini-3.6-flash-low - Gemini 3.6 Flash Low
gemini-3.6-flash-medium - Gemini 3.6 Flash Medium
gemini-3.6-flash-high - Gemini 3.6 Flash
gemini-3.1-pro - Gemini 3.1 Pro
gpt-5.4-mini-none - GPT-5.4 Mini None
gpt-5.4-mini-low - GPT-5.4 Mini Low
gpt-5.4-mini-medium - GPT-5.4 Mini
gpt-5.4-mini-high - GPT-5.4 Mini High
gpt-5.4-mini-xhigh - GPT-5.4 Mini Extra High
gpt-5.4-nano-none - GPT-5.4 Nano None
gpt-5.4-nano-low - GPT-5.4 Nano Low
gpt-5.4-nano-medium - GPT-5.4 Nano
gpt-5.4-nano-high - GPT-5.4 Nano High
gpt-5.4-nano-xhigh - GPT-5.4 Nano Extra High
claude-4.5-sonnet - Claude Sonnet 4.5
claude-4.5-sonnet-thinking - Claude Sonnet 4.5 Thinking
gpt-5.1-low - GPT-5.1 Low
gpt-5.1 - GPT-5.1
gpt-5.1-high - GPT-5.1 High
gemini-3-flash - Gemini 3 Flash
gemini-3.5-flash - Gemini 3.5 Flash
claude-4-sonnet - Claude Sonnet 4
claude-4-sonnet-thinking - Claude Sonnet 4 Thinking
gpt-5-mini - GPT-5 Mini
kimi-k3-low - Kimi K3 Low
kimi-k3-high - Kimi K3 High
kimi-k3-max - Kimi K3
kimi-k2.7-code - Kimi K2.7 Code
glm-5.2-high - GLM 5.2
glm-5.2-max - GLM 5.2 Max

Tip: use --model <id> (or /model <id> in interactive mode) to switch. Parameterized models also accept quoted overrides, e.g. --model 'claude-opus-4-8[context=1m,effort=high,fast=false]'.
```

## Headless smoke test (2026-09-29, empty temp dir)
- `cursor-agent -p --mode ask --output-format json --model <m> --trust "<prompt>"`: composer-2.5 exit 0 in 9 s; gpt-5.6-sol-high exit 0 in 9 s; result "OK" both.
- JSON keys: duration_api_ms, duration_ms, is_error, request_id, result, session_id, subtype, type, usage.
- No keychain prompt from a non-GUI shell; no file written to the working directory; `--mode ask` and `--mode plan` are the documented read-only modes; `-p` alone "has access to all tools, including write and shell".
- Auth: `cursor-agent login` (done by Tom, account tl***@gmail.com). `--api-key` / CURSOR_API_KEY exist but must NOT be used by Alloy (argv/env secret rule).
- Model families (from ids): claude-* = anthropic; gpt-* = openai; gemini-* = google; grok-* and cursor-grok-* = xai; composer-* = cursor; auto = UNKNOWN family (router), so it must never be eligible where family independence matters.
