#!/usr/bin/env bash
# 卸载 ETF 自动化任务（macOS launchd），不删除项目文件
set -e

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "自动化卸载仅支持 macOS（launchd）。"
  exit 0
fi

LA="$HOME/Library/LaunchAgents"
for p in "$LA"/com.etf.*.plist; do
  [[ -f "$p" ]] || continue
  label="$(/usr/libexec/PlistBuddy -c 'Print :Label' "$p" 2>/dev/null || basename "$p")"
  launchctl bootout "gui/$(id -u)" "$p" 2>/dev/null || true
  rm -f "$p"
  echo "已移除：$label"
done
echo "如需恢复，运行 automations/install.sh"
