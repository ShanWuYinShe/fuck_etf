# 文件命名规范（重命名方案）

## 原则
1. 含义明确，无歧义
2. 一致前缀分类（`etf_` / `index_` / `news_` / `boards_` / `global_`）
3. 避免与 `holdings.json` 冲突

## 项目级文件（git 管理）

| 旧 | 新 | 理由 |
|---|---|---|
| `AGENTS.md` | 不变 | 已清晰 |
| `PROMPT_full.md` | 不变 | 已清晰 |
| `README.md` | 不变 | 已清晰 |
| `config/etf_list.txt` | 不变 | 已清晰 |
| `config/holdings.json` | 不变 | 用户说明：记录所有持仓+批次买入卖出 |
| `config/holdings.example.json` | 不变 | 模板 |
| `scripts/fetch_etf_data.py` | 不变 | 已清晰 |
| `scripts/monitor.py` | 不变 | 已清晰 |
| `scripts/morning_plan.py` | 不变 | 已清晰 |

## 数据文件

### 行情类（按标的）

| 旧 | 新 | 理由 |
|---|---|---|
| `day_<code>.json` | 不变 | 日K 含义清晰 |
| `week_<code>.json` | 不变 | 周K |
| `month_<code>.json` | 不变 | 月K |
| `minute_<code>.json` | 不变 | 分时 |
| `fund_<code>.json` | `etf_meta_<code>.json` | `fund` 含义不清，改 `etf_meta`（ETF 元信息：份额/规模/资金流） |
| `holdings_<code>.json` | `top_holdings_<code>.json` | **避免与 `holdings.json`（我的持仓）冲突**——明确"前 N 大重仓股" |

### 实时行情（A 股）

| 旧 | 新 | 理由 |
|---|---|---|
| `realtime.txt` | `etf_realtime_qq.txt` | 加 `etf_` 前缀，标 `qq` = 腾讯主源 |
| `realtime_sina.txt` | `etf_realtime_sina.txt` | 同上 |
| `realtime_eastmoney.json` | `etf_realtime_em.json` | 同上 |
| `realtime_eastmoney_2.json` | `etf_realtime_em_2.json` | 同上 |
| `realtime_iopv.json` | `etf_iopv.json` | 缩写 + 加 etf_ |

### 指数

| 旧 | 新 | 理由 |
|---|---|---|
| `index_realtime.txt` | 不变 | 已清晰 |
| `index_kline_sh.json` | 不变 | 已清晰 |
| `index_kline_sz.json` | 不变 | 已清晰 |

### 板块

| 旧 | 新 | 理由 |
|---|---|---|
| `boards_up.json` | 不变 | 已清晰 |
| `boards_down.json` | 不变 | 已清晰 |

### 外盘

| 旧 | 新 | 理由 |
|---|---|---|
| `global_realtime.txt` | `overseas_realtime_qq.txt` | `global_` 不规范，改 `overseas_` + 标源 |
| `global_sina.txt` | `overseas_realtime_sina.txt` | 同上 |

### 快讯（消息面）

| 旧 | 新 | 理由 |
|---|---|---|
| `news_merged.json` | 不变 | 已清晰 |
| `news_ann.json` | 不变 | 已清晰 |
| `news_jin10.json` | 不变 | 源名清晰 |
| `news.json` | `news_sina.json` | 旧名 `news.json` 含义不清 |
| `news_eastmoney.txt` | 不变 | 清晰 |
| `news_10jqka.json` | 不变 | 清晰（同花顺） |
| `news_wallstcn.json` | 不变 | 清晰（华尔街见闻） |
| `news_163.txt` | `news_netease.txt` | `_163` 是域名，改 `_netease` 更明确 |
| `news_sina_roll.json` | 不变 | 清晰 |
| `news_google.json` | 不变 | 清晰 |
| `news_yahoo.json` | 不变 | 清晰 |
| `news_bbc.json` | 不变 | 清晰 |
| `news_marketwatch.json` | 不变 | 清晰 |

### 元数据

| 旧 | 新 | 理由 |
|---|---|---|
| `_manifest.json` | 不变 | 业界约定（_ 开头表示元数据） |
| `fetch_time.txt` | 不变 | 清晰 |

## 命名总览（最终态）

```
.workwork/data/
├── _manifest.json              # 采集状态汇总
├── fetch_time.txt              # 本轮采集时间
│
├── etf_meta_<code>.json        # ETF 元信息（份额/规模/资金流）
├── etf_realtime_qq.txt         # 实时行情-腾讯主源
├── etf_realtime_sina.txt       # 实时行情-新浪备用
├── etf_realtime_em.json        # 实时行情-东财校验（第一批）
├── etf_realtime_em_2.json      # 实时行情-东财校验（第二批）
├── etf_iopv.json               # 折溢价
├── day_<code>.json             # 日K
├── week_<code>.json            # 周K
├── month_<code>.json           # 月K
├── minute_<code>.json          # 分时
├── top_holdings_<code>.json    # ETF 前 N 大重仓股（避免与我的持仓 holdings.json 混淆）
│
├── index_realtime.txt          # 上证/创指 实时
├── index_kline_sh.json         # 上证近 30 日K
├── index_kline_sz.json         # 创指近 30 日K
│
├── boards_up.json              # 行业板块榜前 10 强（f14 名称/f3 涨跌幅/f62 主力净流入）
├── boards_down.json            # 行业板块榜前 10 弱（同上）
│
├── overseas_realtime_qq.txt    # 外盘-腾讯（道指/纳指/标普/恒指/恒科）
├── overseas_realtime_sina.txt  # 外盘-新浪（黄金/原油/汇率）
│
├── news_merged.json            # 十一源合并去重快讯
├── news_ann.json               # 重仓股公告
├── news_jin10.json             # 金十数据
├── news_sina.json              # 新浪 7x24（原 news.json）
├── news_eastmoney.txt          # 东方财富 7x24
├── news_10jqka.json            # 同花顺
├── news_wallstcn.json          # 华尔街见闻
├── news_netease.txt            # 网易 7x24（原 news_163.txt）
├── news_sina_roll.json         # 新浪滚动财经
├── news_google.json            # Google News（走代理）
├── news_yahoo.json             # Yahoo 财经（走代理）
├── news_bbc.json               # BBC 商业（走代理）
└── news_marketwatch.json       # MarketWatch（走代理）
```
