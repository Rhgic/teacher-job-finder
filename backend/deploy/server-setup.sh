#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/teacher-job-api/backend"

echo "Install system packages..."
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx default-mysql-client

echo "Verify application files and virtual environment..."
cd "$APP_DIR"
if [[ ! -x .venv/bin/python || ! -f .env ]]; then
  echo "Missing .venv or .env. Complete GO_LIVE_COMMANDS.md steps 1-3 as the deploy user first." >&2
  exit 1
fi

echo "Install systemd service..."
cp deploy/teacher-job-api.service /etc/systemd/system/teacher-job-api.service
cp deploy/teacher-job-crawl.service /etc/systemd/system/teacher-job-crawl.service
cp deploy/teacher-job-crawl.timer /etc/systemd/system/teacher-job-crawl.timer
cp deploy/teacher-job-backup.service /etc/systemd/system/teacher-job-backup.service
cp deploy/teacher-job-backup.timer /etc/systemd/system/teacher-job-backup.timer
systemctl daemon-reload
systemctl enable teacher-job-api
systemctl restart teacher-job-api
systemctl enable teacher-job-crawl.timer
systemctl start teacher-job-crawl.timer
systemctl enable teacher-job-backup.timer
systemctl start teacher-job-backup.timer

echo "Done. Next install the IP-only Nginx config and run the acceptance checks."
