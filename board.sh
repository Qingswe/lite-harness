#!/usr/bin/env bash
# Harness 看板快捷方式：启动网页编辑器。
# 用法: ./board.sh        (默认端口 8777)
#       ./board.sh 9000
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/.harness/dashboard/serve.sh" "$@"
