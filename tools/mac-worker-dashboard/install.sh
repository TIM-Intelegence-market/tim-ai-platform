#!/bin/zsh
# Builds the read-only Mac worker dashboard and runs it as a LaunchAgent on 127.0.0.1.
set -euo pipefail

tool_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$tool_dir/../.." && pwd)"
port="${1:-8767}"
worker_repo="${TIM_WORKER_REPO:-$HOME/Documents/TIM/mac-issue-worker}"
install_dir="$HOME/Library/Application Support/TIM Mac Worker Dashboard"
log_dir="$HOME/Library/Logs/TIM"
label="com.tim.mac-worker-dashboard"
# Optional, space separated: extra Host names, e.g. the Mac's Tailscale name for `tailscale serve`.
allow_hosts=""
for host in ${=MWD_ALLOW_HOSTS:-}; do
  [[ "$host" =~ '^[A-Za-z0-9.-]+$' ]] || { print -u2 "ungültiger Host: $host"; exit 2; }
  allow_hosts+="<string>--allow-host</string><string>$host</string>"
done
plist_path="$HOME/Library/LaunchAgents/$label.plist"

[[ -f "$HOME/.cargo/env" ]] && source "$HOME/.cargo/env"
cargo build --release --manifest-path "$tool_dir/Cargo.toml"
mkdir -p "$install_dir" "$log_dir" "$HOME/Library/LaunchAgents"
# Copy the binary out of the repo so a later checkout cannot swap it while it runs.
install -m 755 "$tool_dir/target/release/mac-worker-dashboard" "$install_dir/mac-worker-dashboard"
sed -e "s|__BINARY__|$install_dir/mac-worker-dashboard|g" -e "s|__PORT__|$port|g" \
    -e "s|__WORKER_REPO__|$worker_repo|g" -e "s|__GH__|$(command -v gh)|g" -e "s|__LOG_DIR__|$log_dir|g" \
    -e "s|__ALLOW_HOSTS__|$allow_hosts|g" \
    "$repo_dir/launchd/$label.plist.template" > "$plist_path"
plutil -lint "$plist_path"
launchctl bootout "gui/$(id -u)" "$plist_path" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist_path"
print "Mac-Worker-Dashboard läuft: http://127.0.0.1:$port"
