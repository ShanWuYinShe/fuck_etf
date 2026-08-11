# ETF 交易辅助（以 AI 分析为核心）

核心思路：**脚本只负责采集数据，分析和决策交给 AI**。把 [PROMPT_full.md](PROMPT_full.md) 作为系统提示词交给 AI（内含 10 只标的全集、当前持仓、消息面规则、操作纪律），AI 结合行情与消息面给出操作建议。

## 使用流程

```bash
# 1. 采集数据（需联网；etf_list 中每行一个 6 位代码）
./fetch_etf_data.sh

# 2. 把 PROMPT_full.md 发给 AI，并告诉它数据已采集，让它分析
```

所有脚本都可在任意目录调用（内部自动定位到项目根目录）；只需 bash、python3、curl、iconv，无第三方 Python 依赖。

## 在新电脑上使用（macOS / Linux）

1. 准备：bash（macOS/Linux 均自带）、python3、curl、iconv（macOS 自带；Linux 需另装）。
2. 拷贝或克隆整个项目目录。
3. 首次配置：`mkdir -p .workwork && cp holdings.example.json .workwork/holdings.json`，按实际持仓修改成本/数量/处理线；`etf_list` 按需增删标的。
4. 采集：`./fetch_etf_data.sh`；晨间预案：`./morning_plan.sh`。
5. 自动化（仅 macOS）：`./automations/install.sh` / `./automations/uninstall.sh`。

## 自动化（仅 macOS）

`./automations/install.sh` 安装 launchd 任务：

- 工作日 08:40 执行 `morning_plan.sh`（采集数据，供 AI 晨间分析）；
- 工作日 09:25 启动 `monitor.sh --until-close`（盘中每 2 分钟采集，15:05 自动结束，仅采集不分析）。

日志在 `~/Library/Logs/etf-*.log`。

## 数据说明

- 实时行情：腾讯（主）+ 新浪/东财（校验）；分时 VWAP、日K 支撑目标、三源快讯（新浪/东财/同花顺）、大盘指数、板块主力资金、外盘（美股/港股/期货/黄金/原油/汇率）、ETF 份额与季报重仓股。
- `.workwork/data/` 为行情与快讯缓存，`.workwork/holdings.json` 为持仓配置（不入库）。
- 数据接口为免费公开源，可能限流；采集脚本内置多级降级与重试。

> 风险提示：输出仅作研究参考，不构成投资建议；信号由人工复核执行，禁止自动下单。
