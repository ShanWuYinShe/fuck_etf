#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘中数据监控：每 2 分钟采集一轮（仅采集，不分析）。

用法：
    python3 monitor.py            # 盘中自动循环（午休与收盘后暂停）
    python3 monitor.py --once     # 只采集一轮
    python3 monitor.py --until-close  # 供计划任务使用：9:25 启动，15:05 自动结束
"""

import datetime
import os
import subprocess
import sys
import time


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FETCH = [sys.executable, os.path.join(BASE_DIR, "fetch_etf_data.py")]


def hhmm(now=None):
    now = now or datetime.datetime.now()
    return now.hour * 100 + now.minute


def in_trading_window(now=None):
    h = hhmm(now)
    return (930 <= h <= 1130) or (1300 <= h <= 1500)


def run_once():
    return subprocess.call(FETCH)


def main():
    args = sys.argv[1:]
    if "--once" in args:
        return run_once()
    until_close = "--until-close" in args
    while True:
        now = datetime.datetime.now()
        h = hhmm(now)
        if until_close and (h >= 1505 or h < 930):
            print(f"{now:%H:%M:%S} 已收盘，监控会话结束")
            return 0
        if in_trading_window(now):
            run_once()
        else:
            print(f"{now:%H:%M:%S} 非交易时段，跳过采集")
        time.sleep(120)


if __name__ == "__main__":
    sys.exit(main())
