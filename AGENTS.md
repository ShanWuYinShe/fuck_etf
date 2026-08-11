# AGENTS.md（项目事实）

## 项目定位

A股ETF交易辅助：**脚本只负责采集数据，分析与消息面判断交给 AI**。完整规则见 `PROMPT_full.md`（含标的全集、当前持仓、消息面与操作纪律）；`PROMPT.md` 为 v2.0 规则原始存档。

## 常用命令

- 采集：`./fetch_etf_data.sh`（实时三源、分时、日K、三源快讯、指数、板块、外盘、ETF 份额/重仓 → `.workwork/data/`）
- 晨间预案：`./morning_plan.sh`（只采集数据，提示交给 AI 分析）
- 盘中监控：`./monitor.sh`（`--once` 单轮 / `--until-close` 盘中会话，仅采集）
- 自动化（仅 macOS）：`automations/install.sh`（launchd：工作日 08:40 晨间 + 09:25 盘中会话）、`automations/uninstall.sh`

所有脚本从任意目录可调用（内部自动切换到项目根目录）。

## 数据与配置

- `.workwork/` 全部为本机数据（已 gitignore，不入库）：`data/` 行情缓存、`holdings.json` 持仓配置。
- 持仓配置：`.workwork/holdings.json`（模板 `holdings.example.json`）；标的清单：`etf_list`（每行一个 6 位代码）。
- 提示词 `PROMPT_full.md` 内含 10 只标的全集与当前持仓，供直接粘贴给 AI。

## 约束

- 输出全部使用中文；脚本面向 macOS/Linux（bash + curl + iconv + python3），无第三方 Python 依赖。
- 只采集数据与生成建议，禁止自动下单；分析结论由 AI 结合消息面生成、人工复核执行。
- 依赖免费公开行情接口，可能限流；采集脚本内置多级降级与重试。
