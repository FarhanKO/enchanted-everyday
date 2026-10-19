#!/usr/bin/env bash
# One-time VPS setup for Ubuntu 24.04, x86 or ARM. Run as root on a fresh box:
#   Hostinger (root login):
#     scp scripts/provision_vps.sh root@<vps>:/root/ && ssh root@<vps> bash /root/provision_vps.sh <repo-url>
#   Oracle Cloud Always Free (logs in as ubuntu):
#     scp scripts/provision_vps.sh ubuntu@<vps>: && ssh ubuntu@<vps> sudo bash provision_vps.sh <repo-url>
#
# Before running: add your SSH public key in the provider's panel, because this script disables
# password and root logins. The app user gets the keys of whoever ran the script. Keep your current
# session open until you have confirmed `ssh app@<vps>` works from a second terminal.
set -euo pipefail

REPO_URL="${1:?usage: provision_vps.sh <git-repo-url>}"
APP_USER=app
APP_DIR=/opt/content-engine

# Oracle's Ubuntu images ship their own SSH-only iptables rules (netfilter-persistent), and ufw
# would replace that package. Keep Oracle's rules there; use ufw everywhere else.
if dpkg -s netfilter-persistent &>/dev/null; then USE_UFW=false; else USE_UFW=true; fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade
apt-get install -y ca-certificates curl git unattended-upgrades fail2ban
if $USE_UFW; then apt-get install -y ufw; fi

# --- automatic security updates
dpkg-reconfigure -f noninteractive unattended-upgrades

# --- app user with the login user's SSH keys, and docker access. Under sudo that's the user who ran
# it (ubuntu on Oracle, whose root keys only print "log in as ubuntu"); otherwise root.
KEY_HOME=/root
if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != root ]]; then KEY_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6); fi
id "$APP_USER" &>/dev/null || adduser --disabled-password --gecos "" "$APP_USER"
install -d -m 700 -o "$APP_USER" -g "$APP_USER" /home/$APP_USER/.ssh
# keep only the key itself from each line, dropping any options in front of it (command=, no-pty, ...)
grep -oE '(ssh-|ecdsa-|sk-)[^ ]+ [^ ]+( .*)?$' "$KEY_HOME/.ssh/authorized_keys" >/home/$APP_USER/.ssh/authorized_keys
chown "$APP_USER:$APP_USER" /home/$APP_USER/.ssh/authorized_keys
chmod 600 /home/$APP_USER/.ssh/authorized_keys

# --- SSH: keys only, no root
cat >/etc/ssh/sshd_config.d/99-hardening.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
EOF
sshd -t && systemctl reload ssh

# --- firewall: SSH only (the bot long-polls, nothing listens publicly)
if $USE_UFW; then
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow OpenSSH
  ufw --force enable
fi

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
