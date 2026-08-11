#!/usr/bin/env bash
# v2.0 运行纪律：盘中每 2 分钟执行一轮数据采集（仅采集，不分析）
#   ./monitor.sh        # 盘中自动循环，午休与收盘后暂停
#   ./monitor.sh --once # 只采集一轮后退出
set -e
set -o pipefail

cd "$(dirname "$0")"

if [[ "$1" == "--once" ]]; then
  ./fetch_etf_data.sh
  exit 0
fi

if [[ "$1" == "--until-close" ]]; then
  # 供 launchd 盘中监控会话使用：9:25 启动，15:05 自动结束
  while true; do
    h=$(date +%H%M)
    if (( h >= 1505 )); then
      echo "$(date '+%H:%M:%S') 已收盘，监控会话结束"
      exit 0
    fi
    if (( h >= 930 && h <= 1130 )) || (( h >= 1300 && h <= 1500 )); then
      ./fetch_etf_data.sh
    else
      echo "$(date '+%H:%M:%S') 非交易时段，跳过采集"
    fi
    sleep 120
  done
fi

echo "盘中监控已启动：每 2 分钟采集一轮，午休（11:30-13:00）与收盘后自动暂停。Ctrl+C 停止。"
while true; do
  h=$(date +%H%M)
  if (( h >= 930 && h <= 1130 )) || (( h >= 1300 && h <= 1500 )); then
    ./fetch_etf_data.sh
  else
    echo "$(date '+%H:%M:%S') 非交易时段，跳过采集"
  fi
  sleep 120
done
