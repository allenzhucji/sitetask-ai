"""主窗口背景：固定 alpha 磨砂圆角绘制，不崩溃、圆角外透明、存在半透明磨砂像素。"""

from app.services.settings_service import SettingsService
from app.ui.main_widget import MainWidget


def _make_widget(qtbot) -> MainWidget:
    widget = MainWidget(settings_service=SettingsService())
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def test_background_is_frosted_rounded(qtbot):
    """圆角外（四角）透明；全图中存在磨砂半透明像素（主背景 alpha≈205，
    但会被不透明子控件覆盖，故扫描而非取固定坐标）。"""
    widget = _make_widget(qtbot)
    img = widget.grab().toImage()
    w, h = img.width(), img.height()
    corners = [(2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3)]
    # offscreen 平台（test.bat 设置 QT_QPA_PLATFORM=offscreen）的 grab
    # 会在圆角外残留 ≤2 的合成噪声，故用阈值而非 == 0
    assert all(img.pixelColor(x, y).alpha() < 32 for x, y in corners)

    # 磨砂半透明：步进采样全图，至少一个像素 alpha 严格介于 0 与 255
    semi = False
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            alpha = img.pixelColor(x, y).alpha()
            if 0 < alpha < 255:
                semi = True
                break
        if semi:
            break
    assert semi
    widget.close()


def test_paint_event_never_raises(qtbot):
    """repaint 不崩溃。"""
    widget = _make_widget(qtbot)
    widget.repaint()
    widget.close()
