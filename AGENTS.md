# AGENTS.md（项目事实）

## 项目定位

A股ETF交易辅助：**脚本只负责采集数据，分析与消息面判断交给 AI**。完整规则见 `PROMPT_full.md`（含持仓/标的的数据源说明、消息面与操作纪律；规则历史版本见 git 历史）。

通用约束（Git 规范、Commit 格式、验证流程等）以全局 `~/AGENTS.md` 为准，本文件只记项目特有事实，不得放宽或违背全局约束。

## 按需加载的 skill（.agents/skills/）

| skill | 何时加载 |
|---|---|
| etf-trading-rules | 输出条件单/做T/止盈止损、判定大盘与板块环境时（策略规则速览，权威来源仍是 PROMPT_full.md） |
| etf-analysis-session | 执行每轮分析会话九步流程时 |


## 常用命令（跨平台，仅需 Python 3）

- 采集：`python3 scripts/fetch_etf_data.py`（实时三源、分时、日K、十一源快讯并行合并 [国内7源直连+国外4源走代理，代理在脚本顶部 PROXY 配置] 与重仓股公告、指数、板块、外盘、ETF 份额/重仓 → `.workwork/data/`）；盘后只刷消息面：`python3 scripts/fetch_etf_data.py --news-only`
- 晨间预案：`python3 scripts/morning_plan.py`（只采集数据，提示交给 AI 分析）
- 盘中监控：`python3 scripts/monitor.py`（`--once` 单轮 / `--until-close` 盘中会话，仅采集）
- 配置校验：`python3 scripts/check_config.py`（改 `config/` 后离线校验结构，无需联网）
- 离线单测：`python3 -m unittest discover -s tests -v`（覆盖 fetch_etf_data.py 解析核心，fixtures 为真实接口样本；push/PR 由 GitHub Actions CI 自动执行同样检查）

所有脚本均在 `scripts/` 目录，用 Python 标准库实现，可在任意目录、任意平台（Windows/macOS/Linux）运行。配置在 `config/` 目录（`holdings.json`/`etf_list.txt`），兼容根目录旧位置。

## 数据与配置

- `.workwork/` 全部为本机数据（已 gitignore，不入库）：本项目兼作**脚本运行数据目录**（历史原因，区别于全局定义的"仅 AI 中间文件"）。`data/` 只存**最近一轮**采集结果，**不保留历史数据**——采集失败即删旧文件（`_manifest.json` 状态仅 ok/fail），每轮启动自动清理已移出自选的标的缓存；快讯每轮实时获取，AI 分析前若快讯滞后应先 `--news-only` 刷新。
- **解析健壮性约定**：免费接口 JSON 结构（key 名/层级）随时可能改版，解析一律走递归工具 `_find_lists`（按键名定位条目列表，不依赖固定路径）+ `_default_content_check`（写入前校验结构，漂移即拒收触发重试/换源）；消息源解析 0 条或结构校验未过会在 stdout 打印告警，AI 分析时若见「解析异常」告警应先修复再采。
- **入库数据源（git 管理，可跨设备同步）**：`config/holdings.json`（持仓唯一数据源，模板 `config/holdings.example.json`）与 `config/etf_list.txt`（自选标的清单，每行一个 6 位代码），兼容根目录旧位置。改持仓/成本/自选只改这两个文件，AI 每次分析前必须读取它们，不依赖提示词内旧数据,config/holdings.json 中某持仓的 `batches` 为空数组（`[]`）说明是空仓。
- 提示词 `PROMPT_full.md` **只含策略规则**（数据源说明、消息面与操作纪律），不内嵌持仓/标的/行情数据；AI 需自行读取 `config/holdings.json` 与 `config/etf_list.txt` 获取最新持仓与自选列表。

## 约束

- **约束**：改 `fetch_etf_data.py` 解析逻辑后，必须跑 `python3 scripts/fetch_etf_data.py --news-only` 冒烟验证（stdout 无「解析异常」告警才算通过）。
- 仅依赖 Python 3 标准库（urllib），无第三方包。
- 只采集数据与生成建议，禁止自动下单；分析结论由 AI 结合消息面生成、人工复核执行。
- 依赖免费公开行情接口，可能限流；采集脚本内置多级降级与重试。

## 关键规则速览（详见 skill etf-trading-rules，权威来源 PROMPT_full.md）

策略条目已移入 skill etf-trading-rules，共 11 条（价差单位与分档、T+1、大盘三级+板块叠加、盈利优先、止损锚结构位、买入单无止损参数、止损单唯一性、禁止裸低吸/残缺做T、代码+名称、预判到期失效），此处不再重复。

## 分析会话标准流程（详见 skill etf-analysis-session）

九步流程（采集→持仓→消息面→板块→大盘→前瞻→操作→复盘→文档维护）已移入 skill etf-analysis-session，此处不再重复。
