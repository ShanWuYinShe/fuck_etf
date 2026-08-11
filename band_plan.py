#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 2 周波段操作清单：汇总 analyze_etf.py 与 recommend_etf.py 的结果，
输出 .workwork/report/band_plan.md，包含入场 / 止损 / 目标 / 仓位公式与操作纪律。
"""

import json
import os
from datetime import datetime


REPORT_DIR = ".workwork/report"


def fmt(x, nd=3):
    return "—" if x is None else f"{x:.{nd}f}"


def load(name):
    path = os.path.join(REPORT_DIR, name)
    if not os.path.exists(path):
        return []
    return json.load(open(path, encoding="utf-8"))


def row(r):
    return (
        f"| {r['code']} | {r['name']} | {fmt(r['close'])} | {r.get('band_zone', '—')} | "
        f"{fmt(r.get('band_entry'))} | {fmt(r.get('band_stop'))} | {fmt(r.get('band_target'))} | "
        f"{fmt(r.get('atr_pct'), 2)}% | {fmt(r.get('vol_ratio'), 2)} |"
    )


def main():
    owned = load("etf_report.json")
    reco = load("recommend.json")
    if not owned and not reco:
        raise SystemExit("缺少报告数据，请先运行 analyze_etf.py / recommend_etf.py")

    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    date = owned[0]["date"] if owned else reco[0]["date"]
    lines = [
        f"# 2 周波段操作清单（{gen_time}）\n",
        f"> 数据截至 {date} 收盘。入场=回踩 MA10；止损=跌破 MA10 下方 0.5×ATR 缓冲；目标=布林上轨；状态区分回踩区/追高区/回调区。\n",
        "## 一、已记录 ETF（etf_list）\n",
        "| 代码 | 名称 | 收盘 | 状态 | 入场 | 止损 | 目标 | ATR% | 量比 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in owned:
        sig = r["short"]
        lines.append(row(r))
        lines.append(
            f"  - 波段信号：**{sig['tag']}**（{sig['score']:+d}）｜{sig['advice']}"
        )
    lines.append("")
    lines.append("## 二、推荐新标的（与已记录代码/类型不重复）\n")
    if reco:
        lines.append("| 代码 | 名称 | 收盘 | 状态 | 入场 | 止损 | 目标 | ATR% | 量比 |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in reco:
            sig = r["short"]
            lines.append(row(r))
            lines.append(
                f"  - 波段信号：**{sig['tag']}**（{sig['score']:+d}，综合 {r.get('total', '—'):+d}）｜{sig['advice']}"
            )
    else:
        lines.append("（今日无符合条件的新标的）")
    lines.append("")
    lines.append("## 三、仓位参考（按 2 周波段执行）\n")
    lines.append("单笔风险 = 总资金 × 1%～2%；单只仓位 = 单笔风险 ÷ (入场 − 止损)。")
    lines.append("示例：总资金 10 万、单笔风险 1%（1000 元）、入场 1.000、止损 0.950（5% 空间）→ 仓位 ≈ 1000 ÷ 0.05 = 2 万元（20% 仓位）。")
    lines.append("高波动品种（ATR% > 5）建议单笔风险取 1% 且同方向持仓不超过 2 只。")
    lines.append("")
    lines.append("## 四、操作纪律\n")
    lines.append("1. 只在波段信号 ≥ 偏多（+2）时入场，回踩 MA10 不破再买，不追高。")
    lines.append("2. 止损：跌破 MA10 下方 0.5×ATR 缓冲位即离场，不补仓摊平。")
    lines.append("3. 止盈：到达布林上轨 / 10 日高点附近减半仓，余仓跟 MA10 移动止盈。")
    lines.append("4. 时间止损：持仓满 2 周仍未到目标位，无条件离场，等待下一轮信号。")
    lines.append("5. 每月最多同时持有 3～4 只波段仓，避免同方向（同类型）重复下注。")
    lines.append("")
    lines.append("> 风险提示：本清单基于技术面量化信号，不构成投资建议；实际决策请结合仓位与风险承受能力。")

    out = os.path.join(REPORT_DIR, "band_plan.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"波段操作清单已生成：{out}")


if __name__ == "__main__":
    main()
