#!/usr/bin/env bash
# 晨间预案（v2.0 运行纪律：8:40 执行）
# 作用：采集最新数据（含三源快讯/外盘/份额重仓），供 AI 开盘前分析
set -e
set -o pipefail

cd "$(dirname "$0")"

echo "== 采集最新数据 =="
./fetch_etf_data.sh

echo ""
echo "数据已更新到 .workwork/data/，请将 PROMPT_full.md 与最新数据交给 AI 进行晨间分析。"
