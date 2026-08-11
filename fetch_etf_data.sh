#!/usr/bin/env bash
# 拉取 ETF 行情数据（v2.0 采集规范），输出到 .workwork/data/
#   1) 实时行情三源：腾讯（主）/ 新浪（备）/ 东方财富（校验）
#   2) 分时（VWAP）与日/周/月线（腾讯）
#   3) 财经快讯（新浪 7x24）、大盘指数（上证/创业板 + 成交额）、行业板块榜（东财）
# 用法：
#   ./fetch_etf_data.sh              # 读取 etf_list
#   ./fetch_etf_data.sh 159831 515050

set -e
set -o pipefail

cd "$(dirname "$0")"

DATA_DIR=".workwork/data"
CODES=("$@")
if (( ${#CODES[@]} == 0 )); then
  while IFS= read -r line; do
    if [[ "$line" =~ ([0-9]{6}) ]]; then
      CODES+=("${BASH_REMATCH[1]}")
    fi
  done < etf_list
fi

mkdir -p "$DATA_DIR"

market_of() {
  # 5/11 开头为沪市，其余默认深市
  if [[ "$1" == 5* || "$1" == 11* ]]; then
    echo "sh"
  else
    echo "sz"
  fi
}

# 依次尝试多个 URL，最多 3 轮；拒绝空文件与 HTML 错误页（东财接口偶发空返回/限流）
fetch_save() {
  local name="$1"; shift
  local urls=("$@")
  local attempt u
  for ((attempt = 1; attempt <= 3; attempt++)); do
    for u in "${urls[@]}"; do
      if curl -sS --max-time 12 "$u" -o "$DATA_DIR/$name" \
          && [[ -s "$DATA_DIR/$name" ]] \
          && [[ "$(head -c 1 "$DATA_DIR/$name")" != "<" ]] \
          && ! grep -q '"data":null' "$DATA_DIR/$name"; then
        return 0
      fi
    done
    [[ $attempt -lt 3 ]] && sleep 3
  done
  echo "警告：$name 所有数据源均失败"
  return 1
}

# 采集时间戳（精确到秒），供所有输出标注数据时间
date "+%Y-%m-%d %H:%M:%S" > "$DATA_DIR/fetch_time.txt"

# ---- 1. 实时行情：腾讯主源 ----
QT_URL=""
for c in "${CODES[@]}"; do
  QT_URL+=",$(market_of "$c")$c"
done
curl -sS --max-time 20 "https://qt.gtimg.cn/q=${QT_URL#,}" \
  | iconv -f GBK -t UTF-8 > "$DATA_DIR/realtime.txt"
if [[ ! -s "$DATA_DIR/realtime.txt" ]]; then
  echo "警告：实时行情主源（腾讯）获取失败（realtime.txt 为空）"
fi

# ---- 2. 实时行情备用：新浪 ----
SINA_URL=""
for c in "${CODES[@]}"; do
  SINA_URL+=",$(market_of "$c")$c"
done
curl -sS --max-time 15 -H 'Referer: https://finance.sina.com.cn' \
  "https://hq.sinajs.cn/list=${SINA_URL#,}" \
  | iconv -f GBK -t UTF-8 > "$DATA_DIR/realtime_sina.txt" || true

# ---- 3. 实时行情校验：东方财富（secid：sh=1，sz=0），拆两批避免限流 ----
em_mk() {
  [[ "$(market_of "$1")" == "sh" ]] && echo "1" || echo "0"
}
fetch_em_batch() {
  local name="$1"; shift
  local sec=""
  for c in "$@"; do
    sec+=",$(em_mk "$c").$c"
  done
  fetch_save "$name" \
    "https://push2.eastmoney.com/api/qt/ulist.np/get?secids=${sec#,}&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18,f62" \
    "http://push2.eastmoney.com/api/qt/ulist.np/get?secids=${sec#,}&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18,f62" \
    "https://push2delay.eastmoney.com/api/qt/ulist.np/get?secids=${sec#,}&fields=f2,f3,f4,f5,f6,f12,f14,f15,f16,f17,f18,f62" \
    || true
}
if (( ${#CODES[@]} <= 5 )); then
  fetch_em_batch realtime_eastmoney.json "${CODES[@]}"
else
  fetch_em_batch realtime_eastmoney.json "${CODES[@]:0:5}"
  fetch_em_batch realtime_eastmoney_2.json "${CODES[@]:5}"
fi

# ---- 4. 财经快讯（新浪 7x24，最近 30 条）----
curl -sS --max-time 15 \
  "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=30&zhibo_id=152" \
  -o "$DATA_DIR/news.json" || true

# ---- 4.1 财经快讯补充源：东方财富 7x24 + 同花顺 ----
curl -sS --max-time 15 -A 'Mozilla/5.0' \
  "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_30_1_.html" \
  -o "$DATA_DIR/news_eastmoney.txt" || true
curl -sS --max-time 15 -A 'Mozilla/5.0' \
  "https://news.10jqka.com.cn/tapp/news/push/stock/?page=1&pagesize=30" \
  -o "$DATA_DIR/news_10jqka.json" || true

# ---- 5. 大盘指数：上证/创业板实时 + 近 3 日日K（含成交额，用于对比）----
curl -sS --max-time 15 "https://qt.gtimg.cn/q=sh000001,sz399006" \
  | iconv -f GBK -t UTF-8 > "$DATA_DIR/index_realtime.txt" || true
fetch_save index_kline_sh.json \
  "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000001&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=0&end=20500101&lmt=3" \
  "http://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000001&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=0&end=20500101&lmt=3" \
  || true
fetch_save index_kline_sz.json \
  "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=0.399006&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=0&end=20500101&lmt=3" \
  "http://push2his.eastmoney.com/api/qt/stock/kline/get?secid=0.399006&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=0&end=20500101&lmt=3" \
  || true

# ---- 6. 行业板块榜（东财，最强/最弱各前 10）----
fetch_save boards_up.json \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2+f:!50&fields=f3,f12,f14,f62" \
  "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2+f:!50&fields=f3,f12,f14,f62" \
  "https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2+f:!50&fields=f3,f12,f14,f62" \
  || true
fetch_save boards_down.json \
  "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=0&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2+f:!50&fields=f3,f12,f14,f62" \
  "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=0&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2+f:!50&fields=f3,f12,f14,f62" \
  "https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=10&po=0&np=1&fltt=2&invt=2&fid=f3&fs=m:90+t:2+f:!50&fields=f3,f12,f14,f62" \
  || true

# ---- 6.1 外盘与汇率：美股/港股指数（腾讯）+ 美股期货/黄金/原油/汇率（新浪）----
curl -sS --max-time 15 "https://qt.gtimg.cn/q=usDJI,usIXIC,usINX,hkHSI,hkHSCEI" \
  | iconv -f GBK -t UTF-8 > "$DATA_DIR/global_realtime.txt" || true
curl -sS --max-time 15 -H 'Referer: https://finance.sina.com.cn' \
  "https://hq.sinajs.cn/list=hf_GC,hf_CL,hf_ES,hf_NQ,hf_YM,fx_susdcny" \
  | iconv -f GBK -t UTF-8 > "$DATA_DIR/global_sina.txt" || true

# ---- 6.2 ETF 份额/规模（东财 stock/get）+ 最新季报重仓股（天天基金移动接口）----
for c in "${CODES[@]}"; do
  em="$(em_mk "$c")"
  fetch_save "fund_${c}.json" \
    "https://push2.eastmoney.com/api/qt/stock/get?secid=${em}.${c}&fields=f57,f58,f62,f84,f85" \
    "http://push2.eastmoney.com/api/qt/stock/get?secid=${em}.${c}&fields=f57,f58,f62,f84,f85" \
    "https://push2delay.eastmoney.com/api/qt/stock/get?secid=${em}.${c}&fields=f57,f58,f62,f84,f85" \
    || true
  curl -sS --max-time 12 -A 'Mozilla/5.0' \
    "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNInverstPosition?FCODE=${c}&deviceid=Wap&plat=Wap&product=EFund&version=6.2.8" \
    -o "$DATA_DIR/holdings_${c}.json" || true
done

# ---- 7. 逐只：分时（VWAP）+ 日/周/月线 ----
for c in "${CODES[@]}"; do
  mk="$(market_of "$c")"
  curl -sS --max-time 20 \
    "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=${mk}${c}" \
    -o "$DATA_DIR/minute_${c}.json"
  if [[ ! -s "$DATA_DIR/minute_${c}.json" ]]; then
    echo "警告：${c} 分时数据获取失败"
  fi
  for freq in day week month; do
    curl -sS --max-time 20 -A "Mozilla/5.0" \
      "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${mk}${c},${freq},,,640,qfq" \
      -o "$DATA_DIR/${freq}_${c}.json"
    if [[ ! -s "$DATA_DIR/${freq}_${c}.json" ]]; then
      echo "警告：${c} ${freq} 线获取失败，请稍后重跑"
    fi
    sleep 0.3
  done
done

echo "完成：${#CODES[@]} 只 ETF 的实时三源 + 分时 + 日/周/月线 + 三源快讯 + 指数 + 板块 + 外盘 + 份额/重仓已保存到 $DATA_DIR/"
