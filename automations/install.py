#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台自动化安装（仅采集任务）：
    macOS  → launchd（工作日 08:40 晨间采集 + 09:25 盘中会话，15:05 结束）
    Linux  → crontab（同上）
    Windows→ 任务计划程序（schtasks，同上）
"""

import os
import platform
import shutil
import subprocess
import sys


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = shutil.which("python3") or sys.executable
MORNING = os.path.join(BASE_DIR, "morning_plan.py")
MONITOR = os.path.join(BASE_DIR, "monitor.py")


def macos_install():
    import plistlib
    la = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")
    logdir = os.path.join(os.path.expanduser("~"), "Library", "Logs")
    os.makedirs(la, exist_ok=True)
    tasks = {
        "com.etf.morning-plan": ([PY, MORNING], "etf-morning-plan.log", 8, 40),
        "com.etf.market-monitor": ([PY, MONITOR, "--until-close"], "etf-market-monitor.log", 9, 25),
    }
    for label, (args, log, hour, minute) in tasks.items():
        plist_path = os.path.join(la, label + ".plist")
        payload = {
            "Label": label,
            "ProgramArguments": args,
            "StartCalendarInterval": [{"Weekday": w, "Hour": hour, "Minute": minute}
                                      for w in range(1, 6)],
            "StandardOutPath": os.path.join(logdir, log),
            "StandardErrorPath": os.path.join(logdir, log),
        }
        with open(plist_path, "wb") as f:
            plistlib.dump(payload, f)
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", plist_path],
                       capture_output=True)
        subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", plist_path], check=True)
        print(f"已加载：{label}")
    out = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "com.etf" in line:
            print(line)


def linux_install():
    logdir = os.path.join(os.path.expanduser("~"), ".etf_logs")
    os.makedirs(logdir, exist_ok=True)
    lines = [
        "# >>> etf-automations >>>",
        f'40 8 * * 1-5 "{PY}" "{MORNING}" >> "{os.path.join(logdir, "etf-morning-plan.log")}" 2>&1',
        f'25 9 * * 1-5 "{PY}" "{MONITOR}" --until-close >> "{os.path.join(logdir, "etf-market-monitor.log")}" 2>&1',
        "# <<< etf-automations <<<",
    ]
    cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    keep = [l for l in cur.splitlines()
            if "etf-morning-plan" not in l and "etf-market-monitor" not in l
            and "etf-automations" not in l]
    subprocess.run(["crontab", "-"], input="\n".join(keep + lines) + "\n",
                   text=True, check=True)
    print("已写入 crontab（工作日 08:40 晨间 + 09:25 盘中会话）")


def windows_install():
    logdir = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "etf_logs")
    os.makedirs(logdir, exist_ok=True)
    tasks = [
        ("ETF Morning Plan", MORNING, "etf-morning-plan.log", "08:40"),
        ("ETF Market Monitor", MONITOR + " --until-close", "etf-market-monitor.log", "09:25"),
    ]
    for name, script, log, start in tasks:
        redir = f' >> "{os.path.join(logdir, log)}" 2>&1'
        tr = f'cmd /c ""{PY}" "{script}"{redir}"'
        subprocess.run(["schtasks", "/Create", "/TN", name, "/TR", tr,
                        "/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI", "/ST", start, "/F"],
                       check=True)
        print(f"已创建任务：{name}")


def main():
    system = platform.system()
    if system == "Darwin":
        macos_install()
    elif system == "Linux":
        linux_install()
    elif system == "Windows":
        windows_install()
    else:
        print(f"暂不支持的系统：{system}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
