"""验证 Market 协议中受控的展示字段：display.badge 与 tag_definitions。
两者都只能从 market.json 进入，必须经过 _normalize_display / _normalize_tag_definitions
做白名单/枚举/长度过滤，非法值静默丢弃。
"""
import unittest


class MarketDisplayBadgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from market import _normalize_display  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(f"market module unavailable: {exc}")

    def test_valid_badge_passes_through(self):
        from market import _normalize_display

        self.assertEqual(
            _normalize_display({"badge": {"text": "鲁", "tone": "orange"}}),
            {"badge": {"text": "鲁", "tone": "orange"}},
        )

    def test_invalid_tone_dropped(self):
        from market import _normalize_display

        out = _normalize_display({"badge": {"text": "鲁", "tone": "rainbow"}})
        # text 保留，tone 被丢弃
        self.assertEqual(out, {"badge": {"text": "鲁"}})

    def test_html_text_dropped(self):
        from market import _normalize_display

        out = _normalize_display({"badge": {"text": "<script>x</script>", "tone": "rose"}})
        # 文本含 HTML 字符 → text 整体丢弃；tone 仍合法保留。
        self.assertEqual(out, {"badge": {"tone": "rose"}})

    def test_overlong_text_truncated(self):
        from market import _normalize_display, BADGE_TEXT_MAX_GRAPHEMES

        out = _normalize_display({"badge": {"text": "超长徽章测试"}})
        self.assertLessEqual(len(out["badge"]["text"]), BADGE_TEXT_MAX_GRAPHEMES)

    def test_non_dict_returns_empty(self):
        from market import _normalize_display

        self.assertEqual(_normalize_display(None), {})
        self.assertEqual(_normalize_display("anything"), {})
        self.assertEqual(_normalize_display([{"text": "鲁"}]), {})


class MarketTagDefinitionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from market import _normalize_tag_definitions  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(f"market module unavailable: {exc}")

    def test_valid_definition(self):
        from market import _normalize_tag_definitions

        out = _normalize_tag_definitions({
            "央视": {"priority": 100, "tone": "red", "emphasized": True, "aliases": ["CCTV", "CGTN"]},
        })
        self.assertEqual(out["央视"]["priority"], 100)
        self.assertEqual(out["央视"]["tone"], "red")
        self.assertTrue(out["央视"]["emphasized"])
        self.assertEqual(out["央视"]["aliases"], ["CCTV", "CGTN"])

    def test_priority_clamped(self):
        from market import _normalize_tag_definitions

        out = _normalize_tag_definitions({"x": {"priority": 9999}, "y": {"priority": -50}})
        self.assertEqual(out["x"]["priority"], 100)
        self.assertEqual(out["y"]["priority"], 0)

    def test_invalid_tone_dropped(self):
        from market import _normalize_tag_definitions

        out = _normalize_tag_definitions({"x": {"priority": 1, "tone": "fluorescent"}})
        self.assertNotIn("tone", out["x"])

    def test_emphasized_must_be_bool(self):
        from market import _normalize_tag_definitions

        out = _normalize_tag_definitions({"x": {"emphasized": "yes", "priority": 1}})
        self.assertNotIn("emphasized", out["x"])

    def test_one_bad_entry_does_not_kill_others(self):
        from market import _normalize_tag_definitions

        out = _normalize_tag_definitions({
            "央视": {"priority": 100, "tone": "red"},
            "<bad>": {"priority": 50},                # label 含 HTML → 丢弃
            "无规则": {},                               # rule 全部非法 → 跳过
            "体育": {"priority": 90, "tone": "blue"},
        })
        self.assertIn("央视", out)
        self.assertIn("体育", out)
        self.assertNotIn("<bad>", out)
        self.assertNotIn("无规则", out)

    def test_non_dict_returns_empty(self):
        from market import _normalize_tag_definitions

        self.assertEqual(_normalize_tag_definitions(None), {})
        self.assertEqual(_normalize_tag_definitions([{"x": 1}]), {})


class MarketNormalizePackageDisplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from market import _normalize_package  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(f"market module unavailable: {exc}")

    def test_legacy_package_without_display_keeps_empty_dict(self):
        # 旧包不带 display 字段，规整化后应得到空 dict，不抛错。
        from market import _normalize_package

        pkg = _normalize_package({"id": "legacy", "kind": "playlist"})
        self.assertEqual(pkg["display"], {})

    def test_display_badge_survives_normalization(self):
        from market import _normalize_package

        pkg = _normalize_package({
            "id": "shandong",
            "kind": "playlist",
            "display": {"badge": {"text": "鲁", "tone": "orange"}},
        })
        self.assertEqual(pkg["display"], {"badge": {"text": "鲁", "tone": "orange"}})

    def test_display_with_invalid_badge_filtered(self):
        from market import _normalize_package

        pkg = _normalize_package({
            "id": "x",
            "kind": "playlist",
            "display": {"badge": {"text": "<script>", "tone": "rainbow"}},
        })
        # 全部非法 → display.badge 被丢弃 → display 整体应为 {}（不渲染徽章配置）。
        self.assertEqual(pkg["display"], {})


class MarketTagDefinitionsModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from market import _normalize_tag_definitions_mode  # noqa: F401
        except Exception as exc:
            raise unittest.SkipTest(f"market module unavailable: {exc}")

    def test_default_when_missing(self):
        from market import _normalize_tag_definitions_mode

        self.assertEqual(_normalize_tag_definitions_mode(None), "inherit")
        self.assertEqual(_normalize_tag_definitions_mode(""), "inherit")

    def test_inherit_passes_through(self):
        from market import _normalize_tag_definitions_mode

        self.assertEqual(_normalize_tag_definitions_mode("inherit"), "inherit")

    def test_replace_passes_through(self):
        from market import _normalize_tag_definitions_mode

        self.assertEqual(_normalize_tag_definitions_mode("replace"), "replace")

    def test_invalid_falls_back_to_inherit(self):
        from market import _normalize_tag_definitions_mode

        # 未知字符串、布尔值、整数、列表都必须回退到 inherit，不抛错。
        for bad in ("override", "INHERIT", "Replace", True, 0, ["replace"], {"mode": "replace"}):
            self.assertEqual(_normalize_tag_definitions_mode(bad), "inherit")

    def test_legacy_market_without_mode_treated_as_inherit(self):
        # _normalize_tag_definitions_mode 只接受单值，但旧 market.json 整体上
        # 不会带这个字段。模拟从 dict 读取：market.get(...) 返回 None → 回退 inherit。
        from market import _normalize_tag_definitions_mode

        legacy_market = {"schema_version": 1, "packages": []}
        self.assertEqual(
            _normalize_tag_definitions_mode(legacy_market.get("tag_definitions_mode")),
            "inherit",
        )

    def test_mode_does_not_affect_package_supported_or_importable(self):
        # 该字段属于纯展示元数据，不影响 supported_in_v1 / importable / unsupported_reason。
        from market import _normalize_package

        pkg = _normalize_package({"id": "x", "kind": "playlist"})
        baseline_supported = pkg["supported_in_v1"]
        baseline_importable = pkg["importable"]

        # 该字段是 market 根级，不通过 _normalize_package；这里只断言包字段不被任何别的上下文动到。
        self.assertTrue(baseline_supported)
        self.assertTrue(baseline_importable)


if __name__ == "__main__":
    unittest.main()
