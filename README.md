# ETF 交易辅助（以 AI 分析为核心）

核心思路：**脚本只负责采集数据，分析和决策交给 AI**。把 [PROMPT_full.md](PROMPT_full.md) 作为系统提示词交给 AI（含消息面规则、操作纪律；持仓以 `holdings.json` 为准、标的全集以 `etf_list` 为准，每轮动态读取），AI 结合行情与消息面给出操作建议。

## 使用流程

```bash
# 1. 采集数据（需联网；etf_list 中每行一个 6 位代码）
python3 fetch_etf_data.py

# 2. 把 PROMPT_full.md 发给 AI，并告诉它数据已采集，让它分析
```

所有脚本均为 Python 标准库实现，**Windows / macOS / Linux 通用**，只需安装 Python 3（无需 bash、curl、iconv、任何第三方包），可在任意目录调用。

## 在新电脑上使用（任意平台）

1. 安装 Python 3（Windows 安装时可勾选“Add python.exe to PATH”；命令可能是 `python` 而非 `python3`）。
2. 拷贝或克隆整个项目目录。
3. 首次配置：`cp holdings.example.json holdings.json`（Windows 用 `copy` 或资源管理器复制），按实际持仓修改成本/数量/批次/处理线；`etf_list` 按需增删标的。`holdings.json` 与 `etf_list` 为**入库数据源（git 管理）**，改持仓/自选只改这两个文件，可跨设备同步。
4. 采集：`python3 fetch_etf_data.py`；晨间预案：`python3 morning_plan.py`；盘中监控：`python3 monitor.py --once`。
5. 自动化：`python3 automations/install.py`（macOS→launchd、Linux→crontab、Windows→任务计划程序），卸载用 `automations/uninstall.py`。

## 自动化（三平台）

安装后自动创建两个任务：

- 工作日 08:40 执行 `morning_plan.py`（采集数据，供 AI 晨间分析）；
- 工作日 09:25 启动 `monitor.py --until-close`（盘中每 2 分钟采集，15:05 自动结束，仅采集不分析）。

日志位置：macOS `~/Library/Logs/etf-*.log`；Linux/Windows `~/.etf_logs/`。

## 数据说明

- 实时行情：腾讯（主）+ 新浪/东财（校验）；分时 VWAP、日K 支撑目标、**十一源快讯每轮实时采集并行合并（`news_merged.json`：国内7源直连 [金十/新浪7x24/东财/同花顺/华尔街见闻/网易7x24/新浪滚动] + 国外4源走代理 [Google新闻/Yahoo财经/BBC商业/MarketWatch]）+ 重仓股公告（`news_ann.json`）**、大盘指数、板块主力资金、外盘（美股/港股/期货/黄金/原油/汇率）、ETF 份额与季报重仓股。
- `.workwork/data/` 为**最近一轮**采集结果（本机缓存，不入库）：**不保留历史数据**——某项采集失败即删除其旧文件；每轮启动自动清理已移出自选列表的标的缓存。`holdings.json`（持仓，git 管理）与 `etf_list`（自选，git 管理）为入库数据源，跨设备同步。
- 数据接口为免费公开源，可能限流；采集脚本内置多级降级与重试（东财主源失败自动切 push2delay，逐只 ETF 数据并行采集）。
- 每轮生成 `_manifest.json`，记录各数据项采集状态（ok/fail，fail 项无数据文件），供 AI 识别缺项并在输出中标注「该项无数据」，不据缺项或记忆中的旧数据下单。

> 风险提示：输出仅作研究参考，不构成投资建议；信号由人工复核执行，禁止自动下单。
