# AGENTS.md（项目事实）

## 项目定位

A股ETF交易辅助：**脚本只负责采集数据，分析与消息面判断交给 AI**。完整规则见 `PROMPT_full.md`（含标的全集、当前持仓、消息面与操作纪律）；`PROMPT.md` 为 v2.0 规则原始存档。

## 常用命令（跨平台，仅需 Python 3）

- 采集：`python3 fetch_etf_data.py`（实时三源、分时、日K、三源快讯、指数、板块、外盘、ETF 份额/重仓 → `.workwork/data/`）
- 晨间预案：`python3 morning_plan.py`（只采集数据，提示交给 AI 分析）
- 盘中监控：`python3 monitor.py`（`--once` 单轮 / `--until-close` 盘中会话，仅采集）
- 自动化：`python3 automations/install.py`（macOS→launchd、Linux→crontab、Windows→任务计划程序）、`python3 automations/uninstall.py`

所有脚本均用 Python 标准库实现，可在任意目录、任意平台（Windows/macOS/Linux）运行。

## 数据与配置

- `.workwork/` 全部为本机数据（已 gitignore，不入库）：`data/` 行情缓存、`holdings.json` 持仓配置。
- 持仓配置：`.workwork/holdings.json`（模板 `holdings.example.json`）；标的清单：`etf_list`（每行一个 6 位代码）。
- 提示词 `PROMPT_full.md` 内含 10 只标的全集与当前持仓，供直接粘贴给 AI。

## 约束

- 输出全部使用中文；仅依赖 Python 3 标准库（urllib），无第三方包。
- 只采集数据与生成建议，禁止自动下单；分析结论由 AI 结合消息面生成、人工复核执行。
- 依赖免费公开行情接口，可能限流；采集脚本内置多级降级与重试。
