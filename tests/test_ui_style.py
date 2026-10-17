from __future__ import annotations

import unittest
from pathlib import Path

from config.settings import settings
from modules.ui_style import (
    THEME_BACKGROUND,
    THEME_PRIMARY,
    risk_badge_color,
    risk_label_text,
)

ROOT = Path(settings.base_dir)


class UiStyleThemeTests(unittest.TestCase):
    def test_theme_constants_are_locked(self) -> None:
        self.assertEqual('#1F4E79', THEME_PRIMARY)
        self.assertEqual('#F5F7FA', THEME_BACKGROUND)

    def test_config_toml_matches_module_constants(self) -> None:
        content = (ROOT / '.streamlit' / 'config.toml').read_text(encoding='utf-8')
        self.assertIn(f'primaryColor = "{THEME_PRIMARY}"', content)
        self.assertIn(f'backgroundColor = "{THEME_BACKGROUND}"', content)

    def test_no_hardcoded_conflicting_red_remains(self) -> None:
        # 组装字符串以避免本文件自身的字面量命中扫描结果
        legacy_color = '#ff' + '4b4b'
        for path in ROOT.rglob('*.py'):
            if '__pycache__' in path.parts:
                continue
            self.assertNotIn(
                legacy_color,
                path.read_text(encoding='utf-8', errors='ignore'),
                f'{path.name} 仍存在硬编码的旧强调色',
            )


class RiskBadgeTests(unittest.TestCase):
    def test_chinese_and_english_levels_map_to_same_color(self) -> None:
        self.assertEqual('red', risk_badge_color('高'))
        self.assertEqual('red', risk_badge_color('High'))
        self.assertEqual('red', risk_badge_color('critical'))
        self.assertEqual('orange', risk_badge_color('中'))
        self.assertEqual('orange', risk_badge_color('medium'))
        self.assertEqual('blue', risk_badge_color('低'))
        self.assertEqual('blue', risk_badge_color('minor'))

    def test_missing_or_unknown_level_falls_back_to_neutral(self) -> None:
        self.assertEqual('gray', risk_badge_color(None))
        self.assertEqual('gray', risk_badge_color(''))
        self.assertEqual('gray', risk_badge_color('未知级别'))

    def test_label_never_invents_a_level(self) -> None:
        self.assertEqual('待确认', risk_label_text(None))
        self.assertEqual('待确认', risk_label_text('  '))
        self.assertEqual('高', risk_label_text(' 高 '))


if __name__ == '__main__':
    unittest.main()
