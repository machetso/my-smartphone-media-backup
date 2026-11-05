#!/bin/sh
# Linux: start My Smartphone Media Backup with the project's own Python environment (.venv).
DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$DIR/.venv/bin/python" ]; then
    exec "$DIR/.venv/bin/python" "$DIR/smartphone_media_backup.py" "$@"
fi
exec python3 "$DIR/smartphone_media_backup.py" "$@"
