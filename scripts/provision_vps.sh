#!/usr/bin/env bash
# One-time VPS setup for Ubuntu 24.04 (Hostinger KVM 2). Run as root on a fresh box:
#   scp scripts/provision_vps.sh root@<vps>:/root/ && ssh root@<vps> bash /root/provision_vps.sh <repo-url>
#
# Before running: add your SSH public key to /root/.ssh/authorized_keys (Hostinger panel does this),
# because this script disables password and root logins. Keep your current session open until you
# have confirmed `ssh app@<vps>` works from a second terminal.
set -euo pipefail

REPO_URL="${1:?usage: provision_vps.sh <git-repo-url>}"
APP_USER=app
APP_DIR=/opt/content-engine

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade
apt-get install -y ca-certificates curl git ufw unattended-upgrades fail2ban

# --- automatic security updates
dpkg-reconfigure -f noninteractive unattended-upgrades

# --- app user with the same SSH keys as root, and docker access
id "$APP_USER" &>/dev/null || adduser --disabled-password --gecos "" "$APP_USER"
install -d -m 700 -o "$APP_USER" -g "$APP_USER" /home/$APP_USER/.ssh
install -m 600 -o "$APP_USER" -g "$APP_USER" /root/.ssh/authorized_keys /home/$APP_USER/.ssh/authorized_keys

# --- SSH: keys only, no root
cat >/etc/ssh/sshd_config.d/99-hardening.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
EOF
sshd -t && systemctl reload ssh

# --- firewall: SSH only (the bot long-polls, nothing listens publicly)
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

# --- Docker Engine from Docker's apt repo
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  >/etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker "$APP_USER"
# Docker publishes ports around ufw; compose binds only 127.0.0.1, so nothing leaks.

# --- app checkout
install -d -o "$APP_USER" -g "$APP_USER" "$APP_DIR"
sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR" || true
sudo -u "$APP_USER" cp -n "$APP_DIR/.env.example" "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"
chmod +x "$APP_DIR/scripts/"*.sh

echo
echo "Done. Next:"
echo "  1. From another terminal: ssh $APP_USER@<vps>   (confirm before closing this session)"
echo "  2. Fill in $APP_DIR/.env"
echo "  3. cd $APP_DIR && docker compose up -d && docker compose ps"
