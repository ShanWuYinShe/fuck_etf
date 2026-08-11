#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
短线强势 ETF 推荐工具

思路（两级筛选）：
    1. 从东方财富拉取全市场 ETF 实时列表（约 1300 只），
       按涨幅/量比/换手初筛出活跃候选（排除 etf_list 中已记录代码）。
    2. 对候选逐个拉取腾讯日线，计算与 analyze_etf.py 一致的短线信号，
       叠加"动量延续"条件（站上短均线、MACD 柱为正且扩张、量能放大、中期动量为正），
       按综合分排序，输出 Top N 推荐。

用法：
    python3 recommend_etf.py                  # 默认推荐 10 只，排除 etf_list
    python3 recommend_etf.py --top 15         # 推荐 15 只
    python3 recommend_etf.py --exclude-list my_list.txt
    python3 recommend_etf.py --fast-mode      # 只做实时快筛，不拉 K 线精算（更快但粗糙）

免责声明：
    推荐基于技术面动量延续假设，是统计意义上的强势候选，不是对行情的确定性预测。
    不构成投资建议，请自行控制仓位与风险。
"""

import argparse
import json
import os
import re
import subprocess
import time

import analyze_etf as ae


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- 数据获取

EM_LIST_HOSTS = (
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://push2delay.eastmoney.com/api/qt/clist/get",
)
EM_LIST_QUERY = (
    "?pn={pn}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3&fs=b:MK0021"
    "&fields=f2,f3,f6,f8,f10,f12,f14"
)


def fetch_em_list(data_dir: str) -> list:
    """拉取全市场 ETF 实时列表：东财主/备域名分页。"""
    cache_path = os.path.join(data_dir, "etf_list_cache.json")

    for host in EM_LIST_HOSTS:
        rows = []
        pn = 1
        ok = False
        complete = True
        while True:
            url = host + EM_LIST_QUERY.format(pn=pn)
            for attempt in range(3):
                try:
                    proc = subprocess.run(
                        ["curl", "-sS", "--max-time", "20", "-A", "Mozilla/5.0", url],
                        check=True,
                        capture_output=True,
                    )
                    raw = json.loads(proc.stdout.decode("utf-8"))
                    ok = True
                    break
                except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError):
                    time.sleep(1.0 + attempt)
            if not ok:
                print(f"  警告：{host} 第 {pn} 页获取失败")
                complete = False
                break
            data = raw.get("data") or {}
            diff = data.get("diff") or []
            rows.extend(diff)
            total = data.get("total", 0)
            uniq_codes = len({str(r.get("f12")) for r in rows if r.get("f12")})
            if uniq_codes >= total or not diff:
                break
            pn += 1
            time.sleep(0.5)
        # 去重 + 完整性校验（接口异常时会返回大量重复行）
        seen, uniq = set(), []
        for r in rows:
            c = str(r.get("f12") or "")
            if c and c not in seen:
                seen.add(c)
                uniq.append(r)
        if ok and complete and uniq and len(uniq) >= (data.get("total") or 0) * 0.8:
            save_list_cache(cache_path, uniq, f"东财 {host.split('/')[2]}")
            return uniq
        if rows:
            print(f"  警告：{host} 列表异常（{len(uniq)} 只唯一代码），不写入缓存，尝试下一数据源")
    return []


def fetch_sina_list(data_dir: str) -> list:
    """回退数据源：新浪财经 ETF 行情节点（全量约 1600 只，含商品 ETF）。"""
    cache_path = os.path.join(data_dir, "etf_list_cache.json")
    rows = []
    page = 1
    complete = True
    while page <= 20:
        url = (
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData?page={}&num=100&sort=changepercent&asc=0"
            "&node=etf_hq_fund&symbol=&_s_r_a=init".format(page)
        )
        try:
            proc = subprocess.run(
                ["curl", "-sS", "--max-time", "15", "-A", "Mozilla/5.0", url],
                check=True,
                capture_output=True,
            )
            batch = json.loads(proc.stdout.decode("utf-8"))
        except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError):
            batch = []
        if not batch:
            if page > 1:
                print(f"  警告：新浪列表第 {page} 页失败，仅获取 {len(rows)} 只，不写入缓存")
                complete = False
            break
        # 统一字段名与东财一致
        for r in batch:
            rows.append({
                "f2": float(r.get("trade") or 0),
                "f3": float(r.get("changepercent") or 0),
                "f6": float(r.get("amount") or 0),
                "f8": float(r.get("turnoverratio") or 0),
                "f10": None,
                "f12": str(r.get("code") or ""),
                "f14": r.get("name") or "",
            })
        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.4)
    seen, uniq = set(), []
    for r in rows:
        c = str(r.get("f12") or "")
        if c and c not in seen:
            seen.add(c)
            uniq.append(r)
    if uniq and complete:
        save_list_cache(cache_path, uniq, "新浪财经 etf_hq_fund")
    return uniq


def save_list_cache(cache_path: str, rows: list, source: str):
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(
            {"fetch_time": time.strftime("%Y-%m-%d %H:%M:%S"), "source": source, "rows": rows},
            f,
            ensure_ascii=False,
        )
    print(f"  列表来源：{source}（{len(rows)} 只）")


def load_list_cache(data_dir: str) -> list:
    cache_path = os.path.join(data_dir, "etf_list_cache.json")
    if os.path.exists(cache_path):
        cached = json.load(open(cache_path, encoding="utf-8"))
        print(
            f"  实时列表获取失败，使用本地缓存（{cached.get('source', '?')}，"
            f"获取于 {cached.get('fetch_time', '?')}，{len(cached['rows'])} 只）"
        )
        return cached["rows"]
    return []


def fetch_etf_list(data_dir: str) -> list:
    """全市场 ETF 列表：东财主/备域名 → 新浪 → 本地缓存。"""
    os.makedirs(data_dir, exist_ok=True)
    rows = fetch_em_list(data_dir)
    if rows:
        return rows
    print("  东财列表不可用，切换新浪…")
    rows = fetch_sina_list(data_dir)
    if rows:
        return rows
    return load_list_cache(data_dir)


def fetch_tencent_day(code: str, data_dir: str, retry: int = 2) -> bool:
    """下载单只 ETF 日线 JSON，成功返回 True。"""
    mk = ae.market_of(code)
    path = os.path.join(data_dir, f"day_{code}.json")
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mk}{code},day,,,640,qfq"
    for _ in range(retry):
        try:
            subprocess.run(
                ["curl", "-sS", "--max-time", "20", "-A", "Mozilla/5.0", url, "-o", path],
                check=True,
                capture_output=True,
            )
            if os.path.getsize(path) > 1000 and ae.read_kline(path):
                return True
        except (subprocess.CalledProcessError, OSError, ValueError):
            pass
        time.sleep(0.5)
    return False


def fetch_tencent_names(codes, data_dir: str) -> dict:
    """从腾讯实时行情批量获取 ETF 名称（GBK 解码），用于已记录代码的类型识别。"""
    if not codes:
        return {}
    query = ",".join(ae.market_of(c) + c for c in codes)
    cache_path = os.path.join(data_dir, "owned_names.json")
    try:
        proc = subprocess.run(
            ["curl", "-sS", "--max-time", "15", f"https://qt.gtimg.cn/q={query}"],
            check=True,
            capture_output=True,
        )
        text = proc.stdout.decode("gbk", errors="replace")
        names = {}
        for line in text.splitlines():
            m = re.match(r'v_[a-z]{2}(\d{6})="(.*)"', line.strip())
            if not m:
                continue
            fields = m.group(2).split("~")
            if len(fields) > 2:
                names[m.group(1)] = fields[1]
        if len(names) >= len(codes) * 0.5:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(names, f, ensure_ascii=False)
            return names
    except (subprocess.CalledProcessError, OSError):
        pass
    # 网络失败时用上次成功缓存
    if os.path.exists(cache_path):
        cached = json.load(open(cache_path, encoding="utf-8"))
        print(f"  已记录代码名称使用本地缓存（{len(cached)} 只）")
        return cached
    return names


# ---------------------------------------------------------------- 名称主题

PREFIX_NOISE = (
    "华夏", "嘉实", "国泰", "易方达", "汇添富", "富国", "南方", "广发", "博时",
    "招商", "银华", "鹏华", "华安", "天弘", "建信", "平安", "景顺长城", "中欧",
    "兴全", "大成", "融通", "申万菱信", "华宝", "华泰柏瑞", "工银", "万家",
    "国联", "中证", "上证", "深证", "国证", "中债", "恒生", "标普", "纳斯达克",
    "道琼斯", "摩根", "中金", "东财", "方正", "新华",
)

CATEGORY_RULES = (
    ("黄金", ("黄金", "贵金属", "金ETF")),
    ("有色金属", ("有色", "稀土", "稀有金属", "工业金属")),
    ("芯片半导体", ("芯片", "半导体", "集成电路")),
    ("通信", ("通信", "5g")),
    ("电池", ("电池", "锂电")),
    ("新能源车", ("新能源车", "新能源汽车")),
)


def theme_of(name: str) -> str:
    """从 ETF 名称提取主题词，用于同主题去重。"""
    t = name.split("ETF")[0]
    for p in PREFIX_NOISE:
        if t.startswith(p):
            t = t[len(p):]
            break
    return t.strip() or name


def category_of(theme: str, name: str) -> str:
    """把主题词归一到类型，用于“与已收录类型不重复”的排除。"""
    for cat, kws in CATEGORY_RULES:
        for kw in kws:
            if kw.lower() in theme.lower() or kw.lower() in name.lower():
                return cat
    return theme


# ---------------------------------------------------------------- 精算指标

def compute_short(code: str, name: str, data_dir: str):
    """复用 analyze_etf 的指标函数，计算短线评分 + 动量延续分。"""
    day = ae.read_kline(os.path.join(data_dir, f"day_{code}.json"))
    if not day:
        return None
    closes = [r[2] for r in day]
    vols = [r[5] for r in day]
    price = closes[-1]

    m = {"code": code, "name": name, "close": price, "date": day[-1][0]}
    ma5, ma10, ma20, ma60 = (ae.sma(closes, n)[-1] for n in (5, 10, 20, 60))
    m.update(ma5=ma5, ma10=ma10, ma20=ma20, ma60=ma60)
    ma10_prev = ae.sma(closes, 10)[-6] if len(closes) >= 15 else None
    m["ma10_slope"] = (ma10 - ma10_prev) / ma10_prev * 100 if ma10_prev else None

    r6, r14 = ae.rsi(closes, 6), ae.rsi(closes, 14)
    dif, dea, hist = ae.macd(closes, 6, 13, 5)
    m["rsi6"], m["rsi14"] = r6[-1], r14[-1]
    m["dif"], m["dea"], m["hist"] = dif[-1], dea[-1], hist[-1]

    v5 = sum(vols[-5:]) / 5
    v20_prev = sum(vols[-25:-5]) / 20
    m["vol_ratio"] = v5 / v20_prev if v20_prev else None

    hi10 = max(closes[-10:])
    m["dist_10d_high"] = (price / hi10 - 1) * 100
    m["ret_10d"] = (price / closes[-11] - 1) * 100 if len(closes) > 11 else None
    m["ret_20d"] = (price / closes[-21] - 1) * 100 if len(closes) > 21 else None
    m["ret_5d"] = (price / closes[-6] - 1) * 100 if len(closes) > 6 else None

    # 波动
    atr_line = ae.atr(day, 14)
    m["atr_pct"] = atr_line[-1] / price * 100 if price else None

    # 2 周波段参考：入场（MA10 回踩位）、止损（MA10 下方 0.5×ATR 缓冲）、目标（布林上轨）
    boll_up = ae.boll(closes)[0][-1]
    atr_val = atr_line[-1]
    m["band_entry"] = round(ma10, 3)
    m["band_stop"] = round(ma10 - 0.5 * atr_val, 3)
    m["band_target"] = round(boll_up, 3)
    dist_ma10 = (price / ma10 - 1) * 100 if ma10 else 0
    if dist_ma10 > 2:
        m["band_zone"] = "追高区（等回踩 MA10）"
    elif dist_ma10 < -1:
        m["band_zone"] = "回调区（等企稳信号）"
    else:
        m["band_zone"] = "回踩区（可操作）"

    tag, score, advice, reasons = ae.short_term_signal(m)
    m["short"] = {"tag": tag, "score": score, "advice": advice, "reasons": reasons}

    # 动量延续分（0~4）
    continuation, cont_reasons = 0, []
    if price > ma5 > ma10:
        continuation += 1
        cont_reasons.append("站上 MA5/MA10")
    if m["hist"] is not None and m["hist"] > 0:
        continuation += 1
        cont_reasons.append("快 MACD 柱为正")
    if m["hist"] is not None and len(closes) > 2:
        hist_prev = dif[-2] - dea[-2] if dif[-2] is not None and dea[-2] is not None else None
        if hist_prev is not None and m["hist"] > hist_prev:
            continuation += 1
            cont_reasons.append("快 MACD 柱扩张")
    if m["vol_ratio"] is not None and m["vol_ratio"] >= 1.1:
        continuation += 1
        cont_reasons.append("量能放大")
    if m["ret_10d"] is not None and m["ret_10d"] > 0 and score >= 0:
        continuation += 1
        cont_reasons.append("10 日动量为正")

    m["continuation"] = {"score": continuation, "reasons": cont_reasons}
    m["total"] = score + continuation
    return m


# ---------------------------------------------------------------- 主流程

def read_codes(path: str) -> set:
    codes = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            m = re.search(r"\d{6}", line)
            if m:
                codes.add(m.group())
    return codes


def main():
    ap = argparse.ArgumentParser(description="短线强势 ETF 推荐")
    ap.add_argument("--top", type=int, default=10, help="推荐数量（默认 10）")
    ap.add_argument("--exclude-list", default=os.path.join(BASE_DIR, "etf_list"), help="需要排除的代码文件（默认 etf_list）")
    ap.add_argument("--candidate-count", type=int, default=40, help="实时快筛后精算的候选数量（默认 40）")
    ap.add_argument("--data-dir", default=os.path.join(BASE_DIR, ".workwork", "data", "reco"), help="候选日线缓存目录")
    ap.add_argument("--out-dir", default=os.path.join(BASE_DIR, ".workwork", "report"), help="报告输出目录")
    args = ap.parse_args()

    exclude = read_codes(args.exclude_list)
    print(f"已记录代码（排除）：{sorted(exclude)}")

    print("拉取全市场 ETF 列表…")
    os.makedirs(args.data_dir, exist_ok=True)
    all_etfs = fetch_etf_list(args.data_dir)
    if not all_etfs:
        raise SystemExit("无法获取 ETF 列表（实时接口与本地缓存均不可用），请稍后重试")
    print(f"全市场 ETF：{len(all_etfs)} 只")

    # 已记录代码的类型：优先用腾讯实时名称（东财列表可能缺商品 ETF），再回退东财列表
    etf_by_code = {str(e.get("f12")): e for e in all_etfs}
    owned_names = fetch_tencent_names(sorted(exclude), args.data_dir)
    owned_categories = set()
    for c in exclude:
        e = etf_by_code.get(c)
        name = owned_names.get(c) or (e.get("f14") if e else None) or c
        owned_categories.add(category_of(theme_of(name), name))
    print(f"已记录类型（同类型不再推荐）：{sorted(owned_categories)}")

    # 快筛：流动性 + 当日活跃
    cands = []
    excluded_by_type = 0
    for e in all_etfs:
        code, name = str(e.get("f12") or ""), e.get("f14") or ""
        if not code or code in exclude:
            continue
        try:
            chg = float(e.get("f3") or 0)
            turnover = float(e.get("f8") or 0)
            vol_ratio = float(e.get("f10") or 0)
            amount = float(e.get("f6") or 0)
        except (TypeError, ValueError):
            continue
        # 排除停牌/无价
        if float(e.get("f2") or 0) <= 0:
            continue
        if amount < 3000_0000:  # 成交额 >= 3000 万，保证可交易流动性
            continue
        theme = theme_of(name)
        cat = category_of(theme, name)
        if cat in owned_categories:
            excluded_by_type += 1
            continue
        cands.append({
            "code": code, "name": name, "chg": chg, "turnover": turnover,
            "vol_ratio": vol_ratio, "amount": amount, "theme": theme, "category": cat,
        })

    # 按涨幅排序，同主题最多保留 2 只，避免推荐扎堆同一板块
    cands.sort(key=lambda x: x["chg"], reverse=True)
    seen_theme = {}
    selected = []
    for c in cands:
        if seen_theme.get(c["theme"], 0) >= 2:
            continue
        seen_theme[c["theme"]] = seen_theme.get(c["theme"], 0) + 1
        selected.append(c)
        if len(selected) >= args.candidate_count:
            break

    print(f"实时快筛：{len(selected)} 只候选（已排除同类型 {excluded_by_type} 只）")

    results = []
    for i, c in enumerate(selected, 1):
        ok = fetch_tencent_day(c["code"], args.data_dir)
        r = compute_short(c["code"], c["name"], args.data_dir) if ok else None
        if r is None:
            print(f"  [{i}/{len(selected)}] {c['code']} 日线获取失败，跳过")
            continue
        r.update(
            chg=c["chg"], turnover=c["turnover"], vol_ratio_live=c["vol_ratio"],
            amount=c["amount"], theme=c["theme"], category=c["category"],
        )
        results.append(r)
        if i % 10 == 0 or i == len(selected):
            print(f"  已精算 {i}/{len(selected)}，当前候选池 {len(results)} 只")

    # 去重保险（列表异常时同一代码可能被选中多次）
    seen_res, uniq_results = set(), []
    for r in results:
        if r["code"] not in seen_res:
            seen_res.add(r["code"])
            uniq_results.append(r)
    results = uniq_results

    # 推荐门槛：短线 >= 2 且动量延续 >= 2；不足时放宽到短线 >= 1
    qualified = [r for r in results if r["short"]["score"] >= 2 and r["continuation"]["score"] >= 2]
    if len(qualified) < args.top:
        fallback = [r for r in results if r["short"]["score"] >= 1 and r["continuation"]["score"] >= 1]
        qualified = qualified + [r for r in fallback if r["code"] not in {x["code"] for x in qualified}]
    qualified.sort(key=lambda x: (x["total"], x["chg"]), reverse=True)
    results = qualified[:args.top]

    print("\n===== 推荐结果（2 周波段） =====")
    print(f"{'代码':<8}{'名称':<16}{'现价':>8}{'短线':>5}{'综合':>5}{'入场':>9}{'止损':>9}{'目标':>9}  状态")
    for r in results:
        print(
            f"{r['code']:<8}{r['name']:<16}{r['close']:>8.3f}"
            f"{r['short']['score']:>5}{r['total']:>5}"
            f"{r['band_entry']:>9.3f}{r['band_stop']:>9.3f}{r['band_target']:>9.3f}  {r.get('band_zone', '')}"
        )
    print(f"\n共推荐 {len(results)} 只；已排除 {len(exclude)} 只已记录代码 + {excluded_by_type} 只同类型 ETF")

    # 写报告
    os.makedirs(args.out_dir, exist_ok=True)
    public = []
    for r in results:
        rr = {k: v for k, v in r.items()}
        public.append(rr)
    with open(os.path.join(args.out_dir, "recommend.json"), "w", encoding="utf-8") as f:
        json.dump(public, f, ensure_ascii=False, indent=2)

    lines = ["# 2 周波段强势 ETF 推荐（技术面动量筛选）\n"]
    lines.append("> 规则：全市场 ETF 实时快筛 → 日线精算短线信号 + 动量延续分 → 排除已记录代码及其类型。\n")
    lines.append("## 推荐列表\n")
    lines.append("| 代码 | 名称 | 类型 | 现价 | 短线分 | 延续分 | 综合分 | 入场(回踩MA10) | 止损 | 目标 | 状态 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        reasons = r["short"]["reasons"] + r["continuation"]["reasons"]
        lines.append(
            f"| {r['code']} | {r['name']} | {r.get('category', r['theme'])} | {r['close']:.3f} | "
            f"{r['short']['score']:+d} | {r['continuation']['score']:+d} | {r['total']:+d} | "
            f"{r['band_entry']:.3f} | {r['band_stop']:.3f} | {r['band_target']:.3f} | {r.get('band_zone', '—')} |"
        )
    lines.append("\n### 信号理由\n")
    for r in results:
        reasons = r["short"]["reasons"] + r["continuation"]["reasons"]
        lines.append(f"- **{r['code']} {r['name']}**：{'；'.join(reasons)}")
    lines.append("")
    lines.append("## 说明")
    lines.append(f"- 候选来源：全市场 {len(all_etfs)} 只 ETF，实时快筛取 {args.candidate_count} 只活跃候选（成交额 ≥ 3000 万，同主题限 2 只）。")
    lines.append(f"- 已排除已记录代码 {len(exclude)} 只：{', '.join(sorted(exclude))}。")
    lines.append(f"- 已排除同类型 ETF {excluded_by_type} 只（类型：{', '.join(sorted(owned_categories))}），推荐结果与已收录类型不重复。")
    lines.append("- 短线分（2 周波段）：MA10/MA20 排列、MA10 斜率、快 MACD(6,13,5)、RSI6、量比、距 10 日高点合成（−6 ~ +6）；延续分：站上 MA5/MA10、快 MACD 柱为正且扩张、量能放大、10 日动量为正（0 ~ +4）。")
    lines.append("- 推荐基于动量延续假设，属于统计意义上的强势候选，不是确定性预测；高波动品种请自行控制仓位与止损。")
    lines.append("")
    lines.append("> 风险提示：本报告不构成投资建议。")
    md_path = os.path.join(args.out_dir, "recommend.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n报告已保存：{md_path}")


if __name__ == "__main__":
    main()
