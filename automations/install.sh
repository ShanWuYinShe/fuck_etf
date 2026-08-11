#!/bin/zsh
# 安装并加载 ETF 自动化任务（launchd）：
#   1) com.etf.morning-plan  ：工作日 08:40 执行晨间预案
#   2) com.etf.market-monitor：工作日 09:25 启动盘中监控（每2分钟采集，15:05 结束）
set -e

SRC="$(cd "$(dirname "$0")" && pwd)"
LA="$HOME/Library/LaunchAgents"
mkdir -p "$LA"

cp "$SRC/com.etf.morning-plan.plist" "$SRC/com.etf.market-monitor.plist" "$LA/"

for p in "$LA"/com.etf.*.plist; do
  plutil -lint "$p" >/dev/null
  label="$(/usr/libexec/PlistBuddy -c 'Print :Label' "$p")"
  launchctl bootout "gui/$(id -u)" "$p" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$p"
  echo "已加载：$label"
done

echo ""
echo "当前 ETF 自动化任务："
launchctl list | grep com.etf || true
