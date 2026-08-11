#!/usr/bin/env bash
# 安装并加载 ETF 自动化任务（macOS launchd）：
#   1) com.etf.morning-plan  ：工作日 08:40 执行晨间预案
#   2) com.etf.market-monitor：工作日 09:25 启动盘中监控（每2分钟采集，15:05 结束）
set -e
set -o pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SRC")"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "自动化安装仅支持 macOS（launchd）；其他系统请直接运行脚本或自行配置计划任务。"
  exit 0
fi

# ---- macOS：launchd ----
LA="$HOME/Library/LaunchAgents"
LOG_DIR="$HOME/Library/Logs"
mkdir -p "$LA"

cp "$SRC/com.etf.morning-plan.plist" "$SRC/com.etf.market-monitor.plist" "$LA/"
for p in "$LA"/com.etf.*.plist; do
  # 用当前项目目录与日志目录替换占位符（支持任意路径）
  sed -i '' "s|__PROJECT_DIR__|$PROJECT_DIR|g; s|__LOG_DIR__|$LOG_DIR|g" "$p"
  plutil -lint "$p" >/dev/null
  label="$(/usr/libexec/PlistBuddy -c 'Print :Label' "$p")"
  launchctl bootout "gui/$(id -u)" "$p" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$p"
  echo "已加载：$label"
done

echo ""
echo "当前 ETF 自动化任务："
launchctl list | grep com.etf || true
