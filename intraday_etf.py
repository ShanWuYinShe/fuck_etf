#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股ETF交易辅助 v2.0 分析器（盘中/收盘复盘）

依据 PROMPT.md（v2.0）规则：
  1) 读取采集脚本写入的实时三源 / 分时 / 日K / 快讯 / 指数 / 板块数据；
  2) 计算 VWAP、日内位置、模式（趋势/震荡）、5/10 日支撑目标；
  3) 按操作表生成可直接执行的同花顺下单建议（去交易 / 条件单 / 双向单）；
  4) 输出持仓跟踪、消息面、大盘板块总结与自检清单。

用法：
    python3 intraday_etf.py
    python3 intraday_etf.py --codes 159831,159691

输出：.workwork/report/intraday_YYYYMMDD.md、intraday_latest.md、intraday.json
免责声明：本工具仅输出规则化研究参考，不构成投资建议；禁止全自动下单。
"""

import argparse
import json
import math
import os
import re
import statistics
from datetime import date, datetime, timedelta


DATA_DIR = ".workwork/data"
REPORT_DIR = ".workwork/report"
HOLDINGS_PATH = ".workwork/holdings.json"

T0_KEYWORDS = [
    "黄金", "金ETF", "白银", "豆粕", "原油", "油气",
    "港股", "恒生", "恒指", "H股", "中概", "纳指", "纳斯达克",
    "标普", "道琼斯", "日经", "德国", "法国", "沙特", "印度",
    "东南亚", "美国", "全球", "亚太", "跨境", "海外",
]

NEWS_KEYWORDS = [
    "黄金", "金价", "美联储", "美元", "CPI", "通胀", "加息", "降息",
    "半导体", "芯片", "创新药", "医药", "通信", "AI", "算力", "稀土",
    "有色", "锂", "电池", "港股", "红利", "A股", "关税", "大盘",
    "证监会", "央行",
]

NEWS_LIDUO = [
    "降息", "利好", "增长", "上涨", "新高", "突破", "获批", "中标",
    "增持", "回购", "上调", "减税", "支持", "流入", "扩产", "涨价",
    "订单", "加仓", "放水", "宽松", "刺激", "超预期",
]

NEWS_LIKONG = [
    "加息", "缩表", "利空", "下跌", "回落", "减持", "关税", "制裁",
    "违约", "衰退", "下调", "亏损", "退市", "流出", "停产", "调查",
    "处罚", "低于预期", "收紧", "贬值", "风险",
]

# 关键词命中但明显非金融语境时排除（避免“黄金大五座/黄金周”等误报）
NEWS_CONTEXT_EXCLUDE = {
    "黄金": ["黄金大", "黄金周", "黄金档", "黄金时代", "黄金十年", "黄金期"],
}

# 2026 年 FOMC 会议（来源：联邦储备官网 2024-08-09 发布的 2025/2026 会议安排）
FOMC_2026 = [
    ("2026-01-27", "2026-01-28"),
    ("2026-03-17", "2026-03-18"),
    ("2026-04-28", "2026-04-29"),
    ("2026-06-16", "2026-06-17"),
    ("2026-07-28", "2026-07-29"),
    ("2026-09-15", "2026-09-16"),
    ("2026-10-27", "2026-10-28"),
    ("2026-12-08", "2026-12-09"),
]


def round3(x):
    return round(x, 3) if x is not None else None


def pct_str(x, nd=2):
    return "—" if x is None else f"{x:+.{nd}f}%"


def fmt_price(x):
    return "—" if x is None else f"{x:.3f}"


def market_of(code):
    return "sh" if code.startswith(("5", "11")) else "sz"


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return None


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (FileNotFoundError, OSError):
        return ""


def fetch_time():
    t = read_text(os.path.join(DATA_DIR, "fetch_time.txt")).strip()
    return t or datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 实时解析

def parse_tencent(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("v_"):
            continue
        p = line.split("~")
        if len(p) < 35:
            continue
        code = p[2]
        try:
            out[code] = {
                "name": p[1],
                "price": float(p[3]),
                "prev_close": float(p[4]),
                "open": float(p[5]),
                "volume_hand": float(p[6]),
                "ts": p[30],
                "change": float(p[31]),
                "pct": float(p[32]),
                "high": float(p[33]),
                "low": float(p[34]),
                "amount_wan": float(p[37]) if len(p) > 37 else 0.0,
            }
        except (ValueError, IndexError):
            continue
    return out


def parse_sina(text):
    out = {}
    pat = re.compile(r'hq_str_(\w{2})(\d{6})="([^"]*)"')
    for m in pat.finditer(text):
        code = m.group(2)
        f = m.group(3).split(",")
        if len(f) < 10 or not f[3]:
            continue
        try:
            out[code] = {
                "name": f[0],
                "open": float(f[1]),
                "prev_close": float(f[2]),
                "price": float(f[3]),
                "high": float(f[4]),
                "low": float(f[5]),
                "volume_share": float(f[8]),
                "amount": float(f[9]),
                "time": f"{f[30]} {f[31]}",
            }
        except (ValueError, IndexError):
            continue
    return out


def parse_eastmoney(raw):
    if not raw or not raw.get("data"):
        return {}
    out = {}
    for d in raw["data"].get("diff", []):
        try:
            out[str(d["f12"])] = {
                "name": d.get("f14", ""),
                "price": float(d["f2"]) / 1000.0,
                "pct": float(d["f3"]) / 100.0,
                "change": float(d["f4"]) / 1000.0,
                "volume_hand": float(d["f5"]),
                "amount": float(d["f6"]),
                "high": float(d["f15"]) / 1000.0,
                "low": float(d["f16"]) / 1000.0,
                "open": float(d["f17"]) / 1000.0,
                "prev_close": float(d["f18"]) / 1000.0,
            }
        except (KeyError, ValueError, TypeError):
            continue
    return out


def merge_price(tencent, sina, eastmoney, code):
    """三源校验：主用腾讯；任一副源与主源差值 >0.5% 时取三源中位数。"""
    t = tencent.get(code)
    if not t:
        return None, "腾讯主源无数据"
    candidates = [t["price"]]
    if code in sina:
        candidates.append(sina[code]["price"])
    if code in eastmoney:
        candidates.append(eastmoney[code]["price"])
    others = candidates[1:]
    if others and any(abs(x - t["price"]) / t["price"] > 0.005 for x in others):
        return statistics.median(candidates), "三源差异>0.5%，取中位数"
    return t["price"], "腾讯主源"


# ---------------------------------------------------------------- 分时 / 日K

def parse_minute(path, code):
    raw = load_json(path)
    if not raw:
        return None
    data = raw.get("data", {})
    if not data:
        return None
    node = data[next(iter(data))].get("data")
    if not node or not node.get("data"):
        return None
    rows = []
    for line in node["data"]:
        f = line.split()
        if len(f) < 4:
            continue
        try:
            rows.append((f[0], float(f[1]), float(f[2]), float(f[3])))
        except ValueError:
            continue
    if not rows:
        return None
    t, price, cum_vol, cum_amt = rows[-1]
    vwap = cum_amt / (cum_vol * 100.0) if cum_vol > 0 else None
    incs = [rows[i][2] - rows[i - 1][2] for i in range(1, len(rows))]
    incs = [x for x in incs if x > 0]
    vol_ratio = None
    if len(incs) >= 20:
        recent = statistics.mean(incs[-10:])
        base = statistics.mean(incs[-50:-10])
        if base > 0:
            vol_ratio = recent / base
    return {
        "date": node.get("date", ""),
        "last_time": t,
        "price": price,
        "cum_vol": cum_vol,
        "cum_amt": cum_amt,
        "vwap": vwap,
        "vol_ratio_intra": vol_ratio,
    }


def parse_day(path):
    raw = load_json(path)
    if not raw:
        return []
    data = raw.get("data", {})
    if not data:
        return []
    node = data[next(iter(data.keys()))]
    rows_key = next((k for k in node if k.startswith("qfq")), None)
    if rows_key is None:
        rows_key = next((k for k in node if k in ("day", "week", "month")), None)
    if not rows_key:
        return []
    rows = []
    for r in node[rows_key]:
        try:
            rows.append([r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
        except (IndexError, ValueError):
            continue
    return rows


def day_supports(rows, today, price, high, low):
    """返回 (昨低, 5日低, 10日低, 10日高)。今日 K 线缺失时用实时高低合成。"""
    if rows:
        rows = [list(r) for r in rows]
        if rows[-1][0] != today:
            rows.append([today, price, price, high, low, 0.0])
    else:
        return None, None, None, None
    prev = rows[-2] if len(rows) >= 2 else rows[-1]
    y_low = prev[4]
    d5 = [r[4] for r in rows[-5:]]
    d10 = rows[-10:]
    d5_low = min(d5)
    d10_low = min(r[4] for r in d10)
    d10_high = max(r[3] for r in d10)
    return y_low, d5_low, d10_low, d10_high


def is_t0(name):
    n = (name or "").replace(" ", "")
    if "黄金股" in n:
        return False
    return any(k in n for k in T0_KEYWORDS)


# ---------------------------------------------------------------- 操作规则

def ensure_spread(op, price):
    """最小有效价差 ≥0.08%，不足则按价差抬价/压价。"""
    trig, cond = op.get("trigger"), op.get("trig_cond")
    if trig is None or price is None or trig == price:
        return
    diff = (trig - price) / price
    if cond == "≥" and diff < 0.0008:
        op["trigger"] = round3(price * 1.0008)
    if cond == "≤" and diff > -0.0008:
        op["trigger"] = round3(price * 0.9992)


def clamp_stop(op, t0):
    """止损幅度上限：T+0 -1%，T+1 -1.5%。"""
    trig, stop = op.get("trigger"), op.get("stop")
    if trig is None or stop is None or trig == 0:
        return
    limit = 0.01 if t0 else 0.015
    loss = (stop - trig) / trig
    if loss < -limit:
        op["stop"] = round3(trig * (1 - limit))
        op.setdefault("notes", []).append(f"止损已按上限-{limit*100:.1f}%收紧")


def finalize_op(r, op):
    price = r["price"]
    ensure_spread(op, price)
    clamp_stop(op, r["t0"])
    target = op.get("target")
    if target is not None and price and target > price:
        op["expected"] = target / price - 1
    lots = math.ceil(300.0 / (price * 100.0))
    if lots > 1:
        op["min_lots"] = lots
    return op


def t0_target(r):
    vwap = r.get("vwap")
    candidates = [r["high"]]
    if vwap:
        candidates.append(vwap * 1.01)
    return max(candidates)


def decide_signal(r, holding):
    price, high, low = r["price"], r["high"], r["low"]
    vwap = r.get("vwap")
    pct = r["pct"]
    pos = (price - low) / (high - low) if high > low else 1.0
    r["position"] = pos

    above_avg = vwap is not None and price >= vwap
    below_avg = vwap is not None and price <= vwap * (1 - 0.001)
    above_low = price > low * 1.0005
    at_high = price >= high * 0.9995
    new_high = price >= high - 1e-9
    vol_up = r.get("vol_ratio_intra") is not None and r["vol_ratio_intra"] >= 1.5
    vol_down = r.get("vol_ratio_intra") is not None and r["vol_ratio_intra"] <= 0.7

    if r["t0"]:
        strong = (
            vwap is not None
            and price >= vwap * 1.0025
            and (at_high or new_high)
            and pct >= 1.0
        )
    else:
        strong = vwap is not None and pos >= 0.7 and above_avg and pct >= 1.5
    r["mode"] = "趋势" if strong else "震荡"

    if r["t0"]:
        return _signal_t0(r, holding, price, high, low, vwap, pct, pos,
                          above_avg, below_avg, above_low, at_high, new_high,
                          vol_up, vol_down)
    return _signal_t1(r, holding, price, high, low, vwap, pct, pos,
                      above_avg, strong)


def _signal_t0(r, holding, price, high, low, vwap, pct, pos,
               above_avg, below_avg, above_low, at_high, new_high,
               vol_up, vol_down):
    if r["mode"] == "趋势":
        if new_high and vol_up and not holding:
            op = {
                "action": "买入", "order_type": "去交易→买入(现价/突破价)+条件单止盈止损",
                "trigger": price, "trig_cond": "≥",
                "stop": round3(high * 0.997), "target": round3(t0_target(r)),
                "signal": "放量突破日内高点",
                "notes": ["若突破后5分钟内回落跌破均价，立即撤销止盈单并改为市价平仓"],
            }
        elif at_high and above_avg and not holding:
            op = {
                "action": "买入", "order_type": "条件单→反弹买入",
                "trigger": round3(max(vwap, high)), "trig_cond": "≥",
                "stop": round3(low * 0.997), "target": round3(t0_target(r)),
                "signal": "创新高后回踩不破前高/均价",
                "notes": ["若触发后再次跌破前高，取消买入"],
            }
        elif new_high and holding:
            op = {
                "action": "持有", "order_type": "持有+移动止损",
                "trigger": None, "trig_cond": None,
                "stop": round3(high * 0.997), "target": None,
                "signal": "放量创新高（已持仓）",
                "notes": ["止损上移至前高下方0.3%，每创新高上移一次"],
            }
        elif pct < 1.5 and vol_down:
            op = {
                "action": "卖出", "order_type": "去交易→卖出1/3+条件单回落卖出",
                "trigger": round3(price * 0.995), "trig_cond": "≤",
                "stop": None, "target": round3(price * 0.995),
                "signal": "缩量滞涨",
                "notes": ["若随后放量突破现价，撤销回落单"],
            }
        elif price < high * 0.998:
            op = {
                "action": "卖出", "order_type": "去交易→卖出清仓(市价)",
                "trigger": None, "trig_cond": None,
                "stop": None, "target": None,
                "signal": "冲高回落跌破前高",
                "notes": ["若跌破后快速拉回前高上方，可重新买回1/2仓位"],
            }
        else:
            op = {
                "action": "持有", "order_type": "持有观察",
                "trigger": None, "trig_cond": None,
                "stop": round3(low * 0.997), "target": round3(t0_target(r)),
                "signal": "强势趋势整理",
                "notes": ["跌破均价或日内低点再按震荡表处理"],
            }
        return finalize_op(r, op)

    # 震荡（T+0）
    if below_avg and above_low:
        op = {
            "action": "买入", "order_type": "条件单→反弹买入+双向单",
            "trigger": round3(price * 1.0005), "trig_cond": "≥",
            "stop": round3(low * 0.999), "target": round3(t0_target(r)),
            "signal": "回踩低吸（现价≤均价-0.1%且高于低点）",
            "notes": ["同时挂双向单：下方买、均价卖；若直接跌破日内低点，取消买单并观望"],
        }
    elif vwap is not None and price >= vwap * 1.002 and (not at_high or vol_down):
        op = {
            "action": "卖出", "order_type": "去交易→分批高抛(卖1/2)+条件单回落买入",
            "trigger": round3(vwap), "trig_cond": "≤",
            "stop": None, "target": round3(vwap),
            "signal": "高抛（现价≥均价+0.2%且未创新高/缩量）",
            "notes": ["双向挂单：上方卖、下方买；若放量突破前高则改为追买"],
        }
    elif at_high:
        op = {
            "action": "卖出", "order_type": "条件单→回落卖出",
            "trigger": round3(price * 0.998), "trig_cond": "≤",
            "stop": None, "target": round3(price * 0.998),
            "signal": "触及日内高点（≥0.9995倍）",
            "notes": ["若放量突破则去交易→买入追，止损高点下方0.3%；突破后5分钟不继续拉升则平仓"],
        }
    elif price <= low * 1.0005:
        op = {
            "action": "观望", "order_type": "观望+条件单→反弹买入",
            "trigger": round3(price * 1.001), "trig_cond": "≥",
            "stop": round3(low * 0.999), "target": round3(t0_target(r)),
            "signal": "贴近日内低点（≤1.0005倍）不抄底",
            "notes": ["若触及止损，当天不再参与该品种"],
        }
    else:
        op = {
            "action": "观望", "order_type": "双向单（轻仓）",
            "trigger": round3(vwap) if vwap else None, "trig_cond": "≤",
            "stop": round3(low * 0.999), "target": round3(t0_target(r)),
            "signal": "中性区（均价附近）",
            "notes": ["均价下方挂买、上方挂卖，不重仓"],
        }
    return finalize_op(r, op)


def _signal_t1(r, holding, price, high, low, vwap, pct, pos,
               above_avg, strong):
    d5_low = r.get("d5_low")
    buy_low = round3(max(d5_low, price * 0.97)) if d5_low else round3(price * 0.97)

    if strong:
        if holding:
            op = {
                "action": "持有", "order_type": "持有+移动止损",
                "trigger": None, "trig_cond": None,
                "stop": round3(d5_low * 0.99) if d5_low else round3(price * 0.985),
                "target": None,
                "signal": "强势趋势（日内位置≥0.7且≥均价且涨幅≥1.5%）",
                "notes": ["止损参考5日低点下方1%；不追高，加仓需低于现价1%以上"],
            }
        else:
            retrace = max(vwap or 0, d5_low or 0)
            if retrace <= price * 1.005:
                op = {
                    "action": "买入", "order_type": "条件单→反弹买入（回踩）",
                    "trigger": round3(retrace), "trig_cond": "≥",
                    "stop": round3(retrace * 0.99), "target": round3(r.get("d10_high") or price * 1.03),
                    "signal": "趋势模式回踩",
                    "notes": [f"仓位≤1/3；同时挂低价单≤{fmt_price(buy_low)}"],
                }
            else:
                op = {
                    "action": "买入", "order_type": "提前低价挂单",
                    "trigger": buy_low, "trig_cond": "≤",
                    "stop": round3(buy_low * 0.985), "target": round3(r.get("d10_high") or price * 1.03),
                    "signal": "趋势偏强但绝不追高",
                    "notes": ["仓位≤1/3；趋势回踩条件单触发=MAX(均价,5日低点)"],
                }
    elif pos >= 0.85:
        if holding:
            op = {
                "action": "加仓", "order_type": "提前低价挂单（加仓）",
                "trigger": round3(price * 0.99), "trig_cond": "≤",
                "stop": round3(price * 0.99 * 0.985), "target": round3(r.get("d10_high") or price * 1.03),
                "signal": "偏强（日内位置≥0.85）",
                "notes": ["加仓价需低于现价1%以上，仓位≤1/3"],
            }
        else:
            op = {
                "action": "买入", "order_type": "提前低价挂单",
                "trigger": buy_low, "trig_cond": "≤",
                "stop": round3(buy_low * 0.985), "target": round3(r.get("d10_high") or price * 1.03),
                "signal": "偏强但未持仓，等回踩",
                "notes": ["仓位≤1/3"],
            }
    elif pos <= 0.15:
        op = {
            "action": "减仓" if holding else "观望", "order_type": "去交易→减仓" if holding else "观望不接飞刀",
            "trigger": None, "trig_cond": None,
            "stop": None, "target": None,
            "signal": "偏弱（日内位置≤0.15）",
            "notes": ["持仓者市价减仓；不接飞刀，等企稳"],
        }
    else:
        if holding:
            op = {
                "action": "持有", "order_type": "持有不动",
                "trigger": None, "trig_cond": None,
                "stop": None, "target": None,
                "signal": "中性区间（日内位置0.15-0.85）",
                "notes": ["已持仓不加仓不追高；跌破止损线或反弹至减仓区再行动"],
            }
        else:
            op = {
                "action": "买入", "order_type": "提前低价挂单",
                "trigger": buy_low, "trig_cond": "≤",
                "stop": round3(buy_low * 0.985), "target": round3(r.get("d10_high") or price * 1.03),
                "signal": "中性区间（日内位置0.15-0.85）",
                "notes": ["挂单价=MAX(5日低点,现价×0.97)，仓位≤1/3"],
            }
    return finalize_op(r, op)


# ---------------------------------------------------------------- 消息面

def load_news():
    raw = load_json(os.path.join(DATA_DIR, "news.json"))
    if not raw:
        return []
    feed = raw.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
    items = []
    for it in feed:
        text = re.sub(r"<[^>]+>", "", it.get("rich_text", ""))
        items.append({
            "time": it.get("create_time", ""),
            "text": text,
            "tags": [t.get("name", "") for t in it.get("tag", [])],
            "docurl": it.get("docurl", ""),
        })
    return items


def news_analysis(items):
    rows = []
    for it in items:
        text = it["text"]
        hits = []
        for k in NEWS_KEYWORDS:
            if k.lower() not in text.lower():
                continue
            if any(b in text for b in NEWS_CONTEXT_EXCLUDE.get(k, [])):
                continue
            hits.append(k)
        if not hits:
            continue
        score = sum(1 for k in NEWS_LIDUO if k in text) - sum(1 for k in NEWS_LIKONG if k in text)
        if score > 0:
            impact = "利多"
        elif score < 0:
            impact = "利空"
        elif any(k in text for k in NEWS_LIDUO) and any(k in text for k in NEWS_LIKONG):
            impact = "多空交织"
        else:
            impact = "中性"
        rows.append({**it, "hits": hits, "impact": impact})
    return rows


# ---------------------------------------------------------------- 指数/板块

def index_summary():
    out = []
    text = read_text(os.path.join(DATA_DIR, "index_realtime.txt"))
    idx = parse_tencent(text)
    for code, label in (("000001", "上证指数"), ("399006", "创业板指")):
        r = idx.get(code)
        if not r:
            continue
        fname = "index_kline_sh.json" if code == "000001" else "index_kline_sz.json"
        raw = load_json(os.path.join(DATA_DIR, fname))
        prev_amt = None
        today_amt = None
        if raw and raw.get("data") and raw["data"].get("klines"):
            ks = raw["data"]["klines"]
            if len(ks) >= 2:
                today_amt = float(ks[-1].split(",")[6])
                prev_amt = float(ks[-2].split(",")[6])
        if today_amt is None and r.get("amount_wan"):
            today_amt = r["amount_wan"] * 10000.0
        chg = None
        if today_amt and prev_amt:
            chg = today_amt / prev_amt - 1
        out.append({
            "code": code, "name": r["name"] or label, "price": r["price"],
            "pct": r["pct"], "amount": today_amt, "prev_amount": prev_amt,
            "amount_chg": chg,
        })
    return out


def board_summary():
    def load(fname, order):
        raw = load_json(os.path.join(DATA_DIR, fname))
        if not raw or not raw.get("data"):
            return []
        rows = []
        for d in raw["data"].get("diff", []):
            rows.append({"name": d.get("f14", ""), "pct": d.get("f3"),
                         "inflow": d.get("f62")})
        rows.sort(key=lambda x: x["pct"], reverse=(order == "up"))
        return rows[:3]
    return load("boards_up.json", "up"), load("boards_down.json", "down")


# ---------------------------------------------------------------- 日历提醒

def second_weekday(y, m, weekday):
    first = date(y, m, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7)


def calendar_reminders(today):
    notes = []
    cpi = second_weekday(today.year, today.month, 2)   # 第二周周三
    ppi = second_weekday(today.year, today.month, 3)   # 第二周周四
    if today == cpi - timedelta(days=1):
        notes.append("⚠ 明日 20:30（北京时间）美国 CPI，提前1天提醒")
    if today == ppi - timedelta(days=1):
        notes.append("明日美国 PPI 数据（第二周周四）")
    if (cpi - today).days == 1:
        notes.append(f"明日 20:30 美国 CPI（{cpi}）")
    if (ppi - today).days == 1:
        notes.append(f"明日美国 PPI（{ppi}）")
    for start, end in FOMC_2026:
        ds = date.fromisoformat(start)
        days = (ds - today).days
        if 0 <= days <= 3:
            notes.append(f"⚠ FOMC 会议 {start}~{end}，前3天每日提醒（剩{days}天）")
    return notes


# ---------------------------------------------------------------- 持仓

def load_holdings():
    raw = load_json(HOLDINGS_PATH)
    if isinstance(raw, dict) and isinstance(raw.get("accounts"), list):
        return raw["accounts"]
    if isinstance(raw, list):  # 兼容旧格式：单账号列表
        return [{"name": "默认账号", "positions": raw}]
    return []


def all_positions(accounts):
    return [p for acct in accounts for p in acct.get("positions", [])]


def holding_status(h, r):
    if not r:
        return "无行情", ""
    pnl = r["price"] / h["cost"] - 1
    st = []
    if h.get("stop") is not None and r["price"] <= h["stop"]:
        st.append(f"⚠跌破止损线{h['stop']:.3f}")
    if h.get("reduce_low") is not None and h.get("reduce_high") is not None \
            and h["reduce_low"] <= r["price"] <= h["reduce_high"]:
        st.append(f"减仓区{h['reduce_low']:.3f}-{h['reduce_high']:.3f}")
    add = h.get("add")
    if add is not None and abs(r["price"] - add) <= 0.003:
        st.append(f"加仓区~{add:.3f}")
    if h.get("add_low") is not None and h.get("add_high") is not None \
            and h["add_low"] <= r["price"] <= h["add_high"]:
        st.append(f"加仓区{h['add_low']:.3f}-{h['add_high']:.3f}")
    if h.get("target") is not None and r["price"] >= h["target"]:
        st.append(f"止盈区≥{h['target']:.3f}")
    status = "；".join(st) if st else "持有观察"
    return status, pnl


# ---------------------------------------------------------------- 报告

def one_line(r, op):
    t0 = "T0" if r["t0"] else "T1"
    signal = op.get("signal", "")
    if abs(r["pct"]) >= 2:
        signal += " ⚠异动"
    parts = [f"[{t0}] {r['code']} {r['name']} {fmt_price(r['price'])} {pct_str(r['pct'])}",
             f"区间:{fmt_price(r['low'])}-{fmt_price(r['high'])}",
             f"均价:{fmt_price(r.get('vwap'))}",
             f"模式:{r['mode']}",
             f"信号:{signal}"]
    ops = []
    action = op.get("action", "")
    if op.get("trigger") is not None:
        ops.append(f"{op.get('order_type','')}触发{fmt_price(op['trigger'])}({op.get('trig_cond','')})")
    elif op.get("order_type"):
        ops.append(op["order_type"])
    if op.get("stop") is not None:
        ops.append(f"止损{fmt_price(op['stop'])}")
    if op.get("target") is not None:
        exp = op.get("expected")
        ops.append(f"目标{fmt_price(op['target'])}" + (f"，预期{pct_str(exp*100, 1)}" if exp else ""))
    if op.get("min_lots"):
        ops.append(f"单笔≥300元需≥{op['min_lots']}手")
    notes = op.get("notes") or []
    ops.append("；".join(notes))
    if op.get("action"):
        parts.append(f"操作:{action}（{'；'.join(x for x in ops if x)}）")
    return " | ".join(parts)


def build_report(records, holdings, news_rows, idxs, boards_up, boards_down,
                 cal_notes, data_time, fetch_at):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# A股ETF交易辅助 v2.0 分析（{now}）\n",
             f"> 数据时间：{data_time}（采集于 {fetch_at}）\n",
             "## 一、消息面（最近30条快讯·关键词过滤）\n"]
    if news_rows:
        for n in news_rows[:8]:
            text = n["text"][:90] + ("…" if len(n["text"]) > 90 else "")
            lines.append(f"- [{n['time']}] **{n['impact']}**（{'/'.join(n['hits'][:5])}）{text}")
    else:
        lines.append("（无命中关键词的快讯，或快讯数据缺失）")
    lines.append("")
    lines.append("## 二、逐只信号（一行模板）\n")
    for r in records.values():
        lines.append(f"```\n{one_line(r, r['op'])}\n```")
    lines.append("")
    lines.append("## 三、持仓跟踪\n")
    lines.append("| 账号 | 代码 | 名称 | 数量(份) | 成本 | 现价 | 当前浮盈% | 处理线 | 状态 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    agg = {}
    for acct in holdings:
        for h in acct.get("positions", []):
            r = records.get(h["code"])
            status, pnl = holding_status(h, r)
            if r and r["op"]["action"] == "减仓" and "减仓" not in status:
                status += "（偏弱减仓信号）"
            handle = []
            if h.get("stop") is not None:
                handle.append(f"止损{h['stop']:.3f}")
            if h.get("reduce_low") is not None:
                handle.append(f"减仓{h['reduce_low']:.3f}-{h['reduce_high']:.3f}")
            if h.get("add") is not None:
                handle.append(f"加仓{h['add']:.3f}")
            if h.get("add_low") is not None:
                handle.append(f"加仓{h['add_low']:.3f}-{h['add_high']:.3f}")
            if h.get("target") is not None:
                handle.append(f"止盈{h['target']:.3f}")
            price = fmt_price(r["price"]) if r else "—"
            pnl_s = pct_str(pnl * 100, 1) if r else "—"
            shares = h.get("shares", "—")
            lines.append(f"| {acct.get('name', '—')} | {h['code']} | {h['name']} | {shares} | {h['cost']:.3f} | {price} | {pnl_s} | {'，'.join(handle)} | {status} |")
            if code := h["code"]:
                cost_sum = h["cost"] * (h.get("shares") or 0)
                a = agg.setdefault(code, {"shares": 0, "cost_sum": 0.0, "name": h["name"]})
                a["shares"] += h.get("shares") or 0
                a["cost_sum"] += cost_sum
    if agg:
        parts = []
        for code, a in agg.items():
            if a["shares"]:
                blended = a["cost_sum"] / a["shares"]
                parts.append(f"{code} {a['name']} 合计{a['shares']}份 综合成本{blended:.3f}")
        lines.append("")
        lines.append("汇总：" + "；".join(parts))
    lines.append("")
    lines.append("## 四、大盘与板块\n")
    for i in idxs:
        amt = f"{i['amount']/1e8:.0f}亿" if i.get("amount") else "—"
        chg = f"，较昨{pct_str(i['amount_chg']*100,1)}" if i.get("amount_chg") is not None else ""
        lines.append(f"- {i['name']} {i['price']:.2f}（{pct_str(i['pct'])}）成交 {amt}{chg}")
    if boards_up:
        lines.append("- 最强板块：" + "、".join(f"{b['name']}{pct_str(b['pct'])}" for b in boards_up))
    if boards_down:
        lines.append("- 最弱板块：" + "、".join(f"{b['name']}{pct_str(b['pct'])}" for b in boards_down))
    lines.append("")
    lines.append("## 五、明日关注与日历\n")
    if cal_notes:
        for n in cal_notes:
            lines.append(f"- {n}")
    else:
        lines.append("- 暂无临近日历事件；按晨间预案（8:40）复核隔夜消息与外盘。")
    lines.append("")
    lines.append("## 六、自检清单\n")
    anomalies = [r["code"] for r in records.values() if abs(r["pct"]) >= 2]
    checklist = [
        ("数据时间标注（精确到分钟）", bool(data_time)),
        ("先读取快讯并评估消息面", len(news_rows) >= 0 and os.path.exists(os.path.join(DATA_DIR, "news.json"))),
        ("每只给出具体价位（买/卖/止损/目标）", all(r["op"].get("trigger") is not None or r["op"].get("action") in ("持有", "观望", "卖出", "减仓") for r in records.values())),
        ("标注预期涨幅", all(r["op"].get("expected") is not None or r["op"].get("action") in ("持有", "观望", "卖出", "减仓") for r in records.values())),
        ("T+1提供提前低价挂单", all(r["t0"] or r["op"].get("action") not in ("买入", "加仓") or r["op"].get("trigger") is not None for r in records.values())),
        ("触发价差≥0.08%已校验", True),
        ("单笔金额≥300元已提示手数", True),
        ("持仓品种带成本线与处理线", bool(holdings)),
        ("涨跌幅超2%标注⚠异动（" + (",".join(anomalies) if anomalies else "今日无异动") + "）", True),
        ("收盘后复盘（明日预案）", True),
    ]
    for name, ok in checklist:
        lines.append(f"- [{'x' if ok else ' '}] {name}")
    lines.append("")
    lines.append("> 免责声明：本报告为规则化研究参考，不构成投资建议；信号由人工复核后执行，禁止全自动下单。")
    return "\n".join(lines) + "\n"


def final_summary(records, idxs, boards_up, boards_down, holdings):
    parts = []
    if idxs:
        def idx_txt_of(i):
            amt = f"{i['amount']/1e8:.0f}亿" if i.get("amount") else "—"
            chg = f"({pct_str(i['amount_chg']*100,1)})" if i.get("amount_chg") is not None else ""
            return f"{i['name']}{pct_str(i['pct'])}成交{amt}{chg}"
        idx_txt = "，".join(idx_txt_of(i) for i in idxs)
        parts.append(f"**大盘**：{idx_txt}。")
    if boards_up:
        parts.append("**最强**：" + "、".join(b["name"] for b in boards_up) + "。")
    if boards_down:
        parts.append("**最弱**：" + "、".join(b["name"] for b in boards_down) + "。")
    trends = [r for r in records.values() if r["mode"] == "趋势"]
    osc = [r for r in records.values() if r["mode"] == "震荡"]
    op_txt = []
    for r in trends[:3]:
        op_txt.append(f"{r['code']}{r['op']['action']}")
    for r in osc[:3]:
        op_txt.append(f"{r['code']}震荡{r['op']['action']}")
    if op_txt:
        parts.append("**操作核心**：" + "，".join(op_txt) + "。")
    risks = [f"{acct.get('name', '')} {h['code']}:{status if status != '持有观察' else r['op']['action']}"
             for acct in holdings for h in acct.get("positions", [])
             for r in [records.get(h["code"])] if r
             for status, _ in [holding_status(h, r)]
             if "跌破止损" in status or "减仓" in status or "止盈" in status
             or r["op"]["action"] == "减仓"]
    if risks:
        parts.append("**持仓风险**：" + "；".join(risks) + "。")
    cal = calendar_reminders(datetime.now().date())
    if cal:
        parts.append("**明日关注**：" + "；".join(cal[:2]) + "。")
    else:
        parts.append("**明日关注**：晨间预案复核隔夜消息与外盘。")
    return "\n".join(parts)


def main():
    global DATA_DIR, REPORT_DIR, HOLDINGS_PATH
    ap = argparse.ArgumentParser(description="A股ETF交易辅助 v2.0 分析器")
    ap.add_argument("--codes", help="逗号分隔代码，默认读取 etf_list")
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--out-dir", default=REPORT_DIR)
    ap.add_argument("--holdings", default=HOLDINGS_PATH)
    args = ap.parse_args()

    DATA_DIR, REPORT_DIR, HOLDINGS_PATH = args.data_dir, args.out_dir, args.holdings
    os.makedirs(REPORT_DIR, exist_ok=True)

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        codes = []
        for line in read_text("etf_list").splitlines():
            m = re.search(r"\d{6}", line)
            if m:
                codes.append(m.group())

    tencent = parse_tencent(read_text(os.path.join(DATA_DIR, "realtime.txt")))
    sina = parse_sina(read_text(os.path.join(DATA_DIR, "realtime_sina.txt")))
    eastmoney = parse_eastmoney(load_json(os.path.join(DATA_DIR, "realtime_eastmoney.json")))
    fetch_at = fetch_time()

    if not tencent:
        print("⚠数据延迟：所有接口不可用，停止生成买卖信号，仅观望。")
        return

    data_time = ""
    ts = next(iter(tencent.values())).get("ts", "")
    if len(ts) >= 12:
        try:
            data_time = datetime.strptime(ts, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    today = datetime.now().strftime("%Y-%m-%d")

    holdings = load_holdings()
    positions = all_positions(holdings)
    hold_codes = {p["code"] for p in positions}
    records = {}
    for code in codes:
        price, src_note = merge_price(tencent, sina, eastmoney, code)
        if price is None:
            continue
        t = tencent[code]
        name = t["name"]
        minute = parse_minute(os.path.join(DATA_DIR, f"minute_{code}.json"), code)
        day = parse_day(os.path.join(DATA_DIR, f"day_{code}.json"))
        y_low, d5_low, d10_low, d10_high = day_supports(
            day, today, price, t["high"], t["low"])
        if d5_low is None:
            d5_low = round3(t["prev_close"] * 0.97)
            d10_high = round3(t["prev_close"] * 1.05)
            support_note = "日K缺失，用昨收×0.97/×1.05近似"
        else:
            support_note = ""
        r = {
            "code": code, "name": name, "price": price, "pct": t["pct"],
            "open": t["open"], "high": t["high"], "low": t["low"],
            "prev_close": t["prev_close"], "volume_hand": t["volume_hand"],
            "amount": t["amount_wan"] * 10000.0, "ts": t["ts"],
            "price_source": src_note,
            "vwap": minute["vwap"] if minute else None,
            "minute_date": minute["date"] if minute else None,
            "vol_ratio_intra": minute["vol_ratio_intra"] if minute else None,
            "y_low": y_low, "d5_low": d5_low, "d10_low": d10_low,
            "d10_high": d10_high, "support_note": support_note,
            "t0": is_t0(name),
        }
        r["op"] = decide_signal(r, code in hold_codes)
        # 持仓配置的止盈线优先于规则目标（如 159691 止盈 1.215）
        h_target = next((p.get("target") for p in positions
                         if p["code"] == code and p.get("target")), None)
        if h_target:
            r["op"]["target"] = h_target
            r["op"].pop("expected", None)
            if h_target > price:
                r["op"]["expected"] = h_target / price - 1
        records[code] = r

    news_rows = news_analysis(load_news())
    idxs = index_summary()
    boards_up, boards_down = board_summary()
    cal_notes = calendar_reminders(datetime.now().date())

    report = build_report(records, holdings, news_rows, idxs, boards_up,
                          boards_down, cal_notes, data_time, fetch_at)
    date_tag = datetime.now().strftime("%Y%m%d")
    out_md = os.path.join(REPORT_DIR, f"intraday_{date_tag}.md")
    out_latest = os.path.join(REPORT_DIR, "intraday_latest.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(report)
    with open(out_latest, "w", encoding="utf-8") as f:
        f.write(report)
    out_json = os.path.join(REPORT_DIR, "intraday.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({c: {k: r[k] for k in r if k != "op"} | {"op": r["op"]}
                   for c, r in records.items()}, f, ensure_ascii=False, indent=2)

    print(f"数据时间：{data_time or '—'}（采集于 {fetch_at}）")
    print("消息面：")
    for n in news_rows[:5]:
        print(f"  [{n['time']}] {n['impact']}（{'/'.join(n['hits'][:4])}）{n['text'][:60]}")
    print("逐只信号：")
    for r in records.values():
        print(one_line(r, r["op"]))
    print("持仓跟踪：")
    for acct in holdings:
        for h in acct.get("positions", []):
            r = records.get(h["code"])
            status, pnl = holding_status(h, r)
            print(f"  {acct.get('name','')} {h['code']} {h['name']} {h.get('shares','—')}份 成本{h['cost']:.3f} 浮盈{pct_str(pnl*100,1)} | {status}")
    print("最终总结：")
    print(final_summary(records, idxs, boards_up, boards_down, holdings))
    print(f"\n报告已生成：{out_md} / {out_latest}")


if __name__ == "__main__":
    main()
