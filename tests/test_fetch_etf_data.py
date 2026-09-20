#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_etf_data.py 解析核心离线单测（仅标准库 unittest，零第三方依赖）。

覆盖对抗免费接口结构漂移的两道关键防线：
- _find_lists：按键名递归定位条目列表（不依赖固定层级）；
- _default_content_check：写入前结构校验，漂移即拒收触发换源/重试；
以及 fetch_save 的拒收-换源-清缓存行为、消息源解析器、时间归一化与若干纯函数。

fixtures/ 内样本为 2026-09-21 用脚本自身的 http_get 按生产相同的 URL/请求头/
编码抓取的真实接口响应（K 线行数参数调小以控制体积，结构与生产一致）；
测试中的负例（结构漂移、限流空响应、HTML 错误页等）为按源码逻辑手工构造的字符串，
全部离线运行，不联网。
"""
import contextlib
import datetime
import importlib.util
import io
import json
import os
import re
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
SCRIPT = os.path.join(ROOT, "scripts", "fetch_etf_data.py")
FIXTURES = os.path.join(TESTS_DIR, "fixtures")

_spec = importlib.util.spec_from_file_location("fetch_etf_data", SCRIPT)
f = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(f)


def fixture(name):
    """读取 fixture 原文（与 fetch_save 落盘内容一致：已按接口编码解码后的文本）。"""
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fp:
        return fp.read()


# 手工构造的负例样本（结构漂移 / 限流 / 错误页形态，来源见各用例注释）
VALID_EM = json.dumps({"data": {"total": 1, "diff": [{"f12": "518880", "f14": "黄金ETF"}]}})
VALID_DAY = json.dumps({"data": {"sh512400": {"qfqday": [["2026-09-18", "1.9", "1.9", "1.9", "1.9", "100.0"]]}}})
VALID_MINUTE = json.dumps({"data": {"sh512400": {"data": {"data": ["0930 1.900 100"]}}}})
VALID_META = json.dumps({"data": {"f57": "512400", "f58": "有色金属ETF南方", "f84": 1.0}})
VALID_INDEX_EM = json.dumps({"data": {"klines": ["2026-09-18,3790.0,3796.28,3831.0,3741.0,1,1"]}})


def _jin10_doc(items):
    """按金十响应结构包装条目（data 为条目列表，条目内 data.content 存正文）。"""
    return json.dumps({"data": items}, ensure_ascii=False)


def _jin10_item(time_str, content):
    return {"time": time_str, "data": {"content": content, "title": "", "source_link": ""}}


class TestFindLists(unittest.TestCase):
    """_find_lists：按键名递归定位「键名命中且值为 list」的列表并展平其中 dict。"""

    def test_top_level_list(self):
        a, b = {"k": 1}, {"k": 2}
        self.assertEqual(f._find_lists({"list": [a, b]}, "list"), [a, b])

    def test_nested_independent_of_path(self):
        # 层级漂移（data 包一层、再包一层）不影响定位——这是该工具的核心语义
        a = {"title": "x"}
        doc = {"a": {"b": {"c": {"list": [a]}}}}
        self.assertEqual(f._find_lists(doc, "list"), [a])

    def test_multiple_keys(self):
        a, b = {"t": 1}, {"t": 2}
        doc = {"data": [a], "result": {"list": [b]}}
        self.assertEqual(f._find_lists(doc, "data", "list"), [a, b])

    def test_key_hit_but_not_list_is_recursed_not_collected(self):
        # 键名命中但值为 dict：应继续向内递归，而不是误收 dict 本身
        inner = {"t": 1}
        self.assertEqual(f._find_lists({"list": {"list": [inner]}}, "list"), [inner])

    def test_must_have_filter(self):
        hit, miss = {"rich_text": "x"}, {"other": "y"}
        got = f._find_lists({"list": [hit, miss]}, "list", must_have="rich_text")
        self.assertEqual(got, [hit])

    def test_matched_list_dicts_are_flattened(self):
        # 展平语义：命中列表内的嵌套 dict 也会被产出（新浪 zhibo 富文本条目依赖此行为）
        nested = {"b": 2}
        got = f._find_lists({"list": [{"a": 1, "nested": nested}]}, "list")
        self.assertEqual(got, [{"a": 1, "nested": nested}, nested])

    def test_missing_key_or_scalar_input_returns_empty(self):
        self.assertEqual(f._find_lists({"a": 1}, "list"), [])
        self.assertEqual(f._find_lists("plain string", "list"), [])
        self.assertEqual(f._find_lists({"list": []}, "list"), [])


class TestDefaultContentCheckRealSamples(unittest.TestCase):
    """_default_content_check：真实接口样本必须全部通过校验（否则生产会误拒可用数据）。"""

    def test_real_fixtures_pass(self):
        real = [
            "day_512400.json", "minute_512400.json", "etf_realtime_qq.txt",
            "etf_realtime_sina.txt", "etf_realtime_em.json", "etf_meta_512400.json",
            "top_holdings_512400.json", "boards_up.json", "index_realtime.txt",
            "index_kline_sh.json", "index_kline_em.json", "overseas_realtime_qq.txt",
            "overseas_realtime_sina.txt",
        ]
        for name in real:
            with self.subTest(name=name):
                self.assertIsNone(f._default_content_check(name, fixture(name)))

    def test_day_fixture_passes_under_week_month_names(self):
        # K 线校验对 day/week/month 共用同一键集合，qfqday 在三种频率名下均合法
        text = fixture("day_512400.json")
        for name in ("week_512400.json", "month_512400.json"):
            self.assertIsNone(f._default_content_check(name, text))

    def test_em_second_batch_name_uses_em_branch(self):
        self.assertIsNone(f._default_content_check("etf_realtime_em_2.json", VALID_EM))


class TestDefaultContentCheckDrift(unittest.TestCase):
    """_default_content_check：构造的漂移/限流样本必须被拒收（返回原因字符串）。"""

    def test_non_json_txt_name_skips_check(self):
        # 非 .json/.txt 产物（如 fetch_time.txt 之外的临时名）不做结构校验
        self.assertIsNone(f._default_content_check("foo.html", "<html>anything</html>"))

    def test_day_kline_drift(self):
        self.assertEqual(f._default_content_check("day_x.json", "not json"), "非 JSON")
        self.assertEqual(f._default_content_check("day_x.json", "<html>风控页</html>"), "非 JSON")
        self.assertEqual(f._default_content_check("day_x.json", '{"data": null}'),
                         "data 为空或非 dict")
        self.assertEqual(f._default_content_check("day_x.json", '{"data": {}}'),
                         "data 为空或非 dict")
        self.assertEqual(
            f._default_content_check("day_x.json", '{"data": {"sh512400": {"qt": 1}}}'),
            "内层缺 day/qfqday/week/month 非空K线列表")
        # K线列表为空列表同样拒收
        self.assertEqual(
            f._default_content_check("day_x.json", '{"data": {"sh512400": {"day": []}}}'),
            "内层缺 day/qfqday/week/month 非空K线列表")

    def test_minute_drift(self):
        self.assertEqual(f._default_content_check("minute_x.json", "not json"), "非 JSON")
        self.assertEqual(f._default_content_check("minute_x.json", '{"data": {}}'),
                         "data.{code}.data.data 缺失/为空")
        self.assertEqual(
            f._default_content_check("minute_x.json", '{"data": {"sh512400": {"data": {"data": []}}}}'),
            "data.{code}.data.data 缺失/为空")

    def test_realtime_qq_drift(self):
        self.assertEqual(f._default_content_check("etf_realtime_qq.txt", "v_none=\"\""),
                         "无 ~ 分隔行情字段")

    def test_realtime_sina_rate_limit(self):
        # 新浪限流形态：保留 hq_str_ 变量但引号内为空
        self.assertEqual(f._default_content_check("etf_realtime_sina.txt", 'hq_str_sh518880=""'),
                         "无 hq_str_ 非空行情（限流空响应或改版）")
        self.assertEqual(f._default_content_check("etf_realtime_sina.txt", "var hq_str_="),
                         "无 hq_str_ 非空行情（限流空响应或改版）")

    def test_realtime_em_drift(self):
        name = "etf_realtime_em.json"
        self.assertEqual(f._default_content_check(name, "not json"), "非 JSON")
        self.assertEqual(f._default_content_check(name, '{"data": null}'), "data.diff 缺失/为空")
        self.assertEqual(f._default_content_check(name, '{"data": {"diff": []}}'),
                         "data.diff 缺失/为空")

    def test_etf_meta_drift(self):
        self.assertEqual(f._default_content_check("etf_meta_x.json", "not json"), "非 JSON")
        self.assertEqual(f._default_content_check("etf_meta_x.json", '{"rc": 0}'), "data 缺失/为空")
        self.assertEqual(f._default_content_check("etf_meta_x.json", '{"data": {}}'), "data 缺失/为空")

    def test_top_holdings_drift_and_empty_fundstocks(self):
        name = "top_holdings_512400.json"
        self.assertEqual(f._default_content_check(name, "not json"), "非 JSON")
        self.assertEqual(f._default_content_check(name, '{"Datas": []}'),
                         "缺 fundStocks 键（错误响应或改版）")
        # 黄金等无股票持仓的 ETF fundStocks 为空列表属正常，须放行
        self.assertIsNone(f._default_content_check(name, '{"fundStocks": []}'))

    def test_boards_drift(self):
        name = "boards_up.json"
        self.assertEqual(f._default_content_check(name, '{"data": {"diff": []}}'),
                         "data.diff 缺失/为空（非交易时段 f3=0 属正常，diff 须非空）")

    def test_index_kline_dual_source(self):
        name = "index_kline_sh.json"
        # 腾讯 day 与东财 klines 双结构均须放行（任一单源可用即不得误判为改版）
        self.assertIsNone(f._default_content_check(name, VALID_DAY))
        self.assertIsNone(f._default_content_check(name, VALID_INDEX_EM))
        self.assertEqual(
            f._default_content_check(name, '{"data": {"sh000001": {"qt": 1}}}'),
            "无可用K线（腾讯 day/qfqday 与东财 klines 均缺失/为空）")
        self.assertEqual(f._default_content_check(name, '{"data": {"klines": []}}'),
                         "无可用K线（腾讯 day/qfqday 与东财 klines 均缺失/为空）")


class TestEmDiff(unittest.TestCase):
    def test_valid_returns_list(self):
        d = json.loads(VALID_EM)
        self.assertEqual(f._em_diff(d), [{"f12": "518880", "f14": "黄金ETF"}])

    def test_invalid_shapes_return_none(self):
        self.assertIsNone(f._em_diff({"data": None}))
        self.assertIsNone(f._em_diff({"data": {"diff": None}}))
        self.assertIsNone(f._em_diff({"data": {"diff": {"a": 1}}}))
        self.assertIsNone(f._em_diff({"rc": 0}))
        self.assertIsNone(f._em_diff("not a dict"))
        self.assertIsNone(f._em_diff(None))


class TestNewsParsers(unittest.TestCase):
    """消息源解析器：真实样本须解出非空条目，且统一 schema 五键齐全。"""

    def setUp(self):
        self._orig = f.DATA_DIR
        f.DATA_DIR = FIXTURES

    def tearDown(self):
        f.DATA_DIR = self._orig

    CASES = [
        (f.parse_news_jin10, "金十"),
        (f.parse_news_sina_zhibo, "新浪7x24"),
        (f.parse_news_eastmoney, "东方财富"),
        (f.parse_news_10jqka, "同花顺"),
        (f.parse_news_wallstcn, "华尔街见闻"),
        (f.parse_news_netease, "网易7x24"),
        (f.parse_news_sina_roll, "新浪滚动"),
        (f.parse_news_google, "Google新闻"),
        (f.parse_news_marketwatch, "MarketWatch"),
    ]

    def test_sources_parse_nonempty_with_uniform_schema(self):
        for fn, source in self.CASES:
            with self.subTest(source=source):
                items = fn()
                self.assertGreaterEqual(len(items), 1, f"{source} 解析出 0 条")
                for it in items:
                    self.assertEqual(set(it), {"time", "source", "title", "text", "url"})
                    self.assertEqual(it["source"], source)
                    self.assertTrue(it["title"], "title 不应为空")
                    self.assertTrue(it["text"], "text 不应为空")

    def test_sina_zhibo_bracket_title_extraction(self):
        # text 以【标签】开头时 title 取标签内文本（结构漂移时最易丢的细节）
        for it in f.parse_news_sina_zhibo():
            m = re.match(r"^【(.+?)】", it["text"])
            if m:
                self.assertEqual(it["title"], m.group(1))

    def test_eastmoney_strips_js_prefix(self):
        # 真实响应以 var ajaxResult= 开头，剥前缀失败会整体解析为 0 条
        self.assertTrue(fixture("news_eastmoney.txt").lstrip().startswith("var "))
        self.assertGreaterEqual(len(f.parse_news_eastmoney()), 10)

    def test_netease_strips_callback_prefix(self):
        self.assertTrue(fixture("news_netease.txt").lstrip().startswith("data_callback("))
        self.assertGreaterEqual(len(f.parse_news_netease()), 10)

    def test_jin10_filters_locked_entries(self):
        # PLUS 锁定条目 content 为空，必须被过滤（不允许出现空 text）
        for it in f.parse_news_jin10():
            self.assertTrue(it["text"])

    def test_missing_raw_file_yields_empty_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            f.DATA_DIR = tmp
            for fn, _ in self.CASES:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(fn(), [])
                self.assertIn("解析异常", buf.getvalue())


class TestMergeNews(unittest.TestCase):
    """merge_news：时效过滤、标题去重、150 条上限（构造样本，驱动数据动态生成）。"""

    def setUp(self):
        self._orig = f.DATA_DIR
        self._tmp = tempfile.TemporaryDirectory()
        f.DATA_DIR = self._tmp.name
        f._manifest.clear()

    def tearDown(self):
        f.DATA_DIR = self._orig
        self._tmp.cleanup()

    def _write_jin10(self, items):
        with open(os.path.join(f.DATA_DIR, "news_jin10.json"), "w", encoding="utf-8") as fp:
            fp.write(_jin10_doc(items))

    def test_stale_filtered_and_dedup_by_title(self):
        now = datetime.datetime.now()
        fresh = (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        stale = (now - datetime.timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        self._write_jin10([
            _jin10_item(fresh, "独家测试条目甲"),
            _jin10_item(fresh, "独家测试条目甲"),   # 标题重复 → 去重
            _jin10_item(fresh, "独家测试条目乙"),
            _jin10_item(stale, "陈旧测试条目丙"),   # 超过 MAX_NEWS_AGE_DAYS → 丢弃
        ])
        with contextlib.redirect_stdout(io.StringIO()):
            items = f.merge_news()
        titles = {it["title"] for it in items}
        self.assertEqual(titles, {"独家测试条目甲", "独家测试条目乙"})
        self.assertEqual(len(items), 2)

    def test_cap_150(self):
        t = (datetime.datetime.now() - datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        self._write_jin10([_jin10_item(t, f"容量测试条目{i:04d}") for i in range(160)])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(len(f.merge_news()), 150)

    def test_unparseable_time_kept(self):
        # 时间不可解析的条目不误杀（保留供人工/AI 判断）
        self._write_jin10([_jin10_item("无法解析的时间", "时间异常测试条目")])
        with contextlib.redirect_stdout(io.StringIO()):
            items = f.merge_news()
        self.assertEqual([it["title"] for it in items], ["时间异常测试条目"])


class TestNormTime(unittest.TestCase):
    def test_unix_seconds_roundtrip(self):
        # 期望值按本地时区往返验证，保证测试本身与时区无关
        result = f._norm_time("1726900000")
        self.assertRegex(result, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertEqual(
            datetime.datetime.strptime(result, "%Y-%m-%d %H:%M:%S").timestamp(), 1726900000)

    def test_mmddyyyy_format(self):
        self.assertEqual(f._norm_time("09/21/2026 05:00:00"), "2026-09-21 05:00:00")

    def test_passthrough_truncated_to_19(self):
        self.assertEqual(f._norm_time("2026-09-21 05:00:00.123"), "2026-09-21 05:00:00")

    def test_empty_and_short_inputs(self):
        self.assertEqual(f._norm_time(""), "")
        self.assertEqual(f._norm_time(None), "")
        self.assertEqual(f._norm_time("123"), "123")

    def test_invalid_keeps_original(self):
        self.assertEqual(f._norm_time("2026-13-99 99:99"), "2026-13-99 99:99")


class TestNormRssTime(unittest.TestCase):
    def test_rfc2822_with_offset_converts_to_beijing(self):
        # -0400 → UTC 05:30 → 北京 13:30
        self.assertEqual(f._norm_rss_time("Mon, 21 Sep 2026 01:30:00 -0400"),
                         "2026-09-21 13:30:00")

    def test_rfc2822_gmt(self):
        self.assertEqual(f._norm_rss_time("Mon, 21 Sep 2026 01:30:00 GMT"),
                         "2026-09-21 09:30:00")

    def test_iso8601_z(self):
        self.assertEqual(f._norm_rss_time("2026-09-21T01:30:00Z"), "2026-09-21 09:30:00")

    def test_iso8601_already_beijing_not_shifted(self):
        # 已带 +08:00 的不得重复加 8 小时
        self.assertEqual(f._norm_rss_time("2026-09-21T09:30:00+08:00"), "2026-09-21 09:30:00")

    def test_naive_iso_treated_as_utc_plus_8(self):
        self.assertEqual(f._norm_rss_time("2026-09-21T01:30:00"), "2026-09-21 09:30:00")

    def test_empty_and_unparseable(self):
        self.assertEqual(f._norm_rss_time(""), "")
        self.assertEqual(f._norm_rss_time("not-a-date"), "not-a-date")


class TestPureHelpers(unittest.TestCase):
    def test_market_of(self):
        self.assertEqual(f.market_of("518880"), "sh")
        self.assertEqual(f.market_of("512400"), "sh")
        self.assertEqual(f.market_of("110038"), "sh")   # 11 开头可转债/沪市
        self.assertEqual(f.market_of("159915"), "sz")
        self.assertEqual(f.market_of("300750"), "sz")

    def test_em_secid(self):
        self.assertEqual(f.em_secid("518880"), "1.518880")
        self.assertEqual(f.em_secid("159915"), "0.159915")

    def test_read_codes_from_cli(self):
        got = f.read_codes("518880, 159915 abc 512400 51888")
        self.assertEqual(got, ["518880", "159915", "512400"])  # 非法片段被过滤
        self.assertEqual(f.read_codes(",,, "), [])

    def test_find_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            # 文件入参 + scripts 目录 → 上溯到含 .git 的根
            os.makedirs(os.path.join(tmp, "r", ".git"))
            os.makedirs(os.path.join(tmp, "r", "scripts"))
            marker = os.path.join(tmp, "r", "scripts", "fetch.py")
            open(marker, "w").close()
            self.assertEqual(f._find_project_root(marker), os.path.join(tmp, "r"))
            # 目录名恰为 scripts → 根为其父目录
            os.makedirs(os.path.join(tmp, "a", "scripts"))
            self.assertEqual(f._find_project_root(os.path.join(tmp, "a", "scripts")),
                             os.path.join(tmp, "a"))
            # config/etf_list.txt 标记
            os.makedirs(os.path.join(tmp, "p", "config"))
            open(os.path.join(tmp, "p", "config", "etf_list.txt"), "w").close()
            self.assertEqual(f._find_project_root(os.path.join(tmp, "p")), os.path.join(tmp, "p"))
            # 从深层子目录向上找到 .git
            deep = os.path.join(tmp, "r", "sub", "deep")
            os.makedirs(deep)
            self.assertEqual(f._find_project_root(deep), os.path.join(tmp, "r"))


class TestFetchSave(unittest.TestCase):
    """fetch_save：拒收-换源-清缓存（离线：打桩 http_get，指向临时 DATA_DIR）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_data_dir, self._orig_http_get = f.DATA_DIR, f.http_get
        f.DATA_DIR = self._tmp.name
        f._manifest.clear()

    def tearDown(self):
        f.DATA_DIR, f.http_get = self._orig_data_dir, self._orig_http_get
        self._tmp.cleanup()

    def _fake_get(self, behaviors):
        """按 URL 顺序出栈的 http_get 打桩：抛异常=网络失败，字符串=响应体。"""
        queue = list(behaviors)
        def fake(url, **kwargs):
            b = queue.pop(0)
            if isinstance(b, Exception):
                raise b
            return b
        return fake

    def _path(self, name):
        return os.path.join(f.DATA_DIR, name)

    def test_first_url_ok(self):
        f.http_get = self._fake_get([VALID_EM])
        self.assertEqual(f.fetch_save("etf_realtime_em.json", ["u1"], retries=1), "ok")
        with open(self._path("etf_realtime_em.json"), encoding="utf-8") as fp:
            self.assertEqual(fp.read(), VALID_EM)
        self.assertEqual(f._manifest["etf_realtime_em.json"], "ok")

    def test_network_error_falls_back_to_next_url(self):
        f.http_get = self._fake_get([OSError("timeout"), VALID_EM])
        self.assertEqual(f.fetch_save("etf_realtime_em.json", ["u1", "u2"], retries=1), "ok")
        self.assertEqual(f._manifest["etf_realtime_em.json"], "ok")

    def test_structure_drift_rejected_then_fallback(self):
        # 核心防线：看似 200 实则无效的 data:null 须被拒收并换下一源
        f.http_get = self._fake_get(['{"data": null}', VALID_EM])
        self.assertEqual(f.fetch_save("etf_realtime_em.json", ["u1", "u2"], retries=1), "ok")

    def test_html_error_page_rejected(self):
        f.http_get = self._fake_get(["<html><body>503</body></html>", VALID_EM])
        self.assertEqual(f.fetch_save("etf_realtime_em.json", ["u1", "u2"], retries=1), "ok")

    def test_empty_body_rejected(self):
        f.http_get = self._fake_get(["   \n", VALID_EM])
        self.assertEqual(f.fetch_save("etf_realtime_em.json", ["u1", "u2"], retries=1), "ok")

    def test_all_fail_removes_old_cache(self):
        # 不保留历史数据：失败即删除旧文件，避免旧数据被当实时数据使用
        os.makedirs(f.DATA_DIR, exist_ok=True)
        with open(self._path("etf_realtime_em.json"), "w", encoding="utf-8") as fp:
            fp.write("stale")
        f.http_get = self._fake_get([OSError("down"), OSError("down")])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = f.fetch_save("etf_realtime_em.json", ["u1", "u2"], retries=1)
        self.assertEqual(result, "fail")
        self.assertFalse(os.path.exists(self._path("etf_realtime_em.json")))
        self.assertEqual(f._manifest["etf_realtime_em.json"], "fail")
        self.assertIn("所有数据源均失败", buf.getvalue())


class TestManifest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = f.DATA_DIR
        f.DATA_DIR = self._tmp.name
        f._manifest.clear()

    def tearDown(self):
        f.DATA_DIR = self._orig
        self._tmp.cleanup()

    def test_record_and_write(self):
        f._record("a.json", "ok")
        f._record("b.json", "fail")
        f._record("b.json", "ok")  # 同名重采覆盖为最新状态
        summary = f.write_manifest("2026-09-21 05:00:00")
        # summary 初始含 ok/fail 两键，未被触发的 fail 保留 0
        self.assertEqual(summary, {"ok": 2, "fail": 0})
        with open(os.path.join(f.DATA_DIR, "_manifest.json"), encoding="utf-8") as fp:
            doc = json.load(fp)
        self.assertEqual(doc["files"], {"a.json": "ok", "b.json": "ok"})
        self.assertEqual(doc["summary"], {"ok": 2, "fail": 0})
        self.assertEqual(doc["fetch_time"], "2026-09-21 05:00:00")


if __name__ == "__main__":
    unittest.main()
