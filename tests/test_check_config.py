#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_config.py 离线单测（仅标准库 unittest，零第三方依赖）。

真实调用被测模块的 check_etf_list / check_holdings / check_syntax / main，
用临时目录重定向模块级 ROOT/CONFIG_DIR，不读写仓库真实 config/。
覆盖：合法配置通过、holdings 各级结构错误被拒（顶层/账号/持仓/批次字段）、
etf_list.txt 非法行、缺文件与非法 JSON、语法检查与 main() 退出码联动。
"""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
SCRIPT = os.path.join(ROOT, "scripts", "check_config.py")

_spec = importlib.util.spec_from_file_location("check_config", SCRIPT)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)


def valid_holdings():
    """合法持仓样本：与 config/holdings.example.json 结构一致，含空 batches 观察仓。"""
    return {
        "accounts": [
            {
                "name": "测试账户",
                "positions": [
                    {
                        "code": "510300",
                        "name": "沪深300ETF",
                        "batches": [
                            {"cost": 3.9, "shares": 10000, "buy_time": "2026-09-01"},
                        ],
                    },
                    {"code": "512400", "name": "有色金属ETF", "batches": []},
                ],
            }
        ]
    }


class ConfigTestBase(unittest.TestCase):
    """把被测模块的目录指向临时目录，避免触碰真实仓库配置。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name
        self.cfg = os.path.join(self.root, "config")
        os.makedirs(self.cfg)
        self._saved = (cc.ROOT, cc.CONFIG_DIR)
        cc.ROOT, cc.CONFIG_DIR = self.root, self.cfg
        cc.errors.clear()

    def tearDown(self):
        cc.ROOT, cc.CONFIG_DIR = self._saved
        cc.errors.clear()

    def write_json(self, name, obj):
        with open(os.path.join(self.cfg, name), "w", encoding="utf-8") as f:
            f.write(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))


class TestCheckHoldings(ConfigTestBase):
    """check_holdings：合法样本通过，各层级结构错误被拒。"""

    def check(self):
        cc.check_holdings()
        return cc.errors

    def test_valid_holdings_passes(self):
        self.write_json("holdings.json", valid_holdings())
        self.assertEqual(self.check(), [])

    def test_top_level_structure_rejected(self):
        cases = [
            ("[1, 2]", "顶层应为"),          # 顶层不是 dict
            ('{"accounts": {}}', "顶层应为"),  # accounts 不是数组
            ('{"positions": []}', "顶层应为"),  # 缺 accounts
            ('{"accounts": []}', "accounts 为空"),
        ]
        for raw, expect in cases:
            with self.subTest(raw=raw):
                cc.errors.clear()
                self.write_json("holdings.json", raw)
                errors = self.check()
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(expect, errors[0])

    def test_positions_missing_or_empty_rejected(self):
        for positions, expect in [
            (None, "缺少 positions 数组"),   # 缺字段
            ("x", "缺少 positions 数组"),     # 类型非法
            ([], "positions 为空"),
        ]:
            with self.subTest(positions=positions):
                cc.errors.clear()
                doc = valid_holdings()
                doc["accounts"][0]["name"] = "账号A"
                if positions is None:
                    del doc["accounts"][0]["positions"]
                else:
                    doc["accounts"][0]["positions"] = positions
                self.write_json("holdings.json", doc)
                errors = self.check()
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(expect, errors[0])
                self.assertIn("账号A", errors[0])

    def test_invalid_code_rejected(self):
        for code in ["51030", "5103001", "51a300", 510300, None]:
            with self.subTest(code=code):
                cc.errors.clear()
                doc = valid_holdings()
                doc["accounts"][0]["positions"][0]["code"] = code
                self.write_json("holdings.json", doc)
                errors = self.check()
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("不是 6 位数字代码", errors[0])

    def test_missing_or_empty_name_rejected(self):
        for name in [None, ""]:
            with self.subTest(name=name):
                cc.errors.clear()
                doc = valid_holdings()
                pos = doc["accounts"][0]["positions"][0]
                if name is None:
                    del pos["name"]
                else:
                    pos["name"] = name
                self.write_json("holdings.json", doc)
                errors = self.check()
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("缺少 name", errors[0])

    def test_batches_must_be_array(self):
        for batches in [None, {}, "[]"]:
            with self.subTest(batches=batches):
                cc.errors.clear()
                doc = valid_holdings()
                doc["accounts"][0]["positions"][0]["batches"] = batches
                self.write_json("holdings.json", doc)
                errors = self.check()
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("缺少 batches 数组", errors[0])

    def test_empty_batches_is_legal(self):
        """空数组 = 空仓观察（留码跟踪），仅要求是数组，不应报错。"""
        doc = valid_holdings()
        for pos in doc["accounts"][0]["positions"]:
            pos["batches"] = []
        self.write_json("holdings.json", doc)
        self.assertEqual(self.check(), [])

    def test_batch_cost_rejected(self):
        for cost in [0, -1.0, "3.9", None]:
            with self.subTest(cost=cost):
                cc.errors.clear()
                doc = valid_holdings()
                doc["accounts"][0]["positions"][0]["batches"][0]["cost"] = cost
                self.write_json("holdings.json", doc)
                errors = self.check()
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("应为正数", errors[0])

    def test_batch_shares_must_be_int(self):
        for shares in [1.5, "100", None]:
            with self.subTest(shares=shares):
                cc.errors.clear()
                doc = valid_holdings()
                doc["accounts"][0]["positions"][0]["batches"][0]["shares"] = shares
                self.write_json("holdings.json", doc)
                errors = self.check()
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("应为整数", errors[0])

    def test_batch_buy_time_required(self):
        for buy_time in [None, ""]:
            with self.subTest(buy_time=buy_time):
                cc.errors.clear()
                doc = valid_holdings()
                batch = doc["accounts"][0]["positions"][0]["batches"][0]
                if buy_time is None:
                    del batch["buy_time"]
                else:
                    batch["buy_time"] = buy_time
                self.write_json("holdings.json", doc)
                errors = self.check()
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("缺 buy_time", errors[0])

    def test_multiple_errors_accumulate(self):
        doc = valid_holdings()
        pos = doc["accounts"][0]["positions"][0]
        pos["code"] = "51"
        pos["batches"][0]["cost"] = 0
        self.write_json("holdings.json", doc)
        self.assertEqual(len(self.check()), 2)

    def test_invalid_json_rejected(self):
        self.write_json("holdings.json", "{oops")
        errors = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn("不是合法 JSON", errors[0])

    def test_missing_file_rejected(self):
        errors = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn("缺少 holdings.json", errors[0])

    def test_root_location_fallback(self):
        """config/ 缺文件时回退根目录旧位置（与 fetch_etf_data.py 行为一致）。"""
        with open(os.path.join(self.root, "holdings.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(valid_holdings(), ensure_ascii=False))
        self.assertEqual(self.check(), [])


class TestCheckEtfList(ConfigTestBase):
    """check_etf_list：合法清单通过，非法行按非空行序号报错。"""

    def check(self):
        cc.check_etf_list()
        return cc.errors

    def test_valid_list_passes(self):
        self.write_list("510300\n510500\n\n")  # 末尾空行应被忽略
        self.assertEqual(self.check(), [])

    def write_list(self, raw):
        with open(os.path.join(self.cfg, "etf_list.txt"), "w", encoding="utf-8") as f:
            f.write(raw)

    def test_invalid_lines_rejected(self):
        self.write_list("510300\n51030\nabc123\n5103001\n")
        errors = self.check()
        self.assertEqual(len(errors), 3, errors)
        # 行号按「非空行」计数：第 2/3/4 行非法
        self.assertIn("第 2 行「51030」不是 6 位数字代码", errors[0])
        self.assertIn("第 3 行「abc123」不是 6 位数字代码", errors[1])
        self.assertIn("第 4 行「5103001」不是 6 位数字代码", errors[2])

    def test_empty_file_rejected(self):
        self.write_list("\n  \n")
        errors = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn("etf_list.txt 为空", errors[0])

    def test_missing_file_rejected(self):
        errors = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn("缺少 etf_list.txt", errors[0])

    def test_root_location_fallback(self):
        with open(os.path.join(self.root, "etf_list.txt"), "w", encoding="utf-8") as f:
            f.write("510300\n")
        self.assertEqual(self.check(), [])


class TestCheckSyntax(ConfigTestBase):
    """check_syntax：对 ROOT/scripts/*.py 做 py_compile，语法错误被报出。"""

    def test_syntax_error_reported(self):
        scripts_dir = os.path.join(self.root, "scripts")
        os.makedirs(scripts_dir)
        with open(os.path.join(scripts_dir, "good.py"), "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        with open(os.path.join(scripts_dir, "bad.py"), "w", encoding="utf-8") as f:
            f.write("def o(:\n")
        cc.check_syntax()
        self.assertEqual(len(cc.errors), 1, cc.errors)
        self.assertIn("bad.py", cc.errors[0])
        self.assertIn("语法错误", cc.errors[0])


class TestMainWiring(ConfigTestBase):
    """main()：三项检查全部通过返回 0，任一检查发现错误返回 1。"""

    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.root, "scripts"))  # check_syntax 需要
        self.write_json("holdings.json", valid_holdings())
        with open(os.path.join(self.cfg, "etf_list.txt"), "w", encoding="utf-8") as f:
            f.write("510300\n")

    def test_main_returns_zero_when_all_pass(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cc.main(), 0)

    def test_main_returns_one_on_any_error(self):
        with open(os.path.join(self.cfg, "etf_list.txt"), "w", encoding="utf-8") as f:
            f.write("abc\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cc.main(), 1)


if __name__ == "__main__":
    unittest.main()
