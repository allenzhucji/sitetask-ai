from __future__ import annotations


def pytest_collection_modifyitems(session, config, items):
    """把验证 configure_application_style 的测试排到最前。

    QApplication.setStyleSheet() 会全量重抛所有现存控件；qfluentwidgets
    控件（含其隐藏的 Popup 子窗口）在测试间残留时重抛可触发原生
    access violation。生产环境样式表在控件构造前设置、顺序相反故无此
    问题；测试环境只能让这些测试先于任何构造 qfluentwidgets 控件的
    测试执行（应用启动路径本来就该如此验证——无控件时设置全局样式）。
    """
    items.sort(
        key=lambda item: 0
        if "application_icon" in item.nodeid or "application_style" in item.nodeid
        else 1
    )
