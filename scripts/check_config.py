#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config/ 离线校验：持仓 JSON 结构与自选代码格式。

config/holdings.json 与 config/etf_list.txt 是全部采集与分析的唯一数据源，
且人工编辑频繁；结构错误此前只会在运行期暴露。本脚本零依赖、不联网，
在改动配置后或提交前跑一遍即可：

    python3 scripts/check_config.py

顺带对 scripts/ 全部 .py 做 py_compile 语法检查（仓库无 lint/CI，这是
最接近"测试"的机械校验）。退出码 0 = 通过；非 0 = 配置或语法有问题。
"""
import json
import os
import py_compile
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(ROOT, "config")

errors = []


def err(msg):
    errors.append(msg)


def config_path(name):
    """配置优先 config/，回退根目录（兼容旧位置），与 fetch_etf_data.py 一致。"""
    for p in (os.path.join(CONFIG_DIR, name), os.path.join(ROOT, name)):
        if os.path.exists(p):
            return p
    return None


def check_etf_list():
    p = config_path("etf_list.txt")
    if not p:
        err("缺少 etf_list.txt（config/ 与仓库根都没找到）")
        return
    with open(p, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    if not lines:
        err("etf_list.txt 为空")
        return
    for i, ln in enumerate(lines, 1):
        if not (len(ln) == 6 and ln.isdigit()):
            err(f"etf_list.txt 第 {i} 行「{ln}」不是 6 位数字代码")


def check_holdings():
    p = config_path("holdings.json")
    if not p:
        err("缺少 holdings.json（config/ 与仓库根都没找到）")
        return
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        err(f"holdings.json 不是合法 JSON: {e}")
        return

    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        err("holdings.json 顶层应为 {\"accounts\": [...]}")
        return
    if not data["accounts"]:
        err("holdings.json accounts 为空")
        return

    for ai, acc in enumerate(data["accounts"], 1):
        name = acc.get("name", f"第{ai}个账号")
        if not isinstance(acc.get("positions"), list):
            err(f"账号「{name}」缺少 positions 数组")
            continue
        if not acc["positions"]:
            err(f"账号「{name}」positions 为空")
            continue
        for pi, pos in enumerate(acc["positions"], 1):
            where = f"账号「{name}」第 {pi} 个持仓"
            code = pos.get("code")
            if not (isinstance(code, str) and len(code) == 6 and code.isdigit()):
                err(f"{where} code「{code}」不是 6 位数字代码")
            if not isinstance(pos.get("name"), str) or not pos["name"]:
                err(f"{where} 缺少 name")
            batches = pos.get("batches")
            # 空数组是合法的观察仓（留码跟踪、无持仓批次），仅要求是数组
            if not isinstance(batches, list):
                err(f"{where} 缺少 batches 数组")
                continue
            for bi, b in enumerate(batches, 1):
                if not isinstance(b.get("cost"), (int, float)) or b["cost"] <= 0:
                    err(f"{where} 第 {bi} 笔 cost「{b.get('cost')}」应为正数")
                if not isinstance(b.get("shares"), int):
                    err(f"{where} 第 {bi} 笔 shares「{b.get('shares')}」应为整数（负数=卖出）")
                if not isinstance(b.get("buy_time"), str) or not b["buy_time"]:
                    err(f"{where} 第 {bi} 笔缺 buy_time")


def check_syntax():
    scripts_dir = os.path.join(ROOT, "scripts")
    for fn in sorted(os.listdir(scripts_dir)):
        if fn.endswith(".py"):
            try:
                py_compile.compile(os.path.join(scripts_dir, fn), doraise=True)
            except py_compile.PyCompileError as e:
                err(f"{fn} 语法错误: {e}")


def main():
    check_etf_list()
    check_holdings()
    check_syntax()
    if errors:
        print(f"✗ 发现 {len(errors)} 处问题：")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("✓ config 校验与脚本语法检查全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
