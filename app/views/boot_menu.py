"""安全启动菜单 — 启动异常或用户主动触发时显示的启动选项对话框。

支持四种启动模式：
    normal  — 正常启动（默认）
    safe    — 安全启动：不加载插件、不触发自动化
    hidden  — 隐藏启动：直接最小化到托盘，不显示主窗口
    custom  — 自定义参数：用户填写额外参数传给程序

还包含 AlreadyRunningDialog：重复启动时显示的提示窗口。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QWidget,
    QButtonGroup, QLabel,
)
from qfluentwidgets import (
    SubtitleLabel, BodyLabel, CaptionLabel,
    RadioButton, LineEdit, CardWidget,
    StrongBodyLabel, isDarkTheme, qconfig,
    PrimaryPushButton, PushButton, FluentIcon as FIF,
)

from app.services.i18n_service import I18nService


# ─────────────────────────── 启动模式常量 ───────────────────────────────── #

class BootMode:
    NORMAL = "normal"
    SAFE   = "safe"
    HIDDEN = "hidden"
    CUSTOM = "custom"


def _t(key: str, default: str = "", **kw) -> str:
    return I18nService.instance().t(key, default=default, **kw)


# ─────────────────────── 通用对话框背景样式 ──────────────────────────────── #

def _apply_dialog_style(dialog: QDialog) -> None:
    """根据当前主题设置对话框背景色。"""
    bg = "#202020" if isDarkTheme() else "#f5f5f5"
    dialog.setStyleSheet(f"QDialog{{background:{bg};border-radius:12px;}}")


# ─────────────────────────── 单选项卡片 ──────────────────────────────────── #

class _OptionCard(CardWidget):
    """可选中的启动模式卡片（单选按钮 + 标题 + 描述）。"""

    def __init__(self, radio: RadioButton, title: str, desc: str,
                 extra_widget: QWidget | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("optionCard")
        self._radio = radio

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(radio)
        title_lbl = StrongBodyLabel(title)
        top_row.addWidget(title_lbl, 1)
        layout.addLayout(top_row)

        desc_lbl = CaptionLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setIndent(26)
        layout.addWidget(desc_lbl)

        if extra_widget is not None:
            extra_widget.setContentsMargins(26, 4, 0, 0)
            layout.addWidget(extra_widget)

    def mousePressEvent(self, event):
        self._radio.setChecked(True)
        super().mousePressEvent(event)

    def _apply_style(self):
        dark = isDarkTheme()
        if self._radio.isChecked():
            bg     = "rgba(40,80,160,80)"  if dark else "rgba(200,220,255,120)"
            border = "rgba(80,130,220,80)" if dark else "rgba(60,120,220,60)"
        else:
            bg     = "transparent"
            border = "rgba(80,80,80,30)"   if dark else "rgba(180,180,180,50)"
        self.setStyleSheet(
            "#optionCard{background:%s;border:1px solid %s;border-radius:8px;}" % (bg, border)
        )

    def update_style(self):
        self._apply_style()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_style()


# ────────────────────────── 启动菜单对话框 ──────────────────────────────── #

class StartupMenuDialog(QDialog):
    """启动选项对话框（无需父窗口，可在主窗口创建之前显示）。

    Parameters
    ----------
    reason : str
        触发本对话框的原因描述（空字符串表示用户主动触发）。
    crash_count : int
        检测到的短时间内的启动异常次数（0 表示无异常）。
    """

    def __init__(self, reason: str = "", crash_count: int = 0, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint,
        )
        self.setWindowTitle(_t("boot.menu.title", default="启动选项"))
        self.setFixedWidth(520)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._mode     = BootMode.NORMAL
        self._accepted = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(10)

        # ── 标题 ──────────────────────────────────────────────────────── #
        root.addWidget(SubtitleLabel(_t("boot.menu.title", default="启动选项")))

        # ── 原因横幅 ──────────────────────────────────────────────────── #
        if crash_count > 0:
            icon_ch     = "⚠️"
            reason_text = _t(
                "boot.menu.crash_reason",
                default=f"检测到应用在短时间内异常退出了 {crash_count} 次，建议选择安全启动进行排查。",
                count=crash_count,
            )
        elif reason:
            icon_ch     = "ℹ️"
            reason_text = reason
        else:
            icon_ch     = "🚀"
            reason_text = _t("boot.menu.manual_reason", default="您主动选择了在启动时显示此菜单。")

        reason_row = QHBoxLayout()
        reason_row.setSpacing(8)
        _icon_lbl = QLabel(icon_ch)
        _icon_lbl.setStyleSheet("font-size:16px;")
        _reason_lbl = BodyLabel(reason_text)
        _reason_lbl.setWordWrap(True)
        reason_row.addWidget(_icon_lbl)
        reason_row.addWidget(_reason_lbl, 1)
        root.addLayout(reason_row)

        # ── 单选卡片 ──────────────────────────────────────────────────── #
        self._btn_group    = QButtonGroup(self)
        self._radio_normal = RadioButton()
        self._radio_safe   = RadioButton()
        self._radio_hidden = RadioButton()
        self._radio_custom = RadioButton()
        for r in (self._radio_normal, self._radio_safe,
                  self._radio_hidden, self._radio_custom):
            self._btn_group.addButton(r)

        self._custom_edit = LineEdit()
        self._custom_edit.setPlaceholderText(
            _t("boot.menu.custom_ph", default="如 --debug --locale en-US"))
        self._custom_edit.setEnabled(False)

        cards_def = [
            (self._radio_normal, BootMode.NORMAL,
             _t("boot.mode.normal",        default="正常启动"),
             _t("boot.mode.normal.desc",   default="加载所有插件并启用自动化，与往常相同。"),
             None),
            (self._radio_safe,   BootMode.SAFE,
             _t("boot.mode.safe",          default="安全启动"),
             _t("boot.mode.safe.desc",     default="跳过所有插件加载，不触发任何自动化规则。适合排查崩溃问题。"),
             None),
            (self._radio_hidden, BootMode.HIDDEN,
             _t("boot.mode.hidden",        default="隐藏启动"),
             _t("boot.mode.hidden.desc",   default="直接最小化到系统托盘，不显示主窗口。"),
             None),
            (self._radio_custom, BootMode.CUSTOM,
             _t("boot.mode.custom",        default="自定义参数启动"),
             _t("boot.mode.custom.desc",   default="输入额外启动参数传递给程序。"),
             self._custom_edit),
        ]
        self._option_cards: list[tuple[_OptionCard, str]] = []
        for radio, mode, title, desc, extra in cards_def:
            card = _OptionCard(radio, title, desc, extra)
            root.addWidget(card)
            self._option_cards.append((card, mode))

        self._radio_normal.setChecked(True)
        # 用每个按钮的 toggled 信号，避免 QButtonGroup.checkedButton()
        # 跨父控件时 Python 对象包装不一致导致 is 比较失效
        for _r in (self._radio_normal, self._radio_safe,
                   self._radio_hidden, self._radio_custom):
            _r.toggled.connect(lambda *_: self._on_radio_changed())
        self._on_radio_changed()

        # ── 底部按钮 ──────────────────────────────────────────────────── #
        root.addSpacing(4)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._start_btn = PrimaryPushButton(_t("boot.menu.start", default="启动"))
        self._exit_btn  = PushButton(_t("boot.menu.exit",         default="退出程序"))
        self._start_btn.setFixedHeight(36)
        self._exit_btn.setFixedHeight(36)
        self._start_btn.setMinimumWidth(120)
        self._exit_btn.setMinimumWidth(100)
        btn_row.addStretch()
        btn_row.addWidget(self._exit_btn)
        btn_row.addWidget(self._start_btn)
        root.addLayout(btn_row)

        self._start_btn.clicked.connect(self._on_accept)
        self._exit_btn.clicked.connect(self.reject)

        # ── 主题适配 ─────────────────────────────────────────────────── #
        _apply_dialog_style(self)
        qconfig.themeChangedFinished.connect(self._on_theme_changed)

    # ── 信号处理 ─────────────────────────────────────────────────────── #

    def _on_radio_changed(self) -> None:
        if self._radio_safe.isChecked():
            self._mode = BootMode.SAFE
        elif self._radio_hidden.isChecked():
            self._mode = BootMode.HIDDEN
        elif self._radio_custom.isChecked():
            self._mode = BootMode.CUSTOM
        else:
            self._mode = BootMode.NORMAL
        self._custom_edit.setEnabled(self._mode == BootMode.CUSTOM)
        for card, _ in self._option_cards:
            card.update_style()

    def _on_theme_changed(self) -> None:
        _apply_dialog_style(self)
        for card, _ in self._option_cards:
            card.update_style()

    def _on_accept(self) -> None:
        self._accepted = True
        self.accept()

    # ── 结果属性 ─────────────────────────────────────────────────────── #

    @property
    def selected_mode(self) -> str:
        return self._mode

    @property
    def extra_args(self) -> str:
        return self._custom_edit.text().strip() if self._mode == BootMode.CUSTOM else ""

    # ── 类方法快捷入口 ───────────────────────────────────────────────── #

    @classmethod
    def ask(
        cls,
        reason: str = "",
        crash_count: int = 0,
        parent=None,
    ) -> tuple[str, str] | None:
        """显示启动菜单对话框。

        返回 ``(mode, extra_args)`` 若用户点击「启动」；
        返回 ``None`` 若点击「退出程序」（调用方应 sys.exit）。
        """
        dlg = cls(reason=reason, crash_count=crash_count, parent=parent)
        _center_on_screen(dlg)
        code = dlg.exec()
        if code == QDialog.DialogCode.Accepted and dlg._accepted:
            return dlg.selected_mode, dlg.extra_args
        return None


# ────────────────────────── 重复启动提示对话框 ───────────────────────────── #

class AlreadyRunningDialog(QDialog):
    """当程序已在运行时，第二个实例显示的提示窗口。

    按钮：
        关闭  — 仅关闭此对话框，正在运行的实例不受影响。
        重启  — 向正在运行的实例发送退出指令，之后本进程重新启动。
    """

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowTitleHint,
        )
        self.setWindowTitle(_t("app.name", default="小树时钟"))
        self.setFixedWidth(420)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.restart_requested = False

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(14)

        # ── 图标 + 标题 ───────────────────────────────────────────────── #
        head_row = QHBoxLayout()
        head_row.setSpacing(12)
        icon_lbl = QLabel("🔔")
        icon_lbl.setStyleSheet("font-size:28px;")
        icon_lbl.setFixedWidth(42)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_lbl = SubtitleLabel(_t("boot.already_running.title", default="程序已在运行"))
        desc_lbl  = BodyLabel(
            _t("boot.already_running.desc",
               default="小树时钟已经在运行中。\n您可以在系统托盘找到它，或选择下方操作。")
        )
        desc_lbl.setWordWrap(True)
        title_col.addWidget(title_lbl)
        title_col.addWidget(desc_lbl)

        head_row.addWidget(icon_lbl)
        head_row.addLayout(title_col, 1)
        root.addLayout(head_row)

        # ── 操作说明卡片 ─────────────────────────────────────────────── #
        hint_card = CardWidget()
        hint_card.setObjectName("hintCard")
        hint_layout = QVBoxLayout(hint_card)
        hint_layout.setContentsMargins(14, 10, 14, 10)
        hint_layout.setSpacing(4)
        hint_layout.addWidget(CaptionLabel(
            _t("boot.already_running.close_hint",
               default="关闭  —  仅关闭此提示，正在运行的程序不受影响。")
        ))
        hint_layout.addWidget(CaptionLabel(
            _t("boot.already_running.restart_hint",
               default="重启  —  退出正在运行的程序，然后重新启动。")
        ))
        root.addWidget(hint_card)

        # ── 按钮 ─────────────────────────────────────────────────────── #
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._close_btn   = PushButton(
            FIF.CLOSE,
            _t("boot.already_running.btn_close",   default="关闭"),
        )
        self._restart_btn = PrimaryPushButton(
            FIF.SYNC,
            _t("boot.already_running.btn_restart", default="重启"),
        )
        self._close_btn.setFixedHeight(36)
        self._restart_btn.setFixedHeight(36)
        self._close_btn.setMinimumWidth(100)
        self._restart_btn.setMinimumWidth(100)
        btn_row.addStretch()
        btn_row.addWidget(self._close_btn)
        btn_row.addWidget(self._restart_btn)
        root.addLayout(btn_row)

        self._close_btn.clicked.connect(self.reject)
        self._restart_btn.clicked.connect(self._on_restart)

        _apply_dialog_style(self)
        qconfig.themeChangedFinished.connect(lambda: _apply_dialog_style(self))

    def _on_restart(self) -> None:
        self.restart_requested = True
        self.accept()

    @classmethod
    def show_and_wait(cls, parent=None) -> bool:
        """显示对话框并等待用户操作。返回 True 表示用户选择了「重启」。"""
        dlg = cls(parent=parent)
        _center_on_screen(dlg)
        dlg.exec()
        return dlg.restart_requested


# ────────────────────────── 工具函数 ─────────────────────────────────────── #

def _center_on_screen(dialog: QDialog) -> None:
    """将对话框居中显示在主屏幕上。"""
    screen = QApplication.primaryScreen()
    if screen is None:
        return
    geo = screen.availableGeometry()
    # 需要先 adjustSize，确保 dialog.width()/height() 已更新
    dialog.adjustSize()
    dialog.move(
        geo.center().x() - dialog.width()  // 2,
        geo.center().y() - dialog.height() // 2,
    )
