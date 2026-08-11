#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF 技术面分析工具

用途：
    输入 ETF 代码列表，读取本地腾讯行情 JSON（日/周/月线），
    计算趋势、动量、量能、波动率、位置等指标，
    按固定规则合成“短线 / 长线”信号并输出 Markdown 与 HTML 报告。

数据来源：
    腾讯行情接口（需先联网拉取，见 fetch_etf_data.sh）
        https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=<市场><代码>,day,,,640,qfq

用法：
    python3 analyze_etf.py                     # 读取 etf_list，输出到 .workwork/report/
    python3 analyze_etf.py --codes 159831,515050
    python3 analyze_etf.py --data-dir .workwork/data --out-dir .workwork/report

免责声明：
    本工具输出为基于公开行情数据的技术面量化信号，仅用于研究参考，
    不构成任何投资建议。基金有跟踪误差、清盘与市场波动风险。
"""

import argparse
import json
import math
import os
import re
from datetime import datetime, timedelta


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- 数据读取

def market_of(code: str) -> str:
    """按交易所习惯判断市场前缀：5/11 开头为沪市，其余默认深市。"""
    return "sh" if code.startswith(("5", "11")) else "sz"


def read_kline(path: str) -> list:
    """读取腾讯 JSON，返回 [(date, open, close, high, low, volume), ...]（时间正序）。"""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return []
    data = raw.get("data", {})
    if not data:
        return []
    key = next(iter(data.keys()))
    node = data[key]
    # qfqday / qfqweek / qfqmonth；部分标的只有未复权 day/week/month
    rows_key = next((k for k in node if k.startswith("qfq")), None)
    if rows_key is None:
        rows_key = next((k for k in node if k in ("day", "week", "month")), None)
    if not rows_key:
        return []
    rows = []
    for r in node[rows_key]:
        try:
            rows.append((r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
        except (IndexError, ValueError):
            continue
    return rows


# ---------------------------------------------------------------- 指标计算

def sma(values: list, n: int) -> list:
    out = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def ema(values: list, n: int) -> list:
    out = [None] * len(values)
    if not values:
        return out
    k = 2.0 / (n + 1)
    prev = values[0]
    out[0] = prev
    for i in range(1, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: list, n: int = 14) -> list:
    """Wilder RSI。"""
    out = [None] * len(values)
    if len(values) <= n:
        return out
    gains, losses = [], []
    for i in range(1, len(values)):
        ch = values[i] - values[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    out[n] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    for i in range(n, len(gains)):
        avg_g = (avg_g * (n - 1) + gains[i]) / n
        avg_l = (avg_l * (n - 1) + losses[i]) / n
        out[i + 1] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    return out


def macd(values: list, fast=12, slow=26, signal=9):
    """返回 (dif, dea, hist)。"""
    ef, es = ema(values, fast), ema(values, slow)
    dif = [None if (a is None or b is None) else a - b for a, b in zip(ef, es)]
    clean = [0.0 if x is None else x for x in dif]
    dea = ema(clean, signal)
    hist = [None if d is None or s is None else (d - s) * 2 for d, s in zip(dif, dea)]
    return dif, dea, hist


def atr(rows: list, n: int = 14) -> list:
    out = [None] * len(rows)
    if len(rows) <= n:
        return out
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = rows[i][3], rows[i][4], rows[i - 1][2]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    prev = sum(trs[:n]) / n
    out[n] = prev
    for i in range(n, len(trs)):
        prev = (prev * (n - 1) + trs[i]) / n
        out[i + 1] = prev
    return out


def boll(values: list, n: int = 20, k: float = 2.0):
    mid = sma(values, n)
    up, low = [None] * len(values), [None] * len(values)
    for i in range(n - 1, len(values)):
        window = values[i - n + 1: i + 1]
        mean = mid[i]
        var = sum((v - mean) ** 2 for v in window) / n
        sd = math.sqrt(var)
        up[i], low[i] = mean + k * sd, mean - k * sd
    return up, mid, low


def pct(a, b):
    if not a or not b or b == 0:
        return None
    return (a / b - 1.0) * 100.0


def max_drawdown(closes: list) -> float:
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            mdd = min(mdd, c / peak - 1.0)
    return mdd * 100.0


def position_in_range(price: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.5
    return (price - lo) / (hi - lo)


def quantile(values: list, q: float) -> float:
    s = sorted(values)
    if not s:
        return 0.0
    idx = (len(s) - 1) * q
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return s[lo]
    return s[lo] * (hi - idx) + s[hi] * (idx - lo)


# ---------------------------------------------------------------- 信号合成

def short_term_signal(m):
    """2 周波段信号：趋势 / 动量 / 量能 / 位置，四维打分。"""
    score, reasons = 0, []

    # 1) 趋势：收盘 vs MA10/MA20（2 周波段的关键均线）
    c, ma10, ma20 = m["close"], m["ma10"], m["ma20"]
    if ma10 and ma20:
        if c > ma10 > ma20:
            score += 1
            reasons.append("MA10>MA20 多头排列")
        elif c < ma10 < ma20:
            score -= 1
            reasons.append("MA10<MA20 空头排列")
        else:
            reasons.append("均线交织，方向不明")
    # MA10 斜率
    if m.get("ma10_slope") is not None:
        if m["ma10_slope"] > 0.3:
            score += 1
            reasons.append("MA10 上行")
        elif m["ma10_slope"] < -0.3:
            score -= 1
            reasons.append("MA10 下行")

    # 2) 动量：快 MACD(6,13,5) + RSI6
    if m["dif"] is not None and m["dea"] is not None:
        if m["dif"] > m["dea"]:
            score += 1
            reasons.append("快 MACD 金叉状态")
        else:
            score -= 1
            reasons.append("快 MACD 死叉状态")
    if m.get("rsi6") is not None:
        if m["rsi6"] >= 70:
            reasons.append(f"RSI6 {m['rsi6']:.0f} 超买")
        elif m["rsi6"] <= 30:
            reasons.append(f"RSI6 {m['rsi6']:.0f} 超卖")

    # 3) 量能
    vr = m["vol_ratio"]
    if vr is not None:
        if vr >= 1.2:
            score += 1
            reasons.append(f"放量（5/20日均量 {vr:.2f}）")
        elif vr <= 0.8:
            score -= 1
            reasons.append(f"缩量（5/20日均量 {vr:.2f}）")
        else:
            reasons.append(f"量能平稳（{vr:.2f}）")

    # 4) 位置：距 10 日高点
    d10 = m.get("dist_10d_high")
    if d10 is not None and d10 >= -2.0:
        score += 1
        reasons.append("贴近 10 日高点")
    elif d10 is not None and d10 <= -8.0:
        score -= 1
        reasons.append("远离 10 日高点")

    if score >= 3:
        tag = "强势"
        advice = "波段趋势与动量共振，可顺势持有 2 周左右；回踩 MA10 低吸，跌破 MA10 离场"
    elif score == 2:
        tag = "偏多"
        advice = "波段偏多但未完全共振，回踩 MA10 关注，站稳 10 日高点可加仓"
    elif score == 1:
        tag = "震荡偏多"
        advice = "波段方向初现但力度一般，观望为主，突破 10 日高点后再介入"
    elif score == 0:
        tag = "方向不明"
        advice = "多空信号纠缠，建议观望，等待 MA10/快 MACD 方向明确"
    elif score == -1:
        tag = "震荡偏弱"
        advice = "反弹力度有限，仓位宜轻；有效站回 MA10 前不追多"
    elif score == -2:
        tag = "偏弱"
        advice = "波段偏弱，反弹到 MA10/MA20 附近减仓，等待止跌企稳信号"
    else:
        tag = "弱势"
        advice = "趋势与动量均不利，回避为主；若博弈超跌反弹，须严格止损并快进快出"
    return tag, score, advice, reasons


def long_term_signal(w, mo, m):
    """周线 + 月线 + 52 周位置合成。"""
    reasons = []
    score = 0

    # 周线趋势
    if w and w.get("ma10") and w.get("ma30") and w.get("ma60"):
        if w["ma10"] > w["ma30"] > w["ma60"]:
            score += 1
            reasons.append("周线多头排列（MA10>MA30>MA60）")
        elif w["ma10"] < w["ma30"] < w["ma60"]:
            score -= 1
            reasons.append("周线空头排列")
        else:
            reasons.append("周线均线纠缠")
    else:
        reasons.append("周线数据缺失，按中性处理")

    # 月线趋势
    if mo and mo.get("ma12") and mo.get("ma24"):
        if mo["ma12"] > mo["ma24"]:
            score += 1
            reasons.append("月线 MA12>MA24，长周期向上")
        else:
            score -= 1
            reasons.append("月线 MA12<MA24，长周期向下")
    else:
        reasons.append("月线数据缺失，按中性处理")

    # 位置：52 周分位
    pos52 = m["pos_52w"]
    if pos52 <= 0.30:
        score += 1
        reasons.append(f"处于 52 周低位区间（分位 {pos52:.0%}）")
    elif pos52 >= 0.75:
        score -= 1
        reasons.append(f"处于 52 周高位区间（分位 {pos52:.0%}）")
    else:
        reasons.append(f"52 周分位居中（{pos52:.0%}）")

    if score >= 2:
        tag = "偏强"
        advice = "大周期趋势向上，回踩周线 MA30/MA60 可分批布局；避免追高"
    elif score == 1:
        tag = "中性偏强"
        advice = "长周期方向未完全一致，适合定投或轻仓分批，待周线趋势确认后加码"
    elif score == 0:
        tag = "中性"
        advice = "大周期方向不明，建议等待月线/周线趋势明朗，或以小额定投参与"
    elif score == -1:
        tag = "中性偏弱"
        advice = "大周期偏弱，不宜重仓；仅适合小仓位左侧分批，并设好总仓位上限"
    else:
        tag = "偏弱"
        advice = "长周期下行，等待趋势反转信号（周线重新多头排列）再考虑布局"
    return tag, score, advice, reasons


# ---------------------------------------------------------------- 单只分析

def analyze_one(code: str, name: str, data_dir: str):
    mk = market_of(code)
    day = read_kline(os.path.join(data_dir, f"day_{code}.json"))
    week = read_kline(os.path.join(data_dir, f"week_{code}.json"))
    month = read_kline(os.path.join(data_dir, f"month_{code}.json"))
    if not day:
        return None

    closes = [r[2] for r in day]
    vols = [r[5] for r in day]
    price = closes[-1]
    d = {}
    d["code"], d["name"] = code, name
    d["date"] = day[-1][0]
    d["close"] = price

    # 均线
    for n in (5, 10, 20, 60, 120, 250):
        line = sma(closes, n)
        d[f"ma{n}"] = line[-1]
    ma10_prev = sma(closes, 10)[-6] if len(closes) >= 15 else None
    d["ma10_slope"] = (d["ma10"] - ma10_prev) / ma10_prev * 100 if ma10_prev else None

    # 动量与波动（短线用 RSI6 + 快 MACD(6,13,5)，适配 2 周波段）
    r6, r14 = rsi(closes, 6), rsi(closes, 14)
    dif, dea, hist = macd(closes, 6, 13, 5)
    d["rsi6"], d["rsi14"] = r6[-1], r14[-1]
    d["dif"], d["dea"], d["hist"] = dif[-1], dea[-1], hist[-1]
    up, mid, low = boll(closes)
    d["boll_up"], d["boll_mid"], d["boll_low"] = up[-1], mid[-1], low[-1]
    atr_line = atr(day, 14)
    d["atr14"] = atr_line[-1]
    d["atr_pct"] = atr_line[-1] / price * 100 if price else None

    # 收益率与波动率
    ret20 = pct(price, closes[-21]) if len(closes) > 21 else None
    ret60 = pct(price, closes[-61]) if len(closes) > 61 else None
    ret120 = pct(price, closes[-121]) if len(closes) > 121 else None
    ret250 = pct(price, closes[-251]) if len(closes) > 251 else None
    d["ret_20d"], d["ret_60d"], d["ret_120d"], d["ret_250d"] = ret20, ret60, ret120, ret250
    rets = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))][-20:]
    d["vol_20d_ann"] = (sum(x * x for x in rets) / len(rets)) ** 0.5 * math.sqrt(252) * 100

    # 量能
    v5 = sum(vols[-5:]) / 5
    v20_prev = sum(vols[-25:-5]) / 20
    d["vol_ratio"] = v5 / v20_prev if v20_prev else None

    # 位置
    hi52 = max(closes[-250:])
    lo52 = min(closes[-250:])
    hi10 = max(closes[-10:])
    d["hi_52w"], d["lo_52w"] = hi52, lo52
    d["pos_52w"] = position_in_range(price, lo52, hi52)
    d["dist_52w_high"] = pct(price, hi52)
    d["dist_52w_low"] = pct(price, lo52)
    d["dist_10d_high"] = pct(price, hi10)
    d["max_dd_250d"] = max_drawdown(closes[-250:])
    d["alltime_high"] = max(closes)
    d["dist_alltime_high"] = pct(price, max(closes))

    # 支撑 / 阻力：近 60 日 swing 高低点；布林上下轨单独保留
    recent = closes[-60:]
    d["support"] = round(min(recent), 3)
    d["resistance"] = round(max(recent), 3)
    d["boll_low"], d["boll_up"] = round(low[-1], 3), round(up[-1], 3)

    # 2 周波段参考：入场（MA10 回踩位）、止损（MA10 下方 0.5×ATR 缓冲）、目标（布林上轨）
    atr_val = atr_line[-1]
    ma10_v = d["ma10"] if d["ma10"] else price
    d["band_entry"] = round(ma10_v, 3)
    d["band_stop"] = round(ma10_v - 0.5 * atr_val, 3)
    d["band_target"] = round(up[-1], 3)
    dist_ma10 = (price / ma10_v - 1) * 100
    if dist_ma10 > 2:
        d["band_zone"] = "追高区（等回踩 MA10）"
    elif dist_ma10 < -1:
        d["band_zone"] = "回调区（等企稳信号）"
    else:
        d["band_zone"] = "回踩区（可操作）"

    # 周线 / 月线
    if week:
        wc = [r[2] for r in week]
        w = {"ma10": sma(wc, 10)[-1], "ma30": sma(wc, 30)[-1], "ma60": sma(wc, 60)[-1],
             "rsi14": rsi(wc, 14)[-1], "close": wc[-1], "date": week[-1][0]}
        w["ret_4w"] = pct(w["close"], wc[-5]) if len(wc) > 5 else None
        w["ret_26w"] = pct(w["close"], wc[-27]) if len(wc) > 27 else None
    else:
        w = {}
    if month:
        mc = [r[2] for r in month]
        mo = {"ma12": sma(mc, 12)[-1], "ma24": sma(mc, 24)[-1],
              "rsi14": rsi(mc, 14)[-1], "close": mc[-1], "date": month[-1][0]}
        mo["ret_12m"] = pct(mo["close"], mc[-13]) if len(mc) > 13 else None
        mo["max_dd_all"] = max_drawdown(mc)
    else:
        mo = {}

    d["weekly"], d["monthly"] = w, mo

    st_tag, st_score, st_advice, st_reasons = short_term_signal(d)
    lt_tag, lt_score, lt_advice, lt_reasons = long_term_signal(w, mo, d)
    d["short"] = {"tag": st_tag, "score": st_score, "advice": st_advice, "reasons": st_reasons}
    d["long"] = {"tag": lt_tag, "score": lt_score, "advice": lt_advice, "reasons": lt_reasons}
    return d


# ---------------------------------------------------------------- 报告生成

def fmt(x, nd=3):
    return "—" if x is None else f"{x:.{nd}f}"


def fmt_pct(x):
    return "—" if x is None else f"{x:+.1f}%"


def read_etf_list(path: str) -> list:
    codes = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.search(r"\d{6}", line)
            if m:
                codes.append(m.group())
    return codes


def build_md(results, gen_time) -> str:
    lines = []
    lines.append(f"# ETF 技术面分析报告（{gen_time}）\n")
    lines.append("> 数据截至各 ETF 最近交易日收盘；指标为公开行情的技术面量化信号，不构成投资建议。\n")
    lines.append("## 一、总览\n")
    lines.append("| 代码 | 名称 | 收盘 | 短线波段(2周) | 长线 | 52周分位 | 20日涨跌 | 250日涨跌 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in results:
        lines.append(
            f"| {r['code']} | {r['name']} | {fmt(r['close'])} | "
            f"{r['short']['tag']}({r['short']['score']:+d}) | {r['long']['tag']}({r['long']['score']:+d}) | "
            f"{r['pos_52w']:.0%} | {fmt_pct(r['ret_20d'])} | {fmt_pct(r['ret_250d'])} |"
        )
    lines.append("\n## 二、逐只详情\n")
    for r in results:
        lines.append(f"### {r['code']} {r['name']}\n")
        lines.append(f"- 最新收盘：{fmt(r['close'])}（{r['date']}）｜52 周区间 {fmt(r['lo_52w'])} ~ {fmt(r['hi_52w'])}｜距高点 {fmt_pct(r['dist_52w_high'])}")
        lines.append(f"- 均线：MA5 {fmt(r['ma5'])} / MA10 {fmt(r['ma10'])} / MA20 {fmt(r['ma20'])} / MA60 {fmt(r['ma60'])} / MA250 {fmt(r['ma250'])}")
        lines.append(f"- 动量：RSI6 {fmt(r['rsi6'], 0)} / RSI14 {fmt(r['rsi14'], 0)}｜快MACD(6,13,5) DIF {fmt(r['dif'], 4)} / DEA {fmt(r['dea'], 4)} / 柱 {fmt(r['hist'], 4)}")
        lines.append(f"- 波动与量能：ATR {fmt(r['atr_pct'], 2)}%｜20 日年化波动 {fmt(r['vol_20d_ann'], 1)}%｜量比 {fmt(r['vol_ratio'], 2)}")
        lines.append(f"- 涨跌幅：20 日 {fmt_pct(r['ret_20d'])} / 60 日 {fmt_pct(r['ret_60d'])} / 250 日 {fmt_pct(r['ret_250d'])}")
        lines.append(f"- 回撤：近 250 日最大回撤 {fmt(r['max_dd_250d'], 1)}%｜距历史高点 {fmt_pct(r['dist_alltime_high'])}")
        lines.append(f"- 关键位：60 日支撑 {fmt(r['support'])} / 阻力 {fmt(r['resistance'])}｜布林下轨 {fmt(r['boll_low'])} / 上轨 {fmt(r['boll_up'])}")
        lines.append(f"- 2 周波段参考（{r.get('band_zone', '—')}）：入场 {fmt(r['band_entry'])}（回踩 MA10）｜止损 {fmt(r['band_stop'])}（MA10−0.5×ATR）｜目标 {fmt(r['band_target'])}（布林上轨）")
        if r["weekly"]:
            w = r["weekly"]
            lines.append(f"- 周线（{w['date']}）：MA10 {fmt(w['ma10'])} / MA30 {fmt(w['ma30'])} / MA60 {fmt(w['ma60'])}｜RSI {fmt(w['rsi14'], 0)}｜4 周 {fmt_pct(w['ret_4w'])} / 26 周 {fmt_pct(w['ret_26w'])}")
        if r["monthly"]:
            mo = r["monthly"]
            lines.append(f"- 月线（{mo['date']}）：MA12 {fmt(mo['ma12'])} / MA24 {fmt(mo['ma24'])}｜RSI {fmt(mo['rsi14'], 0)}｜12 个月 {fmt_pct(mo['ret_12m'])}")
        lines.append("")
        lines.append(f"**短线波段（2 周左右）：{r['short']['tag']}（得分 {r['short']['score']:+d}）**")
        lines.append(f"- 依据：{'；'.join(r['short']['reasons'])}")
        lines.append(f"- 操作思路：{r['short']['advice']}")
        lines.append(f"**长线（6 个月以上）：{r['long']['tag']}（得分 {r['long']['score']:+d}）**")
        lines.append(f"- 依据：{'；'.join(r['long']['reasons'])}")
        lines.append(f"- 操作思路：{r['long']['advice']}")
        lines.append("")
    lines.append("---")
    lines.append("## 三、方法论\n")
    lines.append("1. **数据**：日/周/月前复权 K 线，来自腾讯行情接口。")
    lines.append("2. **短线波段信号（2 周左右）** = 趋势（MA10/MA20 排列与 MA10 斜率）+ 动量（快 MACD 6,13,5 / RSI6）+ 量能（5/20 日均量比）+ 位置（距 10 日高点），得分 −6 ~ +6。")
    lines.append("3. **长线信号** = 周线排列（MA10/30/60）+ 月线排列（MA12/24）+ 52 周位置分位，得分 −4 ~ +3。")
    lines.append("4. **操作思路**由信号档位映射，属于固定规则的参考话术，需结合个人风险偏好与仓位管理。")
    lines.append("")
    lines.append("> 风险提示：技术指标有滞后性；ETF 存在跟踪误差、流动性及清盘风险；本报告不构成投资建议。")
    return "\n".join(lines)


def svg_sparkline(r, w=560, h=180):
    """生成简单的收盘价 + MA20/MA60 迷你走势 SVG。"""
    closes = r["_closes"][-160:]
    ma20 = r["_ma20"][-160:]
    ma60 = r["_ma60"][-160:]
    n = len(closes)
    lo = min(min(closes), min(x for x in ma20 if x), min(x for x in ma60 if x)) * 0.985
    hi = max(max(closes), max(x for x in ma20 if x), max(x for x in ma60 if x)) * 1.015
    pad_l, pad_r, pad_t, pad_b = 8, 8, 10, 8
    x = lambda i: pad_l + (w - pad_l - pad_r) * i / max(n - 1, 1)
    y = lambda v: pad_t + (h - pad_t - pad_b) * (1 - (v - lo) / (hi - lo))

    def path(vals, color, width=1.4):
        pts = []
        for i, v in enumerate(vals):
            if v is None:
                continue
            pts.append(f"{x(i):.1f},{y(v):.1f}")
        return f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="{width}"/>'

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    parts.append(f'<rect width="{w}" height="{h}" fill="#fafafa" rx="6"/>')
    parts.append(f'<line x1="{pad_l}" y1="{y(closes[-1])}" x2="{w - pad_r}" y2="{y(closes[-1])}" stroke="#999" stroke-width="1" stroke-dasharray="4,4"/>')
    parts.append(path(ma60, "#8a8f98", 1.2))
    parts.append(path(ma20, "#d19a2e", 1.2))
    parts.append(path(closes, "#2563eb", 1.6))
    last = closes[-1]
    parts.append(f'<circle cx="{x(n - 1):.1f}" cy="{y(last):.1f}" r="3" fill="#2563eb"/>')
    parts.append(f'<text x="{x(n - 1) - 4:.1f}" y="{max(y(last) - 8, 12):.1f}" font-size="12" fill="#2563eb" text-anchor="end">收盘 {last:.3f}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_html(results, gen_time) -> str:
    css = """
    body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;max-width:1080px;margin:24px auto;padding:0 20px;color:#222;background:#fff}
    h1{font-size:24px} h2{font-size:19px;border-bottom:2px solid #eee;padding-bottom:6px;margin-top:34px} h3{font-size:16px}
    table{border-collapse:collapse;width:100%;font-size:13px}
    th,td{border:1px solid #e5e5e5;padding:7px 9px;text-align:left}
    th{background:#f5f5f5}
    .card{background:#fafafa;border:1px solid #eee;border-radius:10px;padding:16px 20px;margin:14px 0}
    .tag{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;color:#fff}
    .pos{background:#16a34a}.neg{background:#dc2626}.neu{background:#64748b}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    @media(max-width:800px){.grid{grid-template-columns:1fr}}
    .kpi{font-size:12px;color:#555;line-height:1.7}
    .advice{background:#fff;border-left:3px solid #2563eb;padding:8px 12px;margin:8px 0}
    footer{color:#999;font-size:12px;margin:30px 0}
    """
    tag_cls = lambda t: "pos" if t in ("强势", "偏强") else ("neg" if t in ("弱势", "偏弱") else "neu")
    parts = [f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>ETF 分析报告</title>
<style>{css}</style></head><body>
<h1>ETF 技术面分析报告</h1><p>生成时间：{gen_time}｜数据截至各 ETF 最近交易日收盘｜仅作研究参考，不构成投资建议。</p>
<h2>总览</h2><table><tr><th>代码</th><th>名称</th><th>收盘</th><th>短线</th><th>长线</th><th>52周分位</th><th>20日</th><th>250日</th></tr>"""]
    for r in results:
        parts.append(
            f"<tr><td>{r['code']}</td><td>{r['name']}</td><td>{fmt(r['close'])}</td>"
            f"<td><span class='tag {tag_cls(r['short']['tag'])}'>{r['short']['tag']}</span> ({r['short']['score']:+d})</td>"
            f"<td><span class='tag {tag_cls(r['long']['tag'])}'>{r['long']['tag']}</span> ({r['long']['score']:+d})</td>"
            f"<td>{r['pos_52w']:.0%}</td><td>{fmt_pct(r['ret_20d'])}</td><td>{fmt_pct(r['ret_250d'])}</td></tr>"
        )
    parts.append("</table>")
    for r in results:
        parts.append(f"<h2>{r['code']} {r['name']}</h2><div class='card'><div class='grid'>")
        parts.append(f"<div class='kpi'>收盘 <b>{fmt(r['close'])}</b>（{r['date']}）<br>"
                     f"MA5 {fmt(r['ma5'])} / MA10 {fmt(r['ma10'])} / MA20 {fmt(r['ma20'])} / MA60 {fmt(r['ma60'])}<br>"
                     f"RSI6 {fmt(r['rsi6'], 0)} / RSI14 {fmt(r['rsi14'], 0)}｜快MACD 柱 {fmt(r['hist'], 4)}<br>"
                     f"ATR {fmt(r['atr_pct'], 2)}%｜年化波动 {fmt(r['vol_20d_ann'], 1)}%｜量比 {fmt(r['vol_ratio'], 2)}<br>"
                     f"20日 {fmt_pct(r['ret_20d'])} / 60日 {fmt_pct(r['ret_60d'])} / 250日 {fmt_pct(r['ret_250d'])}<br>"
                     f"52周区间 {fmt(r['lo_52w'])}~{fmt(r['hi_52w'])}（分位 {r['pos_52w']:.0%}）<br>"
                     f"波段（{r.get('band_zone', '—')}）：入场 {fmt(r['band_entry'])}｜止损 {fmt(r['band_stop'])}｜目标 {fmt(r['band_target'])}</div>")
        parts.append(svg_sparkline(r))
        parts.append("</div>")
        parts.append(
            f"<div class='advice'><b>短线波段（2 周左右）：<span class='tag {tag_cls(r['short']['tag'])}'>{r['short']['tag']}</span></b> "
            f"{r['short']['advice']}<br><small>{'；'.join(r['short']['reasons'])}</small></div>"
        )
        parts.append(
            f"<div class='advice'><b>长线（6 个月+）：<span class='tag {tag_cls(r['long']['tag'])}'>{r['long']['tag']}</span></b> "
            f"{r['long']['advice']}<br><small>{'；'.join(r['long']['reasons'])}</small></div>"
        )
        parts.append("</div>")
    parts.append(
        "<h2>方法论</h2>"
        "<ol><li>数据：日/周/月前复权 K 线，腾讯行情接口。</li>"
        "<li>短线波段（2 周左右）= 趋势（MA10/20 排列、MA10 斜率）+ 动量（快 MACD 6,13,5 / RSI6）+ 量能（5/20 日均量比）+ 位置（距 10 日高点）。</li>"
        "<li>长线 = 周线排列（MA10/30/60）+ 月线排列（MA12/24）+ 52 周位置分位。</li>"
        "<li>操作思路由档位固定映射，实际决策需结合仓位、止损与个人风险偏好。</li></ol>"
        "<footer>风险提示：技术指标滞后；ETF 存在跟踪误差、流动性及清盘风险；本报告不构成投资建议。</footer></body></html>"
    )
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser(description="ETF 技术面分析工具")
    ap.add_argument("--codes", help="逗号分隔的 ETF 代码，默认读取 etf_list")
    ap.add_argument("--data-dir", default=os.path.join(BASE_DIR, ".workwork", "data"), help="行情 JSON 目录")
    ap.add_argument("--out-dir", default=os.path.join(BASE_DIR, ".workwork", "report"), help="报告输出目录")
    args = ap.parse_args()

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    elif os.path.exists(os.path.join(BASE_DIR, "etf_list")):
        codes = read_etf_list(os.path.join(BASE_DIR, "etf_list"))
    else:
        raise SystemExit("未找到 etf_list，请用 --codes 指定代码")

    # 名称表：优先从实时行情文件读取；缺失时用代码占位
    names = {}
    realtime = os.path.join(args.data_dir, "realtime.txt")
    if os.path.exists(realtime):
        for line in open(realtime, encoding="utf-8"):
            m = re.search(r"v_([a-z]{2}\d{6})=", line)
            if m and "~" in line:
                names[m.group(1)[2:]] = line.split("~")[1]

    os.makedirs(args.out_dir, exist_ok=True)
    results = []
    for code in codes:
        r = analyze_one(code, names.get(code, code), args.data_dir)
        if r is None:
            print(f"警告：{code} 缺少日线数据，跳过")
            continue
        # 供 SVG 使用，不输出到 JSON
        closes = [x[2] for x in read_kline(os.path.join(args.data_dir, f"day_{code}.json"))]
        r["_closes"] = closes
        r["_ma20"] = sma(closes, 20)
        r["_ma60"] = sma(closes, 60)
        results.append(r)

    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = build_md(results, gen_time)
    html = build_html(results, gen_time)

    md_path = os.path.join(args.out_dir, "etf_report.md")
    html_path = os.path.join(args.out_dir, "etf_report.html")
    json_path = os.path.join(args.out_dir, "etf_report.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    public = []
    for r in results:
        rr = {k: v for k, v in r.items() if not k.startswith("_")}
        public.append(rr)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(public, f, ensure_ascii=False, indent=2)

    print(f"完成：{len(results)} 只 ETF")
    print(f"报告：{md_path}")
    print(f"HTML：{html_path}")
    print(f"数据：{json_path}")


if __name__ == "__main__":
    main()
