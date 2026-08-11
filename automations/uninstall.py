#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台自动化卸载：macOS→launchd，Linux→crontab，Windows→任务计划程序。"""

import glob
import os
import platform
import subprocess
import sys


def macos_uninstall():
    la = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")
    for p in glob.glob(os.path.join(la, "com.etf.*.plist")):
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", p], capture_output=True)
        os.remove(p)
        print(f"已移除：{os.path.basename(p)}")


def linux_uninstall():
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    keep = [l for l in cur.splitlines()
            if "etf-morning-plan" not in l and "etf-market-monitor" not in l
            and "etf-automations" not in l]
    subprocess.run(["crontab", "-"], input="\n".join(keep) + "\n", text=True, check=True)
    print("已从 crontab 移除 ETF 自动化任务")


def windows_uninstall():
    for name in ("ETF Morning Plan", "ETF Market Monitor"):
        subprocess.run(["schtasks", "/Delete", "/TN", name, "/F"],
                       capture_output=True)
        print(f"已删除任务：{name}")


def main():
    system = platform.system()
    if system == "Darwin":
        macos_uninstall()
    elif system == "Linux":
        linux_uninstall()
    elif system == "Windows":
        windows_uninstall()
    else:
        print(f"暂不支持的系统：{system}")
        return 1
    print("如需恢复，运行 automations/install.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
