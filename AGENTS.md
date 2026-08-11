# AGENTS.md（项目事实）

## 项目定位

A股ETF交易辅助：v2.0 盘中/复盘分析（实时行情、分时 VWAP、T+0/T+1 模式判定、操作指令、消息面、持仓跟踪）+ 2 周波段/长线分析。完整规则见 `PROMPT.md` / `PROMPT_full.md`。

## 常用命令

- 采集：`./fetch_etf_data.sh`（实时三源、分时、日K、三源快讯、指数、板块、外盘、ETF 份额/重仓 → `.workwork/data/`）
- v2.0 分析：`python3 intraday_etf.py`（输出 `.workwork/report/intraday_latest.md` 与 `intraday.json`）
- 旧版波段流程：`python3 analyze_etf.py` / `recommend_etf.py` / `band_plan.py`；一键 `./run_all.sh`
- 晨间预案：`./morning_plan.sh`；盘中监控：`./monitor.sh`（`--once` 单轮 / `--until-close` 盘中会话）
- 自动化：`automations/install.sh`（launchd：工作日 08:40 晨间 + 09:25 盘中会话）、`automations/uninstall.sh`

所有脚本从任意目录可调用（内部自动切换到项目根目录）。

## 数据与配置

- `.workwork/` 全部为本机数据（已 gitignore，不入库）：`data/` 行情缓存、`report/` 报告、`holdings.json` 持仓配置、`shares_cache.json` 份额日变化缓存。
- 持仓配置：`.workwork/holdings.json`（模板 `holdings.example.json`）；标的清单：`etf_list`（每行一个 6 位代码）。
- 提示词 `PROMPT_full.md` 内含 10 只标的全集与当前持仓，供直接粘贴给 AI。

## 约束

- 输出全部使用中文；脚本面向 macOS/Linux（zsh/bash + curl + iconv + python3），无第三方 Python 依赖。
- 只生成分析与下单建议，禁止自动下单；信号由人工复核执行。
- 依赖免费公开行情接口，可能限流；采集脚本内置多级降级与重试。
