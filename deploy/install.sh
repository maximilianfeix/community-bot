#!/usr/bin/env bash
# Runs on the server as root, called by .github/workflows/ci.yml after the code was copied to
# /opt/communitybot/app. Safe to run again: it installs what is missing, then restarts the bot.
#
# This script's output ends up in the log of a public repository. It prints no host name, no server
# name and nothing from the environment file.
set -euo pipefail

APP=/opt/communitybot/app
VENV=/opt/communitybot/venv

if ! python3 -c 'import venv, ensurepip' 2>/dev/null; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3 python3-venv >/dev/null
fi
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Python 3.10+ needed" >&2; exit 1; }

id communitybot >/dev/null 2>&1 \
  || useradd --system --home-dir /opt/communitybot --shell /usr/sbin/nologin communitybot
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
# --require-hashes: every package must match the checksum recorded in requirements.txt
"$VENV/bin/pip" install -q --disable-pip-version-check --require-hashes -r "$APP/requirements.txt"

chown -R root:root "$APP"
chown root:root /etc/communitybot.env
chmod 600 /etc/communitybot.env
install -m 644 "$APP/deploy/communitybot.service" /etc/systemd/system/communitybot.service
systemctl daemon-reload
systemctl enable -q communitybot
systemctl restart communitybot

# Give it a moment to log in; a bad token or a crash shows up here instead of silently later.
sleep 8
if ! systemctl is-active -q communitybot; then
  # -o cat: the bot's own lines only, without the server's host name
  journalctl -u communitybot -n 40 --no-pager -o cat >&2
  exit 1
fi
echo "communitybot is running"
