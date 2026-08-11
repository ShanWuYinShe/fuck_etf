#!/bin/zsh
# 一键完成：拉数据（v2.0 采集）→ 分析已记录 ETF → 推荐新标的 → 生成波段清单 → v2.0 盘中/复盘分析
set -e
set -o pipefail

cd "$(dirname "$0")"

echo "== 1/5 拉取行情数据（实时三源+分时+快讯+指数+板块） =="
./fetch_etf_data.sh

echo "== 2/5 分析已记录 ETF（2周波段/长线） =="
python3 analyze_etf.py

echo "== 3/5 扫描推荐新标的 =="
python3 recommend_etf.py

echo "== 4/5 生成波段操作清单 =="
python3 band_plan.py

echo "== 5/5 生成 v2.0 盘中/复盘分析 =="
python3 intraday_etf.py

echo ""
echo "全部完成，报告位于 .workwork/report/（etf_report.md / recommend.md / band_plan.md / intraday_latest.md）"
