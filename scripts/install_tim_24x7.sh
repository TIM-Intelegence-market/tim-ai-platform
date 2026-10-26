#!/bin/zsh
# One-time administrator install for TIM after logout and while the Mac is awake.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  print -u2 'Bitte mit sudo ausführen.'
  exit 1
fi
TIM_USER=${SUDO_USER:?Bitte mit sudo aus dem eigenen Konto starten.}
TIM_HOME=$(dscl . -read "/Users/$TIM_USER" NFSHomeDirectory | awk '{print $2}')
ROOT=${TIM_ROOT:-$TIM_HOME/Documents/TIM/tim}
USER_ID=$(id -u "$TIM_USER")
wait_for_system_unload() {
  local name="$1"
  for _ in {1..15}; do
    if ! launchctl print "system/$name" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  print -u2 "Systemdienst $name beendet sich nicht rechtzeitig. Installation abgebrochen."
  return 1
}
if [[ ! -f "$TIM_HOME/Library/Application Support/TIM/database-password" ]]; then
  print -u2 'Dienst-Schlüssel fehlt. Zuerst ohne sudo ausführen: .venv/bin/python scripts/provision_tim_daemon_secret.py'
  exit 2
fi
for name in com.tim.runtime com.tim.coverage-worker com.tim.local-qwen-worker; do
  launchctl bootout "gui/$USER_ID/$name" 2>/dev/null || true
done
launchctl bootout system/com.tim.ollama 2>/dev/null || true
wait_for_system_unload com.tim.ollama
rm -f /Library/LaunchDaemons/com.tim.ollama.plist
for name in com.tim.awake com.tim.runtime com.tim.coverage-worker com.tim.local-qwen-worker; do
  launchctl bootout system/$name 2>/dev/null || true
  wait_for_system_unload "$name"
  sed -e "s|/Users/tim/Documents/TIM/tim|$ROOT|g" -e "s|/Users/tim/|$TIM_HOME/|g" -e "s|<string>/Users/tim</string>|<string>$TIM_HOME</string>|g" \
    -e "s|<key>UserName</key><string>tim-user</string>|<key>UserName</key><string>$TIM_USER</string>|g" \
    "$ROOT/ops/launchd/$name.plist" > "/tmp/$name.plist"
  install -o root -g wheel -m 644 "/tmp/$name.plist" "/Library/LaunchDaemons/$name.plist"
  rm -f "/tmp/$name.plist"
  launchctl bootstrap system "/Library/LaunchDaemons/$name.plist"
done
print 'TIM 24/7-Systemdienste sind installiert. Status: sudo launchctl print system/com.tim.runtime'
