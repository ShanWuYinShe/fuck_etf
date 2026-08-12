#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""晨间预案（8:40）：采集最新数据，供 AI 开盘前分析。跨平台，仅需 python3。"""

import os
import subprocess
import sys


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    print("== 采集最新数据 ==")
    rc = subprocess.call([sys.executable, os.path.join(BASE_DIR, "fetch_etf_data.py")])
    if rc != 0:
        return rc
    print("")
    print("数据已更新到 .workwork/data/，请将 PROMPT_full.md 与最新数据交给 AI 进行晨间分析；")
    print("AI 分析前必须先读取 .workwork/holdings.json 获取最新持仓。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
