#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/teacher-job-api"

echo "Install system packages..."
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx

echo "Create virtual environment..."
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

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

echo "Done. Next configure Nginx, HTTPS certificate, and WeChat request domain."
