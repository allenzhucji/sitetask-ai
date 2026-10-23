"""Windows 10/11 玻璃拟态（Acrylic）背景。

通过 ``SetWindowCompositionAttribute`` 请求与 Windows 系统菜单一致的原生
Acrylic 模糊：优先 Acrylic（带色调，需要 Win10 1803+），失败时降级为简单
模糊（BlurBehind），再失败则返回 False，由调用方回退到不透明背景。

所有路径均有防御：非 Windows 平台、无效句柄、API 不可用时静默返回
False，绝不让界面代码崩溃或阻塞。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

_ACCENT_ENABLE_BLURBEHIND = 3
_ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
_WCA_ACCENT_POLICY = 19

_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_LWA_ALPHA = 0x00000002


class _AccentPolicy(ctypes.Structure):
    _fields_ = [
        ("accent_state", wintypes.DWORD),
        ("accent_flags", wintypes.DWORD),
        ("gradient_color", wintypes.DWORD),
        ("animation_id", wintypes.DWORD),
    ]


class _WindowCompositionAttribData(ctypes.Structure):
    _fields_ = [
        ("attrib", ctypes.c_int),
        ("pv_data", ctypes.c_void_p),
        ("cb_data", ctypes.c_size_t),
    ]


# 延迟绑定：ctypes.WinDLL("user32") 只在 Windows 上可用，因此放在模块级
# 条件导入中；非 Windows 平台 _USER32 为 None，所有函数直接返回 False。
_USER32: ctypes.WinDLL | None = None
if sys.platform == "win32":
    try:
        _USER32 = ctypes.WinDLL("user32")
        _USER32.SetWindowCompositionAttribute.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(_WindowCompositionAttribData),
        ]
        _USER32.SetWindowCompositionAttribute.restype = wintypes.BOOL
        _USER32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        _USER32.GetWindowLongW.restype = wintypes.LONG
        _USER32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        _USER32.SetWindowLongW.restype = wintypes.LONG
        _USER32.SetLayeredWindowAttributes.argtypes = [
            wintypes.HWND,
            wintypes.COLORREF,
            wintypes.BYTE,
            wintypes.DWORD,
        ]
        _USER32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    except OSError:
        _USER32 = None


def _accent_data(policy: _AccentPolicy) -> _WindowCompositionAttribData:
    data = _WindowCompositionAttribData()
    data.attrib = _WCA_ACCENT_POLICY
    data.pv_data = ctypes.cast(ctypes.pointer(policy), ctypes.c_void_p)
    data.cb_data = ctypes.sizeof(_AccentPolicy)
    return data


def _ensure_layered(hwnd: int) -> None:
    """确保窗口带 WS_EX_LAYERED，并保持整体不透明（per-pixel alpha 由 Qt 处理）。"""
    if _USER32 is None:
        return
    style = _USER32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    if style & _WS_EX_LAYERED:
        return
    _USER32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style | _WS_EX_LAYERED)
    _USER32.SetLayeredWindowAttributes(hwnd, 0, 255, _LWA_ALPHA)


def _set_accent(hwnd: int, accent_state: int, gradient_color: int) -> bool:
    if not hwnd or _USER32 is None:
        return False
    policy = _AccentPolicy(accent_state, 2, gradient_color, 0)
    data = _accent_data(policy)
    return bool(
        _USER32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    )


def apply_window_backdrop(
    hwnd: int,
    *,
    tint_rgb: tuple[int, int, int] = (23, 25, 31),
    tint_alpha: int = 90,
) -> bool:
    """为窗口应用玻璃拟态背景。

    Args:
        hwnd: 目标窗口的句柄（``int(widget.winId())``）。
        tint_rgb: 着色 RGB（0-255），与主题底色一致。
        tint_alpha: 着色不透明度（0-255），越小玻璃越透。
        实测 170 时 DWM 着色几乎盖死壁纸，半透明不可见；90 时
        磨砂模糊与透感同时可见（与 Win11 系统菜单浓度接近）。

    Returns:
        True 表示玻璃效果已应用；False 表示不可用或失败，调用方应保持
        不透明背景。
    """
    if not hwnd or _USER32 is None:
        return False
    _ensure_layered(hwnd)
    r, g, b = tint_rgb
    alpha = min(max(tint_alpha, 0), 255)
    gradient_color = (alpha << 24) | (b << 16) | (g << 8) | r
    if _set_accent(hwnd, _ACCENT_ENABLE_ACRYLICBLURBEHIND, gradient_color):
        return True
    # Acrylic 不可用（如旧系统）时降级为简单模糊，仍是半透明观感
    return _set_accent(hwnd, _ACCENT_ENABLE_BLURBEHIND, 0)
