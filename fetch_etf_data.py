#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨平台 ETF 数据采集（v2.0 规范）

仅依赖 Python 标准库（urllib），Windows / macOS / Linux 通用，无需 curl / iconv / bash。
输出到 <项目根>/.workwork/data/：
    实时行情三源（腾讯主 / 新浪备 / 东财校验）、分时、日/周/月线、
    三源快讯（新浪 / 东财 / 同花顺）、大盘指数、板块榜、外盘、ETF 份额与季报重仓。

用法：
    python3 fetch_etf_data.py              # 读取 etf_list
    python3 fetch_etf_data.py 159831 515050
"""

import datetime
import os
import re
import sys
import time
from urllib import request


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, ".workwork", "data")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")


def market_of(code):
    return "sh" if code.startswith(("5", "11")) else "sz"


def http_get(url, timeout=15, headers=None, encoding=None):
    req = request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return data.decode(encoding or "utf-8", errors="replace")


def fetch_save(name, urls, timeout=15, headers=None, encoding=None):
    """依次尝试多个 URL，最多 3 轮；拒绝空内容、HTML 错误页与东财 data:null 限流响应。"""
    for attempt in range(3):
        for u in urls:
            try:
                text = http_get(u, timeout=timeout, headers=headers, encoding=encoding)
            except Exception:
                continue
            if not text.strip() or text.lstrip().startswith("<") or '"data":null' in text:
                continue
            with open(os.path.join(DATA_DIR, name), "w", encoding="utf-8") as f:
                f.write(text)
            return True
        if attempt < 2:
            time.sleep(3)
    print(f"警告：{name} 所有数据源均失败")
    return False


def read_codes(cli_codes):
    if cli_codes:
        return [c for c in re.split(r"[,\s]+", cli_codes) if re.fullmatch(r"\d{6}", c)]
    codes = []
    with open(os.path.join(BASE_DIR, "etf_list"), encoding="utf-8") as f:
        for line in f:
            m = re.search(r"\d{6}", line)
            if m:
                codes.append(m.group())
    return codes


def em_secid(code):
    return ("1." if market_of(code) == "sh" else "0.") + code


def main():
    codes = read_codes(" ".join(sys.argv[1:]))
    if not codes:
        print("未找到有效代码（etf_list 为空或参数无效）")
        return 1
    os.makedirs(DATA_DIR, exist_ok=True)

    with open(os.path.join(DATA_DIR, "fetch_time.txt"), "w", encoding="utf-8") as f:
        f.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    qt_codes = ",".join(market_of(c) + c for c in codes)

    # 1/2. 实时行情：腾讯主源 + 新浪备用
    fetch_save("realtime.txt", [f"https://qt.gtimg.cn/q={qt_codes}"],
               timeout=20, encoding="gbk")
    fetch_save("realtime_sina.txt",
               [f"https://hq.sinajs.cn/list={qt_codes}"],
               headers={"Referer": "https://finance.sina.com.cn"}, encoding="gbk")

    # 3. 实时行情校验：东方财富（拆两批避免限流）
    secs = [em_secid(c) for c in codes]
    batches = [secs[:5], secs[5:]] if len(secs) > 5 else [secs]
    for i, batch in enumerate(batches, start=1):
        name = "realtime_eastmoney.json" if i == 1 else "realtime_eastmoney_2.json"
        q = ",".join(batch)
        fetch_save(name, [
            f"https://push2.eastmoney.com/api/qt/ulist.np/get?secids={q}&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18,f62",
            f"http://push2.eastmoney.com/api/qt/ulist.np/get?secids={q}&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18,f62",
            f"https://push2delay.eastmoney.com/api/qt/ulist.np/get?secids={q}&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18,f62",
        ])

    # 4. 三源快讯
    fetch_save("news.json",
               ["https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=30&zhibo_id=152"])
    fetch_save("news_eastmoney.txt",
               ["https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_30_1_.html"])
    fetch_save("news_10jqka.json",
               ["https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&pagesize=30"])

    # 5. 大盘指数：实时 + 近 3 日日K（含成交额）
    fetch_save("index_realtime.txt", ["https://qt.gtimg.cn/q=sh000001,sz399006"], encoding="gbk")
    kline_fields = ("fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,"
                    "f58,f59,f60,f61&klt=101&fqt=0&end=20500101&lmt=3")
    for name, secid in (("index_kline_sh.json", "1.000001"), ("index_kline_sz.json", "0.399006")):
        fetch_save(name, [
            f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&{kline_fields}",
            f"http://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&{kline_fields}",
        ])

    # 6. 行业板块榜（最强/最弱）
    board_q = ("pn=1&pz=10&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2+f:!50&fields=f3,f12,f14,f62")
    for name, po in (("boards_up.json", 1), ("boards_down.json", 0)):
        fetch_save(name, [
            f"https://push2.eastmoney.com/api/qt/clist/get?{board_q}&po={po}",
            f"http://push2.eastmoney.com/api/qt/clist/get?{board_q}&po={po}",
            f"https://push2delay.eastmoney.com/api/qt/clist/get?{board_q}&po={po}",
        ])

    # 6.1 外盘与汇率
    fetch_save("global_realtime.txt",
               ["https://qt.gtimg.cn/q=usDJI,usIXIC,usINX,hkHSI,hkHSCEI"], encoding="gbk")
    fetch_save("global_sina.txt",
               ["https://hq.sinajs.cn/list=hf_GC,hf_CL,hf_ES,hf_NQ,hf_YM,fx_susdcny"],
               headers={"Referer": "https://finance.sina.com.cn"}, encoding="gbk")

    # 6.2 ETF 份额/规模 + 季报重仓股
    for c in codes:
        secid = em_secid(c)
        fetch_save(f"fund_{c}.json", [
            f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f58,f62,f84,f85",
            f"http://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f58,f62,f84,f85",
            f"https://push2delay.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f58,f62,f84,f85",
        ])
        fetch_save(f"holdings_{c}.json", [
            "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNInverstPosition"
            f"?FCODE={c}&deviceid=Wap&plat=Wap&product=EFund&version=6.2.8",
        ])

    # 7. 逐只：分时 + 日/周/月线
    for c in codes:
        mk = market_of(c)
        fetch_save(f"minute_{c}.json",
                   [f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={mk}{c}"],
                   timeout=20)
        for freq in ("day", "week", "month"):
            fetch_save(f"{freq}_{c}.json", [
                f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mk}{c},{freq},,,640,qfq",
            ], timeout=20)
            time.sleep(0.3)

    print(f"完成：{len(codes)} 只 ETF 的实时三源 + 分时 + 日/周/月线 + "
          f"三源快讯 + 指数 + 板块 + 外盘 + 份额/重仓已保存到 {DATA_DIR}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
