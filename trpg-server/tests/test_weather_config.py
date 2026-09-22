# -*- coding: utf-8 -*-
"""天气结构化影响与热读回归测试。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.核心 import weather_config, weather_system


class WeatherConfigTest(unittest.TestCase):
    def test_structured_effect_and_derived_text(self):
        rain = weather_system.effect_for("雨")
        self.assertEqual(rain["判定修正"]["轻功"], -5)
        self.assertEqual(rain["效果倍率"]["火系"], 0.5)
        self.assertIn("视野受限", rain["环境标签"])
        self.assertEqual(
            weather_system.effect_text(rain),
            "轻功判定 +5 难度；火系效果减半；视野受限",
        )

        weather = {"状况": "台风", "影响": "旧文本"}
        self.assertTrue(weather_system.sync_effect(weather))
        self.assertIn("出行", weather["影响"]["禁止行动"])
        self.assertIn("航行", weather["影响"]["禁止行动"])
        self.assertIn("影响文本", weather)
        self.assertFalse(weather_system.sync_effect(weather))

    def test_same_day_legacy_text_is_migrated(self):
        base = {
            "时间": {"日期": "1220-01-17"},
            "天气": {"日期": "1220-01-17", "状况": "雨", "影响": "旧文本"},
        }
        with patch.object(weather_system.state, "load", return_value=base), \
             patch.object(weather_system.state, "save") as save:
            weather_system.ensure_today()
        self.assertEqual(base["天气"]["影响"]["判定修正"]["轻功"], -5)
        self.assertIn("轻功判定 +5 难度", base["天气"]["影响文本"])
        save.assert_called_once_with("基本信息", base)

    def test_hot_reload_and_invalid_config_are_explicit(self):
        original_path = weather_config.CONFIG_PATH
        original_cache = weather_config._cache
        cfg = weather_config.load()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "天气.json"
            try:
                weather_config.CONFIG_PATH = path
                weather_config._cache = None
                changed = json.loads(json.dumps(cfg, ensure_ascii=False))
                changed["影响"]["雨"]["判定修正"]["轻功"] = -8
                path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
                self.assertEqual(weather_system.effect_for("雨")["判定修正"]["轻功"], -8)

                changed["极端天气权重"]["北部城市"]["暴雪"] = 39
                path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
                weather_config._cache = None
                with self.assertRaisesRegex(RuntimeError, "天气配置无效"):
                    weather_config.load()
            finally:
                weather_config.CONFIG_PATH = original_path
                weather_config._cache = original_cache
                weather_config.load()


if __name__ == "__main__":
    unittest.main()
