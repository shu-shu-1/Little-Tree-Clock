from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QProgressBar, QApplication
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt


_STEP_STYLE_DONE = "color:rgba(255,255,255,0.40);"
_STEP_STYLE_ACTIVE = "color:#4cc2ff;font-weight:500;"
_STEP_STYLE_PENDING = "color:rgba(255,255,255,0.18);"


class StartupSplash(QWidget):
    _STEPS = [
        ("init", "初始化运行环境"),
        ("settings", "加载用户配置"),
        ("services", "初始化基础服务"),
        ("views", "构建界面视图"),
        ("window", "配置主窗口"),
        ("plugins", "扫描并加载插件"),
    ]

    def __init__(self, show_detail: bool = False):
        super().__init__()
        self._show_detail = show_detail
        self._current_step = -1
        self._step_labels: list[QLabel] = []

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)

        h = 180 if not show_detail else 310
        self.setFixedSize(300, h)

        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.x() + (geo.width() - self.width()) // 2,
                geo.y() + (geo.height() - self.height()) // 2,
            )

        self._build_ui()

    def _build_ui(self):
        from app.constants import APP_NAME, ICON_PATH
        from pathlib import Path

        card = QWidget(self)
        card.setObjectName("splashCard")
        card.setGeometry(0, 0, self.width(), self.height())
        card.setStyleSheet(
            "#splashCard{background:rgba(44,44,48,0.97);border-radius:14px;}"
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 16)
        layout.setSpacing(4)

        icon_path = Path(ICON_PATH)
        if icon_path.is_file():
            px = QPixmap(str(icon_path))
            if not px.isNull():
                icon_lbl = QLabel()
                icon_lbl.setPixmap(
                    px.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                icon_lbl.setAlignment(Qt.AlignCenter)
                icon_lbl.setStyleSheet("background:transparent;")
                layout.addWidget(icon_lbl)

        name_lbl = QLabel(APP_NAME)
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet(
            "font-size:17px;font-weight:600;color:#fff;background:transparent;border:none;padding-top:2px;"
        )
        layout.addWidget(name_lbl)

        if self._show_detail:
            layout.addSpacing(6)
            for _key, text in self._STEPS:
                lbl = QLabel(text)
                lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                lbl.setStyleSheet(
                    f"font-size:11px;background:transparent;border:none;padding:1px 0;{_STEP_STYLE_PENDING}"
                )
                lbl.setContentsMargins(8, 0, 0, 0)
                layout.addWidget(lbl)
                self._step_labels.append(lbl)
            layout.addSpacing(2)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(3)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(
            "QProgressBar{background:rgba(255,255,255,0.07);border:none;border-radius:1px;}"
            "QProgressBar::chunk{background:#4cc2ff;border-radius:1px;}"
        )
        if not self._show_detail:
            self._progress.setStyleSheet(
                self._progress.styleSheet() + "margin-top:8px;"
            )
        layout.addWidget(self._progress)

    def set_step(self, step_key: str) -> None:
        idx = next(
            (i for i, (k, _) in enumerate(self._STEPS) if k == step_key), -1
        )
        if idx < 0:
            return
        self._current_step = idx
        if self._show_detail:
            for i, lbl in enumerate(self._step_labels):
                if i < idx:
                    lbl.setStyleSheet(
                        f"font-size:11px;background:transparent;border:none;padding:1px 0;{_STEP_STYLE_DONE}"
                    )
                elif i == idx:
                    lbl.setStyleSheet(
                        f"font-size:11px;background:transparent;border:none;padding:1px 0;{_STEP_STYLE_ACTIVE}"
                    )
                else:
                    lbl.setStyleSheet(
                        f"font-size:11px;background:transparent;border:none;padding:1px 0;{_STEP_STYLE_PENDING}"
                    )

        total = len(self._STEPS)
        self._progress.setRange(0, total)
        self._progress.setValue(idx + 1)
        QApplication.processEvents()

    def present(self):
        self.show()
        self.raise_()
        QApplication.processEvents()

    def dismiss(self):
        self.close()
