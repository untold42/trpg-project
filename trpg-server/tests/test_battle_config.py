# -*- coding: utf-8 -*-
"""战斗数值配置迁移与热读回归测试。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.核心 import battle_config
from tools.战斗 import battle
from tools.战斗 import battle_ai
from tools.战斗 import battle_tactics


class BattleConfigTest(unittest.TestCase):
    def test_config_drives_core_formulas(self):
        cfg = battle_config.load()
        hit = cfg["命中"]
        self.assertEqual(battle._hit_tier(hit["未命中线"] - 1), (None, 0.0))
        self.assertEqual(battle._hit_tier(hit["未命中线"]), ("命中", hit["擦中伤害倍率"]))
        self.assertEqual(battle._hit_tier(hit["标准命中线"]), ("命中", hit["普通伤害倍率"]))
        self.assertEqual(battle._hit_tier(hit["会心线"]), ("会心", hit["会心伤害倍率"]))

        coef = cfg["梯度系数"]["T2"]
        hp_rule = cfg["NPC推导"]["生命"]
        npc = battle.npc_combatant("测试", "敌方", "T2")
        self.assertEqual(npc["生命"], round(hp_rule["系数"] * coef + hp_rule["基础"]))
        self.assertEqual(battle_ai.score_of("精妙"), cfg["思路评价"]["精妙"])

    def test_hot_reload_and_invalid_config_are_explicit(self):
        original_path = battle_config.CONFIG_PATH
        original_cache = battle_config._cache
        cfg = battle_config.load()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "战斗数值.json"
            try:
                battle_config.CONFIG_PATH = path
                battle_config._cache = None

                changed = json.loads(json.dumps(cfg, ensure_ascii=False))
                changed["命中"]["未命中线"] += 1
                changed["战术AI"]["内力代价权重"] = 0.25
                changed["思路评价"]["精妙"] += 1
                path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")

                battle.refresh_config()
                battle_tactics._refresh_ai_config()
                self.assertEqual(battle._hit_tier(changed["命中"]["未命中线"] - 1), (None, 0.0))
                self.assertEqual(battle_tactics.W_COST, 0.25)
                self.assertEqual(battle_ai.score_of("精妙"), changed["思路评价"]["精妙"])

                del changed["命中"]["会心线"]
                path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
                battle_config._cache = None
                with self.assertRaisesRegex(RuntimeError, "战斗数值配置无效"):
                    battle.refresh_config()
            finally:
                battle_config.CONFIG_PATH = original_path
                battle_config._cache = original_cache
                battle.refresh_config()
                battle_tactics._refresh_ai_config()
                battle_ai.score_of("平平")


if __name__ == "__main__":
    unittest.main()
