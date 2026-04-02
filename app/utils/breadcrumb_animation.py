"""面包屑步骤切换动画工具。"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPropertyAnimation, QPoint
from PySide6.QtWidgets import QStackedWidget, QWidget


def animate_stacked_page_slide(
    *,
    host: QWidget,
    stack: QStackedWidget,
    target_index: int,
    previous_index: int,
    enabled: bool,
    active_animations: list[QParallelAnimationGroup],
    distance: int = 36,
    duration_ms: int = 280,
) -> None:
    """在步骤切换时执行轻量级页面滑入动画。"""
    if not enabled or target_index == previous_index:
        return

    page = stack.widget(target_index)
    if page is None or not host.isVisible():
        return

    base_pos = page.pos()
    offset = distance if target_index > previous_index else -distance
    start_pos = QPoint(base_pos.x() + offset, base_pos.y())
    page.move(start_pos)

    pos_ani = QPropertyAnimation(page, b"pos", host)
    pos_ani.setDuration(duration_ms)
    pos_ani.setStartValue(start_pos)
    pos_ani.setEndValue(base_pos)
    pos_ani.setEasingCurve(QEasingCurve.Type.OutCubic)

    group = QParallelAnimationGroup(host)
    group.addAnimation(pos_ani)
    active_animations.append(group)

    def _cleanup() -> None:
        if group in active_animations:
            active_animations.remove(group)

    group.finished.connect(_cleanup)
    group.start()


def stop_animations(active_animations: list[QParallelAnimationGroup]) -> None:
    """停止并清空动画组。"""
    for animation in list(active_animations):
        animation.stop()
    active_animations.clear()
