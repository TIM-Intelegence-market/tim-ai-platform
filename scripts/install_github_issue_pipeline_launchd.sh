#!/bin/zsh
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
mode="${1:-pilot}"
if [[ "$mode" != "pilot" && "$mode" != "production" ]]; then
  print -u2 "Usage: $0 [pilot|production]"
  exit 2
fi
state_dir="$HOME/Library/Application Support/TIM GitHub Worker"
plist_dir="$HOME/Library/LaunchAgents"
plist_path="$plist_dir/com.tim.github-issue-pipeline.plist"
worker_path="$(dirname "$(command -v gh)"):$(dirname "$(command -v codex)"):$(dirname "$(command -v claude)"):/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$state_dir" "$plist_dir"
sed -e "s|__PYTHON__|$(command -v python3)|g" -e "s|__REPOSITORY__|$repo_dir|g" -e "s|__STATE_DIR__|$state_dir|g" -e "s|__MODE__|$mode|g" -e "s|__PATH__|$worker_path|g" "$repo_dir/launchd/com.tim.github-issue-pipeline.plist.template" > "$plist_path"
plutil -lint "$plist_path"
launchctl bootout "gui/$(id -u)" "$plist_path" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist_path"
launchctl kickstart -k "gui/$(id -u)/com.tim.github-issue-pipeline"
print "Installed and started com.tim.github-issue-pipeline."
