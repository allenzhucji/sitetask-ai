from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon

from app.ui.title_bar import TitleBar


def test_title_bar_actions_share_flat_icon_button_geometry(qtbot):
    title_bar = TitleBar()
    qtbot.addWidget(title_bar)
    buttons = (
        title_bar.pin_button,
        title_bar.all_tasks_button,
        title_bar.settings_button,
        title_bar.minimize_button,
        title_bar.close_button,
    )

    assert {button.size() for button in buttons} == {QSize(18, 18)}
    assert {button.iconSize() for button in buttons} == {QSize(18, 18)}
    assert all(button.isFlat() for button in buttons)
    assert all(button.text() == "" for button in buttons)
    assert all(not button.icon().isNull() for button in buttons)
    assert all(button.focusPolicy() is Qt.FocusPolicy.NoFocus for button in buttons)
    assert all(
        button.cursor().shape() is Qt.CursorShape.PointingHandCursor
        for button in buttons
    )
    assert len({button.icon().cacheKey() for button in buttons}) == len(buttons)


def test_pin_icon_has_distinct_checked_state_and_accessible_label(qtbot):
    title_bar = TitleBar()
    qtbot.addWidget(title_bar)

    off = title_bar.pin_button.icon().pixmap(
        QSize(18, 18), QIcon.Mode.Normal, QIcon.State.Off
    )
    on = title_bar.pin_button.icon().pixmap(
        QSize(18, 18), QIcon.Mode.Normal, QIcon.State.On
    )
    assert not off.isNull()
    assert not on.isNull()
    assert off.toImage() != on.toImage()

    title_bar.set_pinned(True)
    assert title_bar.pin_button.isChecked()
    assert title_bar.pin_button.accessibleName() == "Pinned"
    assert title_bar.pin_button.toolTip() == "Unpin window"
