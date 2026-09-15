#!/bin/zsh
# One-time administrator install for TIM after logout and while the Mac is awake.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  print -u2 'Bitte mit sudo ausführen.'
  exit 1
fi
ROOT=/Users/tim/Documents/TIM/tim
USER_ID=$(id -u tim-user)
for name in com.tim.runtime com.tim.coverage-worker; do
  launchctl bootout "gui/$USER_ID/$name" 2>/dev/null || true
done
for name in com.tim.awake com.tim.ollama com.tim.runtime com.tim.coverage-worker; do
  launchctl bootout system/$name 2>/dev/null || true
  install -o root -g wheel -m 644 "$ROOT/ops/launchd/$name.plist" "/Library/LaunchDaemons/$name.plist"
  launchctl bootstrap system "/Library/LaunchDaemons/$name.plist"
done
print 'TIM 24/7-Systemdienste sind installiert. Status: sudo launchctl print system/com.tim.runtime'
