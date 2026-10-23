"""window_backdrop 防御测试：任何环境下都必须安全降级、绝不崩溃。

玻璃效果依赖系统 DWM 能力，因此这里只断言降级行为与类型契约，
不依赖真实渲染结果。
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

import app.services.window_backdrop as backdrop


def test_invalid_handle_returns_false():
    assert backdrop.apply_window_backdrop(0) is False


def test_missing_user32_returns_false(monkeypatch):
    # 模拟非 Windows 平台：user32 不可用（模块级防御路径）
    monkeypatch.setattr(backdrop, "_USER32", None)
    assert backdrop.apply_window_backdrop(12345) is False


def test_blur_fallback_is_also_safe(monkeypatch):
    # 内部降级路径：即使 Acrylic 分支被绕过，Blur 分支同样拒绝空句柄
    monkeypatch.setattr(backdrop, "_USER32", None)
    assert backdrop._set_accent(0, backdrop._ACCENT_ENABLE_BLURBEHIND, 0) is False


def test_real_window_never_raises(qtbot):
    # 真实窗口：结果取决于系统能力，但调用本身必须安全
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    result = backdrop.apply_window_backdrop(int(window.winId()))
    assert isinstance(result, bool)
    window.hide()


def test_out_of_range_alpha_is_clamped(qtbot):
    # 越界 alpha 必须被 clamp 而不是抛异常
    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    result = backdrop.apply_window_backdrop(
        int(window.winId()), tint_rgb=(23, 25, 31), tint_alpha=300
    )
    assert isinstance(result, bool)
