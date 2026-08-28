# ETF 交易辅助（以 AI 分析为核心）

核心思路：**脚本只负责采集数据，分析和决策交给 AI**。把 [PROMPT_full.md](PROMPT_full.md) 作为系统提示词交给 AI（含消息面规则、操作纪律；持仓以 `config/holdings.json` 为准、标的全集以 `config/etf_list.txt` 为准，每轮动态读取，兼容根目录旧位置），AI 结合行情与消息面给出操作建议。

## 使用流程

```bash
# 1. 采集数据（需联网；config/etf_list.txt 中每行一个 6 位代码）
python3 scripts/fetch_etf_data.py

# 2. 把 PROMPT_full.md 发给 AI，并告诉它数据已采集，让它分析
```

所有脚本均为 Python 标准库实现，**Windows / macOS / Linux 通用**，只需安装 Python 3（无需 bash、curl、iconv、任何第三方包），可在任意目录调用。

## 在新电脑上使用（任意平台）

1. 安装 Python 3（Windows 安装时可勾选“Add python.exe to PATH”；命令可能是 `python` 而非 `python3`）。
2. 拷贝或克隆整个项目目录。
3. 首次配置：`cp config/holdings.example.json config/holdings.json`（Windows 用 `copy` 或资源管理器复制），按实际持仓只填代码/名称/买入批次（成本/数量/买入时间），**止损/减仓/加仓/目标等处理线不写文件、由 AI 每轮按实时行情推导**；`config/etf_list.txt` 按需增删标的。`config/holdings.json` 与 `config/etf_list.txt` 为**入库数据源（git 管理）**，改持仓/自选只改这两个文件，可跨设备同步（兼容根目录旧文件）。
4. 采集：`python3 scripts/fetch_etf_data.py`；晨间预案：`python3 scripts/morning_plan.py`；盘中监控：`python3 scripts/monitor.py --once`。

## 数据说明

- 实时行情：腾讯（主）+ 新浪/东财（校验）；分时 VWAP、日K 支撑目标、**十一源快讯每轮实时采集并行合并（`news_merged.json`：国内7源直连 [金十/新浪7x24/东财/同花顺/华尔街见闻/网易7x24/新浪滚动] + 国外4源走代理 [Google新闻/Yahoo财经/BBC商业/MarketWatch]）+ 重仓股公告（`news_ann.json`）**、大盘指数、板块主力资金、外盘（美股/港股/期货/黄金/原油/汇率）、ETF 份额与季报重仓股。
- `.workwork/data/` 为**最近一轮**采集结果（本机缓存，不入库）：**不保留历史数据**——某项采集失败即删除其旧文件；每轮启动自动清理已移出自选列表的标的缓存。`config/holdings.json`（持仓，git 管理）与 `config/etf_list.txt`（自选，git 管理）为入库数据源，跨设备同步。
- 数据接口为免费公开源，可能限流；采集脚本内置多级降级与重试（东财主源失败自动切 push2delay，逐只 ETF 数据并行采集）。
- 每轮生成 `_manifest.json`，记录各数据项采集状态（ok/fail，fail 项无数据文件），供 AI 识别缺项并在输出中标注「该项无数据」，不据缺项或记忆中的旧数据下单。

> 风险提示：输出仅作研究参考，不构成投资建议；信号由人工复核执行，禁止自动下单。
