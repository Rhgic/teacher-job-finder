#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT/dist"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$OUT_DIR/teacher-job-api-$STAMP.tar.gz"

mkdir -p "$OUT_DIR"

export COPYFILE_DISABLE=1

tar \
  --no-xattrs \
  --no-mac-metadata \
  --exclude=".venv" \
  --exclude="__pycache__" \
  --exclude="*.pyc" \
  --exclude=".DS_Store" \
  --exclude="._*" \
  --exclude="teacher_jobs.db" \
  --exclude="generated_resumes" \
  --exclude="backups" \
  --exclude=".crawler_cache" \
  --exclude="dist" \
  -czf "$OUT" \
  -C "$ROOT" \
  .

echo "$OUT"
