#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-8777}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$SCRIPT_DIR/server.py"

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "未找到 python，请先安装 Python 3。" >&2
  exit 1
fi

URL="http://127.0.0.1:$PORT"
# 尝试打开浏览器（不同平台）
( sleep 1
  if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL"
  elif command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v start >/dev/null 2>&1; then start "$URL"
  fi ) >/dev/null 2>&1 &

exec "$PY" "$SERVER" --port "$PORT"
