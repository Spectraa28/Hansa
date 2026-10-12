#!/usr/bin/env bash
# Prepares a fresh Ubuntu 24.04 EC2 instance to run the Hansa API and sandbox.
# Proposed and not yet run against a real server; read it before running it.
#
#   sudo bash setup-server.sh <git-repository-url | folder-on-this-machine> <api-host-name>
#   e.g. sudo bash setup-server.sh https://github.com/you/hansa.git hansa-api.sverma.online
#
# Safe to run again: each step checks before it changes anything. It never writes secrets;
# you fill in /opt/hansa/.env yourself, and the API is only started once that file is ready.
set -euo pipefail

REPO="${1:?Pass the git repository URL}"
API_HOST="${2:?Pass the API host name, for example hansa-api.sverma.online}"
APP=/opt/hansa

if [ "$(id -u)" -ne 0 ]; then echo "Run with sudo." >&2; exit 1; fi

echo "== Packages"
apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -y -q docker.io caddy git curl sqlite3

echo "== Swap (a 4 GB instance needs headroom while a sandbox image builds)"
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== Service user"
id hansa >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin hansa
usermod -aG docker hansa
systemctl enable --now docker

echo "== Code"
mkdir -p "$APP" && chown hansa:hansa "$APP"
if [ -d "$REPO" ]; then
  # A folder already on this machine (copied over by hand): mirror it, leaving settings and data alone.
  apt-get install -y -q rsync
  rsync -a --delete --exclude /.env --exclude /var --exclude /backend/.venv "$REPO"/ "$APP"/
  chown -R hansa:hansa "$APP"
elif [ -d "$APP/.git" ]; then
  sudo -u hansa git -C "$APP" pull --ff-only
else
  sudo -u hansa git clone --branch main --single-branch "$REPO" "$APP"
fi

echo "== Python environment"
sudo -u hansa -H bash -c 'command -v ~/.local/bin/uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u hansa -H bash -c "cd $APP/backend && ~/.local/bin/uv sync --locked"

echo "== Sandbox base image"
docker image inspect python:3.12-slim >/dev/null 2>&1 || docker pull -q python:3.12-slim

echo "== Settings file"
if [ ! -f "$APP/.env" ]; then
  install -o hansa -g hansa -m 600 "$APP/backend/.env.example" "$APP/.env"
  NEW_ENV=1
fi
install -d -o hansa -g hansa -m 700 "$APP/var"

echo "== HTTPS front (only /auth and /github are reachable from outside)"
sed "s/HANSA_API_HOST/$API_HOST/g" "$APP/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl enable caddy >/dev/null && systemctl restart caddy

echo "== Daily database backup, seven kept"
install -d -o hansa -g hansa -m 700 /var/backups/hansa
cat > /etc/cron.d/hansa-backup <<'CRON'
# A consistent copy of the database every night. Imported source copies are not backed up; they can be re-imported.
17 3 * * * hansa [ -f /opt/hansa/var/auth.sqlite3 ] && sqlite3 /opt/hansa/var/auth.sqlite3 ".backup /var/backups/hansa/auth-$(date +\%F).sqlite3" && ls -1t /var/backups/hansa/auth-*.sqlite3 | tail -n +8 | xargs -r rm --
CRON

echo "== API service"
install -m 644 "$APP/deploy/hansa-api.service" /etc/systemd/system/hansa-api.service
systemctl daemon-reload
systemctl enable hansa-api >/dev/null

if [ "${NEW_ENV:-0}" = 1 ] || ! grep -Eq '^AUTH_SECRET_KEY=.{32,}' "$APP/.env"; then
  cat <<NOTE

Almost done. The API is NOT started yet, because $APP/.env still needs your values.

  sudo -u hansa nano $APP/.env        # fill it in; see README.md and deploy/README.md
  sudo systemctl start hansa-api
  sudo systemctl status hansa-api --no-pager

Set at least: AUTH_SECRET_KEY, APP_URL and FRONTEND_ORIGIN (both the website's https address),
AUTH_COOKIE_SECURE=true, the GitHub and Google sign-in values, the GitHub App values, and the model
gateway values. If you use a GitHub App private key file, put it in $APP/var/ with mode 600.
NOTE
else
  systemctl restart hansa-api
  sleep 3
  systemctl --no-pager --lines=5 status hansa-api || true
fi
echo
echo "Check from your own machine once DNS points here:  curl -s https://$API_HOST/auth/providers"
