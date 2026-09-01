#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨平台 ETF 数据采集

仅依赖 Python 标准库（urllib + concurrent.futures），Windows / macOS / Linux 通用，无需 curl / iconv / bash。
输出到 <项目根>/.workwork/data/：
    实时行情三源（腾讯主 / 新浪备 / 东财校验）、折溢价（IOPV）、分时、日/周/月线、大盘指数、板块榜、
    外盘与汇率、ETF 份额与季报重仓、消息面快讯（国内七源直连 + 国外四源走代理，每轮实时采集合并为
    news_merged.json）与自选 ETF 重仓股公告（news_ann.json）。
逐只 ETF 数据并行采集。不保留历史数据：某项采集失败即删除其旧缓存；每轮启动时自动清理不在当前
自选列表的标的级缓存文件。每轮写 _manifest.json 记录各文件采集状态（ok/fail），fail 项无数据文件。

用法：
    python3 scripts/fetch_etf_data.py              # 读取 config/etf_list.txt（兼容根目录 etf_list.txt）
    python3 scripts/fetch_etf_data.py 512400 159992
    python3 scripts/fetch_etf_data.py --news-only  # 只刷消息面（快讯+重仓股公告），盘后快速刷新用
"""

import datetime
import email.utils
import gzip
import json
import os
import re
import sys
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import request


def _find_project_root(start):
    """自适应项目根：兼容脚本在根目录或 scripts/ 下，以及配置在 config/ 或根目录"""
    cur = os.path.dirname(os.path.abspath(start)) if os.path.isfile(start) else os.path.abspath(start)
    # 若在 scripts/ 下，根为其父目录
    if os.path.basename(cur) == "scripts":
        return os.path.dirname(cur)
    # 向上查找直到含 .git 或 etf_list.txt
    for _ in range(4):
        if os.path.exists(os.path.join(cur, ".git")) or os.path.exists(os.path.join(cur, "etf_list.txt")) or os.path.exists(os.path.join(cur, "config", "etf_list.txt")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.dirname(os.path.abspath(__file__)) if os.path.basename(os.path.dirname(os.path.abspath(__file__))) != "scripts" else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = _find_project_root(__file__)
DATA_DIR = os.path.join(BASE_DIR, ".workwork", "data")


def _config_path(name):
    """配置优先 config/，回退根目录（兼容旧位置）"""
    for p in (os.path.join(BASE_DIR, "config", name), os.path.join(BASE_DIR, name)):
        if os.path.exists(p):
            return p
    return os.path.join(BASE_DIR, "config", name) if os.path.exists(os.path.join(BASE_DIR, "config")) else os.path.join(BASE_DIR, name)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")

# 本地代理（用于国外新闻源；留空 "" 则跳过国外源，仅采国内源）
PROXY = "http://127.0.0.1:10809"

# 逐只 ETF 并行度（温和，避免触发免费接口限流）
MAX_WORKERS = 5

# 采集状态汇总：{文件名: "ok"|"fail"}，线程安全
_manifest = {}
_manifest_lock = threading.Lock()


def market_of(code):
    return "sh" if code.startswith(("5", "11")) else "sz"


def http_get(url, timeout=6, headers=None, encoding=None, proxy=None):
    req = request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    if proxy:
        opener = request.build_opener(request.ProxyHandler({"http": proxy, "https": proxy}))
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read()
    else:
        with request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode(encoding or "utf-8", errors="replace")


def _record(name, status):
    with _manifest_lock:
        _manifest[name] = status


def _default_content_check(name, text):
    """内容结构校验：接口改版/风控页「看似成功实则无效」时拒收，触发换源与重试。
    校验失败返回原因字符串，通过返回 None。"""
    if name.endswith((".json", ".txt")) is False:
        return None
    if name.startswith(("day_", "week_", "month_", "minute_")):
        try:
            d = json.loads(text)
        except ValueError:
            return "非 JSON"
        inner = (d.get("data") or {})
        # 腾讯行情包内层键为 sh{code}/sz{code}，K线在 day/qfqday(/week/month) 之一
        if not isinstance(inner, dict) or not inner:
            return "data 为空或非 dict"
        for v in inner.values():
            if isinstance(v, dict) and any(k in v for k in ("day", "qfqday", "week", "month", "data", "qt")):
                break
        else:
            return "内层缺 day/qfqday/data 等行情键"
    elif name.startswith("etf_realtime_"):
        # 腾讯为 ~ 分隔、东财为 JSON diff、新浪为 hq_str_ 变量格式，三者任一即可
        if ("~" not in text) and ('"diff"' not in text) and ("hq_str_" not in text):
            return "无行情字段（~ / diff / hq_str_ 均缺失）"
    elif name in ("index_realtime.txt", "overseas_realtime_qq.txt"):
        if "~" not in text:
            return "无 ~ 分隔行情字段"
    elif name.startswith("index_kline_"):
        try:
            d = json.loads(text)
        except ValueError:
            return "非 JSON"
        ks = ((d.get("data") or {}).get("klines")) or []
        if not ks:
            return "data.klines 为空"
    return None


def fetch_save(name, urls, timeout=6, headers=None, encoding=None, retries=3, proxy=None):
    """依次尝试多个 URL，最多 retries 轮（指数退避 0.8s / 1.6s）；
    拒绝空内容、HTML 错误页、东财 data:null 限流响应，以及结构不符的数据（_default_content_check）。
    返回 "ok"（成功）/"fail"（失败，同时删除旧缓存，不保留历史数据）。
    """
    for attempt in range(retries):
        for u in urls:
            try:
                text = http_get(u, timeout=timeout, headers=headers, encoding=encoding, proxy=proxy)
            except Exception:
                continue
            if not text.strip():
                continue
            head = text.lstrip()[:200].lower()
            if head.startswith(("<html", "<!doctype")) or '"data":null' in text:
                continue
            bad = None
            try:
                bad = _default_content_check(name, text)
            except Exception:
                bad = None  # 校验器自身异常不阻断采集
            if bad:
                print(f"警告：{name} 内容结构校验未通过（{bad}），尝试下一数据源")
                continue
            with open(os.path.join(DATA_DIR, name), "w", encoding="utf-8") as f:
                f.write(text)
            _record(name, "ok")
            return "ok"
        if attempt < 2:
            time.sleep(0.8 * (2 ** attempt))  # 0.8s, 1.6s
    path = os.path.join(DATA_DIR, name)
    if os.path.exists(path):
        os.remove(path)  # 不保留历史数据：失败即清除旧文件，避免把旧数据当实时数据用
    print(f"警告：{name} 所有数据源均失败（已清除旧数据）")
    _record(name, "fail")
    return "fail"


def read_codes(cli_codes):
    if cli_codes:
        return [c for c in re.split(r"[,\s]+", cli_codes) if re.fullmatch(r"\d{6}", c)]
    codes = []
    cfg = _config_path("etf_list.txt")
    with open(cfg, encoding="utf-8") as f:
        for line in f:
            m = re.search(r"\d{6}", line)
            if m:
                codes.append(m.group())
    return codes


PER_CODE_PREFIXES = ("day_", "week_", "month_", "minute_", "etf_meta_", "top_holdings_")


def cleanup_cache(codes):
    """不保留历史数据：删除代码不在当前自选列表的标的级缓存文件。"""
    keep = set(codes)
    removed = 0
    for fn in os.listdir(DATA_DIR):
        for prefix in PER_CODE_PREFIXES:
            if fn.startswith(prefix):
                code = fn[len(prefix):].split(".")[0]
                if code not in keep:
                    os.remove(os.path.join(DATA_DIR, fn))
                    removed += 1
                break
    if removed:
        print(f"已清理 {removed} 个非当前自选标的的历史缓存文件")


def em_secid(code):
    return ("1." if market_of(code) == "sh" else "0.") + code


# ---- 消息面：国内七源（直连）+ 国外四源（走 PROXY）→ 合并为 news_merged.json + 重仓股公告 ----
# 说明：金十数据为最快源（约0.2s、秒级时效，覆盖宏观/大宗/外汇，含全球视角）；其余为国内快源
# （新浪7x24/东财/同花顺/华尔街见闻/网易/新浪滚动）。国外源（Google News/Yahoo/BBC/MarketWatch）
# 走顶部 PROXY 代理（免费 RSS 无 key），实测 1s 级可用；PROXY 留空则自动跳过国外源。
# 全部源并行采集，总耗时=最慢单源。自动合并为统一 schema 的 news_merged.json，
# AI 每轮直接读取即可，无需再逐个解析原始文件。

NEWS_RAW = [
    # (文件名, [URL], timeout, retries, headers)
    ("news_jin10.json",
     ["https://flash-api.jin10.com/get_flash_list?channel=-8200&vip=1&max_time=0"],
     8, 2, {"x-app-id": "bVBF4FyRTn5NJF5n", "x-version": "1.0.0",
            "x-requested-with": "XMLHttpRequest", "Accept-Encoding": "gzip"}),
    ("news_sina.json",
     ["https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=30&zhibo_id=152"],
     6, 2, None),
    ("news_eastmoney.txt",
     ["https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_30_1_.html"],
     6, 2, None),
    ("news_10jqka.json",
     ["https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&pagesize=30"],
     6, 2, None),
    ("news_wallstcn.json",
     ["https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=30"],
     8, 2, None),
    ("news_netease.txt",
     ["https://money.163.com/special/00259BVP/news_flow_index.js"],
     10, 1, None),
    ("news_sina_roll.json",
     ["https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=30&page=1"],
     8, 2, None),
]


def _norm_time(raw):
    """统一为 %Y-%m-%d %H:%M:%S；支持 unix 秒 与 MM/DD/YYYY HH:MM:SS。"""
    if not raw:
        return ""
    s = str(raw).strip()
    if s.isdigit() and len(s) == 10:
        try:
            return datetime.datetime.fromtimestamp(int(s)).strftime("%Y-%m-%d %H:%M:%S")
        except (OSError, ValueError, OverflowError):
            return ""
    try:
        return datetime.datetime.strptime(s, "%m/%d/%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    return s[:19]


def _read_raw(name):
    p = os.path.join(DATA_DIR, name)
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def _dicts_in(obj):
    """展平 obj 内所有层级的 dict。"""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _dicts_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _dicts_in(v)


def _find_lists(obj, *keys, must_have=None):
    """递归查找所有「键名为 keys 之一、值为 list」的列表，展平返回其中全部 dict。
    must_have: 仅保留含该 key 的条目（避免抓到同名但语义不同的列表）。"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, list):
                out.extend(x for x in _dicts_in(v)
                           if must_have is None or must_have in x)
            else:
                out.extend(_find_lists(v, *keys, must_have=must_have))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_find_lists(v, *keys, must_have=must_have))
    return out


def parse_news_sina_zhibo():
    items = []
    try:
        d = json.loads(_read_raw("news_sina.json"))
        # must_have 锁定含 rich_text 的条目列表，避免抓到 top/focus 等同名 list
        for it in _find_lists(d, "list", must_have="rich_text"):
            t = it.get("rich_text") or ""
            if not t:
                continue
            m = re.match(r"^【(.+?)】", t)
            items.append({"time": _norm_time(it.get("create_time")), "source": "新浪7x24",
                          "title": m.group(1) if m else t[:40], "text": t, "url": ""})
    except Exception as e:
        print(f"警告：新浪7x24 解析异常：{type(e).__name__}: {e}")
    return items


def parse_news_eastmoney():
    items = []
    try:
        t = _read_raw("news_eastmoney.txt")
        body = t[t.find("{"):t.rfind("}") + 1]  # 剥 var ajaxResult= 前缀
        # LivesList 是「键名为 LivesList 的 list」，用键名递归查找而非固定路径
        for it in _find_lists(json.loads(body), "LivesList"):
            title = it.get("title") or ""
            if not title:
                continue
            items.append({"time": _norm_time(it.get("showtime")), "source": "东方财富",
                          "title": title, "text": it.get("digest") or title,
                          "url": it.get("url_unique") or ""})
    except Exception as e:
        print(f"警告：东方财富解析异常：{type(e).__name__}: {e}")
    return items


def parse_news_10jqka():
    items = []
    try:
        d = json.loads(_read_raw("news_10jqka.json"))
        # data 可能为 dict（含 list）也可能直接是 list（接口偶发改版）
        data = d.get("data")
        cands = data if isinstance(data, list) else _find_lists(d, "list")
        for it in cands:
            title = it.get("title") or ""
            if not title:
                continue
            items.append({"time": _norm_time(it.get("ctime")), "source": "同花顺",
                          "title": title, "text": it.get("summary") or title,
                          "url": it.get("url") or it.get("url_m") or ""})
    except Exception as e:
        print(f"警告：同花顺解析异常：{type(e).__name__}: {e}")
    return items


def parse_news_wallstcn():
    items = []
    try:
        d = json.loads(_read_raw("news_wallstcn.json"))
        for it in _find_lists(d, "items"):
            title = it.get("title") or ""
            if not title:
                continue
            items.append({"time": _norm_time(it.get("display_time")), "source": "华尔街见闻",
                          "title": title, "text": it.get("content_text") or title,
                          "url": it.get("uri") or ""})
    except Exception as e:
        print(f"警告：华尔街见闻解析异常：{type(e).__name__}: {e}")
    return items


def parse_news_netease():
    items = []
    try:
        t = _read_raw("news_netease.txt")
        body = t[t.find("["):t.rfind("]") + 1]  # 剥 data_callback( 前缀
        for it in json.loads(body):
            title = it.get("title") or ""
            if not title:
                continue
            items.append({"time": _norm_time(it.get("time")), "source": "网易7x24",
                          "title": title, "text": it.get("digest") or title,
                          "url": it.get("docurl") or ""})
    except Exception as e:
        print(f"警告：网易7x24 解析异常：{type(e).__name__}: {e}")
    return items


def parse_news_sina_roll():
    items = []
    try:
        d = json.loads(_read_raw("news_sina_roll.json"))
        # 兼容两种结构：result.data 为条目列表（现行）或 result.data.list 包裹（改版后）
        for it in _find_lists(d, "data", "list", must_have="title"):
            title = it.get("title") or ""
            if not title:
                continue
            items.append({"time": _norm_time(it.get("ctime")), "source": "新浪滚动",
                          "title": title, "text": title, "url": it.get("url") or ""})
    except Exception as e:
        print(f"警告：新浪滚动解析异常：{type(e).__name__}: {e}")
    return items


def parse_news_jin10():
    """金十数据（最快源）：data[] 中过滤 PLUS 锁定条目（content 为空）。"""
    items = []
    try:
        d = json.loads(_read_raw("news_jin10.json"))
        for it in _find_lists(d, "data"):
            dd = it.get("data") or {}
            content = dd.get("content") or ""
            if not content:
                continue
            m = re.match(r"^【(.+?)】", content)
            items.append({"time": _norm_time(it.get("time")), "source": "金十",
                          "title": dd.get("title") or (m.group(1) if m else content[:40]),
                          "text": content, "url": dd.get("source_link") or ""})
    except Exception as e:
        print(f"警告：金十解析异常：{type(e).__name__}: {e}")
    return items


def parse_news_cnbc():
    """（已弃用：CNBC 偶发超时且内容偏美股，全球宏观由金十覆盖；保留函数便于日后恢复）"""
    return []


# ---- 国外新闻源（走 PROXY 代理；RSS 免费无 key） ----
# 实测（2026-08-13）：Google News / Yahoo / BBC / MarketWatch / CNBC / Investing 走代理均 1s 级可用；
# Reuters(404) / FT / Bloomberg / AP / Economist(SSL) 不可用，WSJ 内容陈旧，均弃用。
NEWS_FOREIGN_RAW = [
    # (文件名, [URL], timeout, retries, headers)
    ("news_google.json",
     ["https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans"], 10, 1, None),
    ("news_yahoo.json",
     ["https://finance.yahoo.com/news/rssindex"], 10, 1, None),
    ("news_bbc.json",
     ["https://feeds.bbci.co.uk/news/business/rss.xml"], 10, 1, None),
    ("news_marketwatch.json",
     ["https://feeds.content.dowjones.io/public/rss/mw_topstories"], 10, 1, None),
]


def _norm_rss_time(raw):
    """RSS 时间为 GMT/UTC，转北京时间；支持 RFC2822 与 ISO8601。"""
    if not raw:
        return ""
    s = str(raw).strip()
    try:
        dt = email.utils.parsedate_to_datetime(s)
        return (dt + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (dt + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return s[:19]


def parse_news_rss(fname, source):
    """通用 RSS 解析（item 的 title/pubDate/description/link）。"""
    items = []
    try:
        root = ET.fromstring(_read_raw(fname))
        for it in root.iter("item"):
            title = it.findtext("title") or ""
            if not title:
                continue
            items.append({"time": _norm_rss_time(it.findtext("pubDate")
                                                 or it.findtext("published") or ""),
                          "source": source, "title": title,
                          "text": it.findtext("description") or title,
                          "url": it.findtext("link") or ""})
    except Exception as e:
        print(f"警告：RSS({source}) 解析异常：{type(e).__name__}: {e}")
    return items


def parse_news_google():
    return parse_news_rss("news_google.json", "Google新闻")


def parse_news_yahoo():
    return parse_news_rss("news_yahoo.json", "Yahoo财经")


def parse_news_bbc():
    return parse_news_rss("news_bbc.json", "BBC商业")


def parse_news_marketwatch():
    return parse_news_rss("news_marketwatch.json", "MarketWatch")


# (解析函数, 原始文件名, 中文名) —— merge_news 表驱动遍历，新增源只需在此登记
NEWS_SOURCES = [
    (parse_news_jin10, "news_jin10.json", "金十"),
    (parse_news_sina_zhibo, "news_sina.json", "新浪7x24"),
    (parse_news_eastmoney, "news_eastmoney.txt", "东方财富"),
    (parse_news_10jqka, "news_10jqka.json", "同花顺"),
    (parse_news_wallstcn, "news_wallstcn.json", "华尔街见闻"),
    (parse_news_netease, "news_netease.txt", "网易7x24"),
    (parse_news_sina_roll, "news_sina_roll.json", "新浪滚动"),
    (parse_news_google, "news_google.json", "Google新闻"),
    (parse_news_yahoo, "news_yahoo.json", "Yahoo财经"),
    (parse_news_bbc, "news_bbc.json", "BBC商业"),
    (parse_news_marketwatch, "news_marketwatch.json", "MarketWatch"),
]


def merge_news():
    """七源（国内）+ 四源（国外，代理）解析合并：去重（标题前25字）、时间倒序、上限 150 条。
    任一源解析为 0 条时打印告警——数据源改版（JSON key 漂移）不再静默丢失。"""
    items = []
    for fn, fname, cn_name in NEWS_SOURCES:
        parsed = fn()
        if not parsed:
            raw = _read_raw(fname)
            reason = ("原始文件缺失（采集失败，见上方 fetch_save 警告）" if not raw.strip()
                      else "解析出 0 条（接口结构可能已改版，请检查解析器）")
            print(f"警告：消息源 {cn_name} 解析异常：{reason}")
        else:
            items.extend(parsed)
    seen, uniq = set(), []
    for it in sorted(items, key=lambda x: x["time"] or "", reverse=True):
        k = (it["title"] or "")[:25]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    return uniq[:150]


def fetch_holdings_ann(codes):
    """自选 ETF 季报重仓股（前10，去重上限60只）最近3天 A 股公告 → news_ann.json。
    覆盖业绩/回购/增减持/重组等一手公告，解决个股公告滞后于快讯的问题。"""
    stocks = {}
    for c in codes:
        p = os.path.join(DATA_DIR, f"top_holdings_{c}.json")
        if not os.path.exists(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
            # 递归定位 fundStocks 列表并展平（_find_lists 直接返回条目 dict，不依赖 Datas 固定层级）
            for s in _find_lists(d, "fundStocks"):
                g = str(s.get("GPDM") or "")
                if g.isdigit() and len(g) == 6:
                    stocks.setdefault(g, s.get("GPJC") or "")
        except Exception as e:
            print(f"重仓股解析 {code} 失败：{type(e).__name__}: {e}")
            continue
    results = []
    cutoff = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    if stocks:
        url_tpl = ("https://np-anotice-stock.eastmoney.com/api/security/ann"
                   "?sr=-1&page_size=3&page_index=1&ann_type=A&client_source=web&stock_list={code}")

        def one(item):
            code, name = item
            try:
                t = http_get(url_tpl.format(code=code), timeout=6)
                d = json.loads(t)
                for it in (d.get("data") or {}).get("list") or []:
                    date = (it.get("notice_date") or "")[:10]
                    if date >= cutoff:
                        results.append({"code": code, "name": name, "date": date,
                                        "title": it.get("title") or ""})
            except Exception as e:
                print(f"公告采集 {name}({code}) 失败：{type(e).__name__}: {e}")

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(one, list(stocks.items())[:60]))
        results.sort(key=lambda x: x["date"] + x["title"], reverse=True)
    ann_path = os.path.join(DATA_DIR, "news_ann.json")
    if stocks:
        doc = {"fetch_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "cutoff": cutoff, "count": len(results), "items": results}
        with open(ann_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        _record("news_ann.json", "ok")
    else:
        if os.path.exists(ann_path):
            os.remove(ann_path)  # 不保留历史数据
        _record("news_ann.json", "fail")
    print(f"重仓股公告：{len(results)} 条（覆盖 {len(stocks)} 只股票，近3天）")


def fetch_news(codes):
    """消息面采集：国内七源 + 国外四源（需 PROXY）并行抓取 → news_merged.json；
    重仓股公告 → news_ann.json。总耗时≈最慢单源；任一源失败不影响其他源；
    盘后可用 --news-only 单独刷新。"""
    jobs = [(name, urls, timeout, headers, retries, None)
            for name, urls, timeout, retries, headers in NEWS_RAW]
    if PROXY:
        jobs += [(name, urls, timeout, headers, retries, PROXY)
                 for name, urls, timeout, retries, headers in NEWS_FOREIGN_RAW]
    else:
        print("提示：未配置 PROXY（fetch_etf_data.py 顶部），跳过国外新闻源")
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futures = [ex.submit(fetch_save, name, urls, timeout, headers, None, retries, proxy)
                   for name, urls, timeout, headers, retries, proxy in jobs]
        for _ in as_completed(futures):
            pass
    items = merge_news()
    if items:
        doc = {"fetch_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "count": len(items), "items": items}
        with open(os.path.join(DATA_DIR, "news_merged.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        _record("news_merged.json", "ok")
    else:
        merged_path = os.path.join(DATA_DIR, "news_merged.json")
        if os.path.exists(merged_path):
            os.remove(merged_path)  # 不保留历史数据：快讯必须实时，失败即删旧文件
        _record("news_merged.json", "fail")
        print("警告：news_merged.json 各源均解析失败（已清除旧数据）")
    fetch_holdings_ann(codes)


def fetch_global(codes):
    """采集全局接口（实时三源 / 快讯 / 指数 / 板块 / 外盘）。数量少、对东财并发敏感，保持串行。"""
    qt_codes = ",".join(market_of(c) + c for c in codes)

    # 1/2. 实时行情：腾讯主源 + 新浪备用
    fetch_save("etf_realtime_qq.txt", [f"https://qt.gtimg.cn/q={qt_codes}"], encoding="gbk")
    fetch_save("etf_realtime_sina.txt",
               [f"https://hq.sinajs.cn/list={qt_codes}"],
               headers={"Referer": "https://finance.sina.com.cn"}, encoding="gbk")

    # 2.5 折溢价（IOPV）：解析腾讯字段 [78]（盘中实时参考净值），跨境/商品类溢价风险提示用
    iopv_path = os.path.join(DATA_DIR, "etf_iopv.json")
    try:
        with open(os.path.join(DATA_DIR, "etf_realtime_qq.txt"), encoding="utf-8") as f:
            qt_raw = f.read()
        iopv_rows = []
        for line in qt_raw.strip().split(";"):
            line = line.strip()
            if "=" not in line:
                continue
            parts = line.split("~")
            if len(parts) > 78 and parts[2] and parts[3] and parts[78]:
                try:
                    price, iopv = float(parts[3]), float(parts[78])
                except ValueError:
                    continue
                iopv_rows.append({"code": parts[2], "name": parts[1], "price": price,
                                  "iopv": iopv, "premium_pct": round((price / iopv - 1) * 100, 3)})
        if iopv_rows:
            with open(iopv_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(iopv_rows, ensure_ascii=False))
            _record("etf_iopv.json", "ok")
        elif os.path.exists(iopv_path):
            os.remove(iopv_path)
    except Exception as e:
        if os.path.exists(iopv_path):
            os.remove(iopv_path)
        print("IOPV 解析失败:", e)

    # 3. 实时行情校验：东方财富（拆两批避免限流）—— push2delay 优先（实测稳定），push2 作备用
    secs = [em_secid(c) for c in codes]
    batches = [secs[:5], secs[5:]] if len(secs) > 5 else [secs]
    em_fields = "f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18,f62"
    for i, batch in enumerate(batches, start=1):
        name = "etf_realtime_em.json" if i == 1 else "etf_realtime_em_2.json"
        q = ",".join(batch)
        fetch_save(name, [
            f"https://push2delay.eastmoney.com/api/qt/ulist.np/get?secids={q}&fields={em_fields}",
            f"https://push2.eastmoney.com/api/qt/ulist.np/get?secids={q}&fields={em_fields}",
            f"http://push2.eastmoney.com/api/qt/ulist.np/get?secids={q}&fields={em_fields}",
        ])

    # 4. 消息面：七源快讯（news_merged.json）+ 重仓股公告（news_ann.json）
    fetch_news(codes)

    # 5. 大盘指数：实时 + 近 30 日日K（含成交额；30 日用于计算 20 日线，供 8.1 大盘环境分级）
    fetch_save("index_realtime.txt", ["https://qt.gtimg.cn/q=sh000001,sz399006"], encoding="gbk")
    kline_fields = ("fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,"
                    "f58,f59,f60,f61&klt=101&fqt=0&end=20500101&lmt=30")
    for name, secid in (("index_kline_sh.json", "1.000001"), ("index_kline_sz.json", "0.399006")):
        fetch_save(name, [
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&{kline_fields}",
            f"http://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&{kline_fields}",
        ])

    # 6. 行业板块榜（最强/最弱）—— push2delay 优先
    board_q = ("pn=1&pz=10&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2+f:!50&fields=f3,f12,f14,f62")
    for name, po in (("boards_up.json", 1), ("boards_down.json", 0)):
        fetch_save(name, [
            f"https://push2delay.eastmoney.com/api/qt/clist/get?{board_q}&po={po}",
            f"https://push2.eastmoney.com/api/qt/clist/get?{board_q}&po={po}",
            f"http://push2.eastmoney.com/api/qt/clist/get?{board_q}&po={po}",
        ])

    # 6.1 外盘与汇率
    fetch_save("overseas_realtime_qq.txt",
               ["https://qt.gtimg.cn/q=usDJI,usIXIC,usINX,hkHSI,hkHSCEI"], encoding="gbk")
    fetch_save("overseas_realtime_sina.txt",
               ["https://hq.sinajs.cn/list=hf_GC,hf_CL,hf_ES,hf_NQ,hf_YM,fx_susdcny"],
               headers={"Referer": "https://finance.sina.com.cn"}, encoding="gbk")


def fetch_one_etf(code):
    """采集单只 ETF 的份额/重仓/分时/日周月线（并行调度单元）。"""
    secid = em_secid(code)
    fund_fields = "f57,f58,f62,f84,f85"
    # ETF 份额/规模 + 主力资金 —— push2delay 优先
    fetch_save(f"etf_meta_{code}.json", [
        f"https://push2delay.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fund_fields}",
        f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fund_fields}",
        f"http://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fund_fields}",
    ])
    # 季报重仓股
    fetch_save(f"top_holdings_{code}.json", [
        "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNInverstPosition"
        f"?FCODE={code}&deviceid=Wap&plat=Wap&product=EFund&version=6.2.8",
    ])
    mk = market_of(code)
    fetch_save(f"minute_{code}.json",
               [f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={mk}{code}"],
               timeout=20)
    for freq in ("day", "week", "month"):
        fetch_save(f"{freq}_{code}.json", [
            f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mk}{code},{freq},,,640,qfq",
        ], timeout=20)


def write_manifest(fetch_time_str):
    summary = {"ok": 0, "fail": 0}
    for v in _manifest.values():
        summary[v] = summary.get(v, 0) + 1
    doc = {"fetch_time": fetch_time_str, "summary": summary, "files": dict(_manifest)}
    with open(os.path.join(DATA_DIR, "_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return summary


def main():
    args = [a for a in sys.argv[1:]]
    news_only = "--news-only" in args
    if news_only:
        args.remove("--news-only")
    codes = read_codes(" ".join(args))
    if not codes:
        print("未找到有效代码（etf_list.txt 为空或参数无效）")
        return 1
    os.makedirs(DATA_DIR, exist_ok=True)
    cleanup_cache(codes)

    t0 = time.time()
    fetch_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(DATA_DIR, "fetch_time.txt"), "w", encoding="utf-8") as f:
        f.write(fetch_time_str)

    if news_only:
        # 盘后/盘中快速刷新消息面（快讯+重仓股公告），不刷行情
        fetch_news(codes)
    else:
        # 全局接口（串行）
        fetch_global(codes)

        # 逐只 ETF（并行）
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = [ex.submit(fetch_one_etf, c) for c in codes]
            for _ in as_completed(futures):
                pass

    elapsed = time.time() - t0
    summary = write_manifest(fetch_time_str)
    print(f"完成：{len(codes)} 只 ETF，{summary['ok']} ok / {summary['fail']} fail，"
          f"耗时 {elapsed:.1f}s → {DATA_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
