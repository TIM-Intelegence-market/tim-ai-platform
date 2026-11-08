#!/bin/bash
# TIM: Ersteinrichtung auf Fedora Asahi (Mac mini) – einmal ausführen.
# Installiert Tailscale, SSH-Server, Node.js und Claude Code und startet Claude Code
# zum Anmelden. Fragt einmal nach dem Linux-Passwort (für die Installation).
set -e
echo "== TIM Linux-Ersteinrichtung =="
sudo -v
echo "1/4 Pakete und SSH..."
sudo dnf -y install curl git openssh-server nodejs npm python3 python3-pip postgresql-server tmux >/dev/null
sudo systemctl enable --now sshd
echo "2/4 Tailscale..."
if ! command -v tailscale >/dev/null; then
  sudo dnf -y config-manager addrepo --from-repofile=https://pkgs.tailscale.com/stable/fedora/tailscale.repo 2>/dev/null || \
  sudo dnf -y config-manager --add-repo https://pkgs.tailscale.com/stable/fedora/tailscale.repo
  sudo dnf -y install tailscale >/dev/null
fi
sudo systemctl enable --now tailscaled
echo "   Tailscale-Anmeldung: Es folgt ein Browser-Link, dort mit dem Google-Konto anmelden."
sudo tailscale up --ssh --hostname=zeyirs-mac-mini-linux || true
echo "3/4 Claude Code..."
if ! command -v claude >/dev/null; then
  curl -fsSL https://claude.ai/install.sh | bash
fi
export PATH="$HOME/.local/bin:$PATH"
echo "4/4 Fertig. Jetzt Claude Code anmelden (Browser-Link folgt)."
echo "   Danach: claude remote-control  (oder Claude am Handy: Geräte > neues Gerät)"
claude
