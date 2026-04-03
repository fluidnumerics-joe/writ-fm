#!/bin/bash
# WRIT-FM Operator - Launch Claude Code for maintenance
# Run manually, via cron, or from mac/operator_daemon.sh.

set -euo pipefail

# Cron runs with a minimal PATH; ensure Homebrew-installed CLIs are available.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$HOME/.local/bin"

cd "$(dirname "$0")"

# Read the operator prompt
PROMPT=$(cat mac/operator_prompt.md)

# Launch Claude Code with the prompt
claude -p "$PROMPT" --allowedTools "Bash,Read,Write,Edit,Glob,Grep"
