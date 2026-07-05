#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'USAGE'
用法:
  ./init.sh

说明:
  init.sh 是 Unix/macOS/Linux 的环境探针入口。
  Windows 请使用 .\init.ps1。
  验证与归档请使用 .harness/scripts/harness verify|close <change>。

可选环境变量:
  UNITY_BIN=<path>          指定 Unity 可执行文件
  REQUIRE_UNITY_PROJECT=1   当前目录不是 Unity 项目时失败
  RUN_UNITY_IMPORT=1        执行 Unity 导入/编译
  RUN_EDITMODE=1            执行 EditMode 测试
  RUN_PLAYMODE=1            执行 PlayMode 测试
  RUN_START_COMMAND=1       打开 Unity 编辑器
USAGE
}

is_unity_project() {
  [ -d "Assets" ] && [ -f "Packages/manifest.json" ] && [ -d "ProjectSettings" ]
}

resolve_unity_bin() {
  if [ -n "${UNITY_BIN:-}" ]; then
    echo "$UNITY_BIN"
    return 0
  fi

  if command -v Unity >/dev/null 2>&1; then
    command -v Unity
    return 0
  fi

  if command -v unity >/dev/null 2>&1; then
    command -v unity
    return 0
  fi

  return 1
}

run_unity() {
  local unity_bin="$1"
  shift

  echo "==> Unity: $unity_bin $*"
  "$unity_bin" "$@"
}

if [ "${1:-}" = "help" ] || [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi

echo "==> 当前目录: $PWD"

if command -v openspec >/dev/null 2>&1; then
  echo "==> OpenSpec 活跃变更"
  openspec list || true
else
  echo "==> 未找到 openspec；跳过 OpenSpec 探针"
fi

if ! is_unity_project; then
  message="当前目录不是完整 Unity 项目；缺少 Assets、Packages/manifest.json 或 ProjectSettings。"
  if [ "${REQUIRE_UNITY_PROJECT:-0}" = "1" ]; then
    echo "错误: $message" >&2
    exit 1
  fi

  echo "==> $message"
  echo "==> 按模板/文档仓库处理，跳过 Unity 导入和测试。"
  exit 0
fi

if ! UNITY_BIN_RESOLVED="$(resolve_unity_bin)"; then
  message="未找到 Unity 可执行文件；可通过 UNITY_BIN 指定。"
  if [ "${RUN_UNITY_IMPORT:-0}" = "1" ] || [ "${RUN_EDITMODE:-0}" = "1" ] || [ "${RUN_PLAYMODE:-0}" = "1" ] || [ "${RUN_START_COMMAND:-0}" = "1" ]; then
    echo "错误: $message" >&2
    exit 1
  fi

  echo "==> $message"
  echo "==> 未请求 Unity 动作，环境探针完成。"
  exit 0
fi

echo "==> 使用编辑器: $UNITY_BIN_RESOLVED"

if [ "${RUN_UNITY_IMPORT:-0}" = "1" ]; then
  run_unity "$UNITY_BIN_RESOLVED" -batchmode -quit -nographics -projectPath "$ROOT_DIR" -logFile -
fi

if [ "${RUN_EDITMODE:-0}" = "1" ]; then
  run_unity "$UNITY_BIN_RESOLVED" -batchmode -nographics -projectPath "$ROOT_DIR" \
    -runTests -testPlatform EditMode -testResults "$ROOT_DIR/test-results-editmode.xml" -logFile -
fi

if [ "${RUN_PLAYMODE:-0}" = "1" ]; then
  run_unity "$UNITY_BIN_RESOLVED" -batchmode -projectPath "$ROOT_DIR" \
    -runTests -testPlatform PlayMode -testResults "$ROOT_DIR/test-results-playmode.xml" -logFile -
fi

echo "==> Unity 启动命令:"
printf '    %q' "$UNITY_BIN_RESOLVED" -projectPath "$ROOT_DIR"
printf '\n'

if [ "${RUN_START_COMMAND:-0}" = "1" ]; then
  exec "$UNITY_BIN_RESOLVED" -projectPath "$ROOT_DIR"
fi

echo "==> 环境探针完成。需要实际验证时，请按质量契约设置 RUN_UNITY_IMPORT/RUN_EDITMODE/RUN_PLAYMODE。"
