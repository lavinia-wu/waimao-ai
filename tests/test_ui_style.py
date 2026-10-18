from __future__ import annotations

import unittest
from pathlib import Path

from config.settings import settings
from modules.ui_style import (
    SEMANTIC_ERROR,
    SEMANTIC_SUCCESS,
    SEMANTIC_WARNING,
    STATUS_TONE_COLORS,
    STOCK_STATUS_COLORS,
    THEME_BACKGROUND,
    THEME_BORDER,
    THEME_PRIMARY,
    THEME_SECONDARY_BACKGROUND,
    THEME_TEXT,
    THEME_TEXT_MUTED,
    _BASE_CSS,
    risk_badge_color,
    risk_label_text,
    status_badge_color,
    stock_display_value,
    stock_status_color,
)

ROOT = Path(settings.base_dir)


class UiStyleThemeTests(unittest.TestCase):
    def test_theme_constants_are_locked(self) -> None:
        self.assertEqual('#2447A8', THEME_PRIMARY)
        self.assertEqual('#F6F8FC', THEME_BACKGROUND)
        self.assertEqual('#FFFFFF', THEME_SECONDARY_BACKGROUND)
        self.assertEqual('#182230', THEME_TEXT)
        self.assertEqual('#667085', THEME_TEXT_MUTED)
        self.assertEqual('#E4E7EC', THEME_BORDER)

    def test_semantic_colors_are_declared(self) -> None:
        self.assertEqual('#15803D', SEMANTIC_SUCCESS)
        self.assertEqual('#B45309', SEMANTIC_WARNING)
        self.assertEqual('#B42318', SEMANTIC_ERROR)

    def test_config_toml_matches_module_constants(self) -> None:
        content = (ROOT / '.streamlit' / 'config.toml').read_text(encoding='utf-8')
        self.assertIn(f'primaryColor = "{THEME_PRIMARY}"', content)
        self.assertIn(f'backgroundColor = "{THEME_BACKGROUND}"', content)
        self.assertIn(f'secondaryBackgroundColor = "{THEME_SECONDARY_BACKGROUND}"', content)
        self.assertIn(f'textColor = "{THEME_TEXT}"', content)

    def test_config_toml_keeps_base_theme(self) -> None:
        """改色板时不得把 base 等既有配置覆盖掉。"""
        content = (ROOT / '.streamlit' / 'config.toml').read_text(encoding='utf-8')
        self.assertIn('base = "light"', content)

    def test_base_css_avoids_generated_class_names(self) -> None:
        """CSS 只能依赖稳定 data-testid，不能依赖自动生成的 .css- 类名。"""
        self.assertIn('data-testid', _BASE_CSS)
        self.assertNotIn('.css-', _BASE_CSS)

    def test_base_css_is_centralized(self) -> None:
        """全站只允许 inject_base_css() 一处写 CSS。"""
        offenders = []
        for path in ROOT.rglob('*.py'):
            # 测试文件自身含有 '<style' 字面量用于断言，不算分散样式
            if '__pycache__' in path.parts or path.name == 'ui_style.py':
                continue
            if path.name.startswith('test_'):
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            if '<style' in text:
                offenders.append(path.name)
        self.assertEqual([], offenders, f'存在分散的样式定义：{offenders}')

    def test_no_html_widgets_outside_style_module(self) -> None:
        """可操作组件不得用纯 HTML 实现；HTML 只允许出现在 ui_style 的样式里。"""
        offenders = []
        for path in ROOT.rglob('*.py'):
            if '__pycache__' in path.parts or path.name == 'ui_style.py':
                continue
            if path.name.startswith('test_'):
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            if '<a href' in text or '<div id' in text:
                offenders.append(path.name)
        self.assertEqual([], offenders, f'存在纯 HTML 可操作组件：{offenders}')

    def test_no_h4_headings_in_markdown(self) -> None:
        """分区内标题禁止 H4，页面只使用 title / subheader / 加粗文本。"""
        offenders = []
        patterns = ('markdown(f"####', "markdown(f'####", 'markdown("####', "markdown('####")
        for path in ROOT.rglob('*.py'):
            if '__pycache__' in path.parts or path.name.startswith('test_'):
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            if any(pattern in text for pattern in patterns):
                offenders.append(path.name)
        self.assertEqual([], offenders, f'存在 H4 级标题：{offenders}')

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


class StatusBadgeTests(unittest.TestCase):
    def test_tones_map_to_badge_colors(self) -> None:
        self.assertEqual('green', status_badge_color('success'))
        self.assertEqual('orange', status_badge_color('warning'))
        self.assertEqual('red', status_badge_color('error'))
        self.assertEqual('blue', status_badge_color('info'))
        self.assertEqual('gray', status_badge_color('neutral'))

    def test_unknown_tone_falls_back_to_gray(self) -> None:
        self.assertEqual('gray', status_badge_color('unknown'))
        self.assertEqual('gray', status_badge_color(None))
        self.assertEqual('gray', status_badge_color(''))

    def test_every_declared_tone_is_valid(self) -> None:
        allowed = {'red', 'orange', 'yellow', 'blue', 'green', 'violet', 'gray', 'grey', 'primary'}
        self.assertEqual(set(STATUS_TONE_COLORS.values()) - allowed, set())


class StockDisplayTests(unittest.TestCase):
    def test_unmaintained_is_never_rendered_as_zero(self) -> None:
        self.assertEqual('未维护', stock_display_value(None))
        self.assertEqual('未维护', stock_display_value(''))
        self.assertEqual('0', stock_display_value(0))
        self.assertEqual('0', stock_display_value('0'))

    def test_integral_numbers_drop_decimals(self) -> None:
        self.assertEqual('500', stock_display_value(500.0))
        self.assertEqual('12.5', stock_display_value(12.5))

    def test_status_colors_cover_every_status(self) -> None:
        self.assertEqual(
            {'缺货', '偏低', '充足', '正常', '未维护'}, set(STOCK_STATUS_COLORS)
        )

    def test_unknown_status_is_neutral(self) -> None:
        self.assertEqual('gray', stock_status_color('不存在的状态'))
        self.assertEqual('gray', stock_status_color(None))

    def test_null_and_zero_are_distinguishable(self) -> None:
        """库存 NULL 与 0 必须给出不同的展示与不同的颜色。"""
        self.assertNotEqual(stock_display_value(None), stock_display_value(0))
        self.assertNotEqual(stock_status_color('未维护'), stock_status_color('缺货'))


if __name__ == '__main__':
    unittest.main()
