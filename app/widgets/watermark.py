"""测试版水印叠加层

当 IS_BETA 为 True 时，将此控件作为主窗口的子控件使用。
提供两个水印区域：
  1. 对角平铺文字（全窗口半透明）
  2. 右下角信息文字（版本号、测试信息、非最终效果提示）
鼠标事件完全穿透，不影响任何交互。
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtCore import Qt

from app.constants import LONG_VER, BETA_TEST_INFO


class WatermarkOverlay(QWidget):
    """全窗口半透明水印叠加层（鼠标事件穿透）"""

    # ---------- 对角平铺 ----------
    TILE_TEXT       = "测试版 BETA"     # 水印文字内容
    TILE_FONT_PT    = 18                # 水印文字大小（pt）
    TILE_ALPHA      = 30                # 0-255，越小越透明
    TILE_SPACING    = 160               # 相邻水印行/列间距（像素）
    ROTATE_DEG      = -30               # 文字倾斜角度

    # ---------- 右下角文字 ----------
    CORNER_MARGIN   = 16                # 距窗口边缘像素
    CORNER_FONT_PT  = 10                # 文字大小（pt）
    CORNER_ALPHA    = 160               # 文字不透明度

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.raise_()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._draw_tiled(p)
        self._draw_corner(p)

    # ---- 对角平铺 ----

    def _draw_tiled(self, p: QPainter):
        font = QFont("Microsoft YaHei", self.TILE_FONT_PT, QFont.Bold)
        p.setFont(font)
        p.setPen(QColor(120, 120, 120, self.TILE_ALPHA))

        w, h     = self.width(), self.height()
        fm       = p.fontMetrics()
        text_w   = fm.horizontalAdvance(self.TILE_TEXT)
        text_h   = fm.height()
        extra    = int((w * w + h * h) ** 0.5)
        col_step = text_w + self.TILE_SPACING
        row_step = text_h + self.TILE_SPACING
        cols     = int(extra * 2 / col_step) + 4
        rows     = int(extra * 2 / row_step) + 4

        p.save()
        p.translate(w / 2, h / 2)
        p.rotate(self.ROTATE_DEG)
        sx      = -cols // 2 * col_step
        sy      = -rows // 2 * row_step
        for r in range(rows):
            for c in range(cols):
                p.drawText(int(sx + c * col_step), int(sy + r * row_step), self.TILE_TEXT)
        p.restore()

    # ---- 右下角文字 ----

    def _draw_corner(self, p: QPainter):
        lines: list[str] = [LONG_VER]
        if BETA_TEST_INFO:
            lines.append(BETA_TEST_INFO)
        lines.append("非最终效果，仅供测试参考")

        font    = QFont("Microsoft YaHei", self.CORNER_FONT_PT)
        p.setFont(font)
        fm      = p.fontMetrics()
        lh      = fm.height()
        gap     = 3

        w, h    = self.width(), self.height()
        margin  = self.CORNER_MARGIN
        color   = QColor(150, 150, 150, self.CORNER_ALPHA)
        p.setPen(color)

        # 从底部向上逐行绘制
        y = h - margin
        for line in reversed(lines):
            x = w - fm.horizontalAdvance(line) - margin
            p.drawText(x, y, line)
            y -= lh + gap


# ──────────────────────── 安全模式水印 ──────────────────────────────────── #

class SafeModeWatermark(QWidget):
    """安全模式右下角水印（鼠标事件完全穿透）。

    在主窗口右下角以橙色显示"安全模式"提示文字，
    不遮挡任何交互，随窗口缩放自动重绘。
    """

    MARGIN  = 14        # 距窗口边缘像素
    FONT_PT = 11        # 字体大小
    ALPHA   = 200       # 文字不透明度 (0-255)
    COLOR   = (220, 130, 20)   # 橙黄色，与 beta 水印灰色区分

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground,        True)
        self.setAttribute(Qt.WA_TranslucentBackground,     True)
        self.raise_()

    def paintEvent(self, event):
        from PySide6.QtCore import QRect
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        text = "安全模式  SAFE MODE"
        font = QFont("Microsoft YaHei", self.FONT_PT, QFont.Bold)
        p.setFont(font)
        fm = p.fontMetrics()

        tw = fm.horizontalAdvance(text)
        th = fm.height()
        x  = self.width()  - tw - self.MARGIN
        y  = self.height() -      self.MARGIN

        # 半透明背景胶囊
        r, g, b  = self.COLOR
        pad_h, pad_v = 6, 3
        bg_rect = QRect(
            x - pad_h,
            y - th - pad_v + fm.descent(),
            tw + pad_h * 2,
            th + pad_v * 2,
        )
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(r, g, b, 40))
        p.drawRoundedRect(bg_rect, 4, 4)

        # 文字
        p.setPen(QColor(r, g, b, self.ALPHA))
        p.drawText(x, y, text)
