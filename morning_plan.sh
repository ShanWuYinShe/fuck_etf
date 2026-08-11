#!/bin/zsh
# 晨间预案（v2.0 运行纪律：8:40 执行）
# 作用：采集最新数据（含三源快讯/外盘/份额重仓）→ 运行 v2.0 分析 → 打印隔夜消息与持仓摘要
set -e
set -o pipefail

echo "== 1/2 采集最新数据 =="
./fetch_etf_data.sh

echo ""
echo "== 2/2 v2.0 晨间分析 =="
python3 intraday_etf.py

echo ""
echo "完整报告：.workwork/report/intraday_latest.md"
