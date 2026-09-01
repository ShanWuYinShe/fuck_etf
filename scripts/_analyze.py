# -*- coding: utf-8 -*-
import json, os, sys

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.workwork', 'data')


def ma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def _find_kline_lists(obj, *keys):
    """递归查找「键名为 keys 之一、值为 list」的列表（腾讯K线内层 day/qfqday/week/month，
    东财 K 线 data.klines 均可命中，不依赖固定层级）。"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, list):
                out.append((k, v))
            else:
                out.extend(_find_kline_lists(v, *keys))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_find_kline_lists(v, *keys))
    return out


def load_day(code):
    d = json.load(open(os.path.join(D, 'day_%s.json' % code), encoding='utf-8'))
    # 腾讯K线：data.{sh|sz}{code}.qfqday（多数）或 .day（部分标的）；两者都缺失则报出实际结构
    hits = _find_kline_lists(d, 'qfqday', 'day')
    if not hits:
        raise KeyError('day_%s.json 中找不到 qfqday/day 列表，实际顶层 keys=%s'
                       % (code, list(d.keys())))
    rows_raw = hits[0][1]
    out = []
    for r in rows_raw:
        if isinstance(r, str):
            r = r.split(',')
        out.append((r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
    return out


def load_index_kline(fname):
    d = json.load(open(os.path.join(D, fname), encoding='utf-8'))
    hits = _find_kline_lists(d, 'klines')
    if not hits:
        raise KeyError('%s 中找不到 klines 列表，实际顶层 keys=%s' % (fname, list(d.keys())))
    return [x.split(',') for x in hits[0][1]]


print('=' * 78)
print('[DAPAN]')
for f, nm in [('index_kline_sh.json', 'SH'), ('index_kline_sz.json', 'CYB')]:
    try:
        ks = load_index_kline(f)
    except Exception as e:
        print(nm, 'ERR', e)
        continue
    closes = [float(x[2]) for x in ks]
    vols = [float(x[5]) for x in ks]
    m5, m10, m20 = ma(closes[:-1], 5), ma(closes[:-1], 10), ma(closes[:-1], 20)
    m20_now = ma(closes, 20)
    m20_prev = sum(closes[-21:-1]) / 20
    print('%s: last_close(8/31)=%.2f now(9/1 intraday)=%.2f' % (nm, closes[-2], closes[-1]))
    print('   MA5=%.2f MA10=%.2f MA20=%.2f (excl today) | MA20 incl today=%.2f | slope=%+.2f' %
          (m5, m10, m20, m20_now, m20_now - m20_prev))
    print('   vs MA20: %s (diff %+.2f, %+.2f%%)' %
          ('ABOVE' if closes[-1] > m20_now else 'BELOW', closes[-1] - m20_now, (closes[-1] / m20_now - 1) * 100))
    print('   last6: ' + ' | '.join('%s %.2f' % (k[0][5:], float(k[2])) for k in ks[-6:]))

print()
print('=' * 78)
codes = [
    ('159992', '创新药ETF银华'), ('159516', '半导体设备ETF国泰'), ('588200', '科创芯片ETF嘉实'),
    ('515880', '通信ETF国泰'), ('518880', '黄金ETF华安'), ('513630', '港股低波红利ETF摩根'),
    ('159566', '储能电池ETF易方达'), ('159755', '电池ETF广发'), ('159611', '电力ETF广发'),
    ('512400', '有色金属ETF南方'), ('562800', '稀有金属ETF嘉实'),
]
for c, nm in codes:
    try:
        rows = load_day(c)
    except Exception as e:
        print(c, 'ERR', e)
        continue
    closes = [r[2] for r in rows]
    highs = [r[3] for r in rows]
    lows = [r[4] for r in rows]
    vols = [r[5] for r in rows]
    last_date, last_close = rows[-1][0], rows[-1][2]
    cl2 = closes[:-1]
    m5, m10, m20, m60 = ma(cl2, 5), ma(cl2, 10), ma(cl2, 20), ma(cl2, 60)
    m20_prev = sum(cl2[-21:-1]) / 20
    low10 = min(lows[-11:-1]); high10 = max(highs[-11:-1])
    low20 = min(lows[-21:-1]); high20 = max(highs[-21:-1])
    v5 = ma(vols[:-1], 5)
    vr = vols[-2] / v5 if v5 else 0
    print('-' * 74)
    print('%s %s | now(%s)=%.3f | prev_close=%.3f' % (c, nm, last_date, last_close, cl2[-1]))
    print('   MA5=%.3f MA10=%.3f MA20=%.3f MA60=%.3f | MA20 slope=%+.4f | pos=%s' %
          (m5, m10, m20, m60, m20 - m20_prev, 'ABOVE' if cl2[-1] > m20 else 'BELOW'))
    print('   10d range %.3f-%.3f | 20d range %.3f-%.3f' % (low10, high10, low20, high20))
    print('   close8: ' + ' '.join('%.3f' % x for x in closes[-8:]))
    print('   vol8(w): ' + ' '.join('%.0f' % (x / 1e4) for x in vols[-8:]))
    print('   prev_day_vol/ma5vol=%.2fx | today_vol(10min)=%.0fw' % (vr, vols[-1] / 1e4))
    print('   chg5 %+.2f%% | chg10 %+.2f%% | chg20 %+.2f%%' %
          ((cl2[-1] / cl2[-6] - 1) * 100, (cl2[-1] / cl2[-11] - 1) * 100, (cl2[-1] / cl2[-21] - 1) * 100))
    print('   low10=%.3f | now vs low10 %+.2f%% | now vs MA20 %+.2f%%' %
          (low10, (last_close / low10 - 1) * 100, (last_close / m20 - 1) * 100))
