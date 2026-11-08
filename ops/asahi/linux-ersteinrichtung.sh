#!/bin/bash
# TIM: Ersteinrichtung auf Fedora Asahi (Mac mini) – einmal ausführen.
# Installiert SSH-Server, Tailscale, Node.js und Claude Code und startet Claude Code
# zum Anmelden. Fragt einmal nach dem Linux-Passwort (für die Installation).
set -e
trap 'echo; echo "FEHLER in Zeile $LINENO. Foto davon an Claude schicken. Enter zum Schließen."; read -r' ERR
echo "== TIM Linux-Ersteinrichtung =="
sudo -v
echo "1/4 Pakete und SSH (dauert ein paar Minuten)..."
sudo dnf -y install curl git openssh-server nodejs npm python3 python3-pip tmux >/dev/null
sudo systemctl enable --now sshd
echo "2/4 Tailscale..."
if ! command -v tailscale >/dev/null; then
  sudo dnf -y config-manager addrepo --from-repofile=https://pkgs.tailscale.com/stable/fedora/tailscale.repo --overwrite 2>/dev/null || \
  sudo dnf -y config-manager --add-repo https://pkgs.tailscale.com/stable/fedora/tailscale.repo
  sudo dnf -y install tailscale >/dev/null
fi
sudo systemctl enable --now tailscaled
echo "   Tailscale-Anmeldung: Es öffnet sich gleich ein Browser-Link, dort mit dem Google-Konto anmelden."
sudo tailscale up --ssh --hostname=zeyirs-mac-mini-linux || true
echo "3/4 Claude Code..."
if ! command -v claude >/dev/null && [ ! -x "$HOME/.local/bin/claude" ]; then
  curl -fsSL https://claude.ai/install.sh | bash
fi
export PATH="$HOME/.local/bin:$PATH"
echo "4/4 Fertig. Jetzt Claude Code anmelden (Browser-Link folgt)."
echo "   Danach in Claude Code tippen: /remote-control"
claude
