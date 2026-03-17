"""
关于窗口 — 项目信息、依赖、鸣谢、赞助
使用 FluentWidget 作为窗口基类，支持云母背景及自动深浅色切换。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QFrame,
)

from qfluentwidgets import (
    FluentWidget,
    SegmentedWidget,
    SmoothScrollArea, VBoxLayout,
    SubtitleLabel, BodyLabel, StrongBodyLabel, CaptionLabel, TitleLabel,
    CardWidget, FluentIcon as FIF,
    PrimaryPushButton, PushButton, HyperlinkButton,
    ImageLabel, IconWidget,
)

from app.constants import APP_NAME, LONG_VER, ICON_PATH, APP_VERSION
from app.services.i18n_service import I18nService, LANG_EN_US

# 项目 GitHub 仓库地址
GITHUB_URL = "https://github.com/shu-shu-1/Little-Tree-Clock"


def _i18n() -> I18nService:
    return I18nService.instance()


def _tr(zh: str, en: str) -> str:
    return en if _i18n().language == LANG_EN_US else zh


# ─────────────────────────────────────────────────────────────────────────── #
# 依赖项目列表
# ─────────────────────────────────────────────────────────────────────────── #
_DEPS: list[tuple[str, str, str, str, str]] = [
    # (包名, 版本要求, 中文描述, 英文描述, 主页链接)
    ("PySide6", ">=6.8.0", "Qt for Python — Qt 官方 Python 绑定，提供完整 GUI 框架", "Qt for Python official bindings by Qt, providing a complete GUI framework",
     "https://pypi.org/project/PySide6/"),
    ("pyside6-fluent-widgets", ">=1.7.0", "QFluentWidgets — Fluent Design 风格 Qt 组件库", "QFluentWidgets Fluent Design Qt component library",
     "https://qfluentwidgets.com/"),
    ("loguru", ">=0.7.3", "优雅的 Python 日志记录库，支持结构化输出与文件轮转", "Elegant Python logging library with structured output and log rotation",
     "https://pypi.org/project/loguru/"),
    ("lunardate", ">=0.2.2", "中国农历日期转换库，支持节气、节日计算", "Chinese lunar date conversion library with solar terms and festival calculation",
     "https://pypi.org/project/lunardate/"),
    ("ntplib", ">=0.4.0", "NTP (网络时间协议) 客户端，用于精准时间同步", "NTP client for accurate time synchronization",
     "https://pypi.org/project/ntplib/"),
    ("Pillow", ">=11.0.0", "Python 图像处理库 (PIL Fork)，用于图标与图像操作", "Python imaging library (PIL fork) for icon and image processing",
     "https://pypi.org/project/Pillow/"),
    ("platformdirs", ">=4.9.4", "跨平台应用目录定位库，用于获取系统标准数据路径", "Cross-platform application directory library for system standard paths",
     "https://pypi.org/project/platformdirs/"),
    ("pynput", ">=1.8.1", "跨平台键鼠控制与监听库", "Cross-platform keyboard and mouse control/listener library",
     "https://pypi.org/project/pynput/"),
    ("requests", ">=2.32.0", "简洁易用的 HTTP 客户端库，用于网络请求", "Simple and widely used HTTP client library",
     "https://pypi.org/project/requests/"),
    ("tzdata", ">=2024.1", "IANA 时区数据包，保障跨平台时区支持", "IANA timezone data package for cross-platform timezone support",
     "https://pypi.org/project/tzdata/"),
    ("pip", ">=26.0.1", "Python 包安装管理器，用于运行时依赖安装", "Python package installer used for runtime dependency installation",
     "https://pypi.org/project/pip/"),
]

# ─────────────────────────────────────────────────────────────────────────── #
# 鸣谢列表
# ─────────────────────────────────────────────────────────────────────────── #
_ACKS: list[tuple[str, str, str, str, str]] = [
    # (中文名称, 英文名称, 中文描述, 英文描述, 链接)
    ("zhiyiYo / QFluentWidgets", "zhiyiYo / QFluentWidgets",
     "提供精美的 Fluent Design 风格 Qt 组件库，是本项目 UI 的基石。", "Provides fluent-style Qt components and serves as the UI foundation of this project.",
     "https://github.com/zhiyiYo/PyQt-Fluent-Widgets"),
    ("Qt Company / PySide6", "Qt Company / PySide6",
     "感谢 Qt 官方提供强大的跨平台 GUI 框架及 Python 绑定。", "Thanks to Qt for providing a powerful cross-platform GUI framework and Python bindings.",
     "https://www.qt.io/"),
    ("所有贡献者", "All Contributors",
     "感谢每一位为本项目提交代码、提出 Issue、分享反馈的朋友们！", "Thanks to everyone who submitted code, opened issues, and shared feedback.",
     GITHUB_URL + "/graphs/contributors"),
    ("所有测试用户", "All Beta Testers",
     "感谢在测试阶段体验并提出宝贵意见的用户，你们的反馈让小树时钟做得更好。", "Thanks to all beta users whose feedback helped improve Little Tree Clock.",
     ""),
]

# ─────────────────────────────────────────────────────────────────────────── #
# 赞助列表（在此处可以添加赞助者信息）
# ─────────────────────────────────────────────────────────────────────────── #
_SPONSORS: list[tuple[str, str]] = [
    # (昵称, 留言/备注)  —— 目前暂无赞助记录
]


# ─────────────────────────────────────────────────────────────────────────── #
# 辅助：水平分隔线
# ─────────────────────────────────────────────────────────────────────────── #
def _make_separator(parent: QWidget) -> QFrame:
    line = QFrame(parent)
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setFixedHeight(1)
    return line


# ─────────────────────────────────────────────────────────────────────────── #
# 辅助：无横向滚动的透明滚动区域
# ─────────────────────────────────────────────────────────────────────────── #
def _make_scroll() -> SmoothScrollArea:
    scroll = SmoothScrollArea()
    scroll.setWidgetResizable(True)
    scroll.enableTransparentBackground()
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    return scroll


# ─────────────────────────────────────────────────────────────────────────── #
# 依赖卡片
# ─────────────────────────────────────────────────────────────────────────── #
class _DepCard(CardWidget):
    """单个依赖项卡片"""

    def __init__(self, name: str, version: str, desc: str, url: str, parent=None):
        super().__init__(parent)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 16, 14)
        outer.setSpacing(12)

        icon_widget = IconWidget(FIF.CODE, self)
        icon_widget.setFixedSize(28, 28)
        outer.addWidget(icon_widget, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        text_col.setContentsMargins(0, 0, 0, 0)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_lbl = StrongBodyLabel(name, self)
        ver_lbl = CaptionLabel(version, self)
        name_row.addWidget(name_lbl)
        name_row.addWidget(ver_lbl)
        name_row.addStretch()

        desc_lbl = BodyLabel(desc, self)
        desc_lbl.setWordWrap(True)

        text_col.addLayout(name_row)
        text_col.addWidget(desc_lbl)
        outer.addLayout(text_col, 1)

        if url:
            link_btn = PushButton(FIF.LINK, _tr("查看", "View"), self)
            link_btn.setFixedWidth(80)
            link_btn.clicked.connect(lambda: __import__("webbrowser").open(url))
            outer.addWidget(link_btn, 0, Qt.AlignVCenter)


# ─────────────────────────────────────────────────────────────────────────── #
# 鸣谢卡片
# ─────────────────────────────────────────────────────────────────────────── #
class _AckCard(CardWidget):
    """单个鸣谢项卡片"""

    def __init__(self, title: str, desc: str, url: str, parent=None):
        super().__init__(parent)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 16, 16, 16)
        outer.setSpacing(12)

        icon_widget = IconWidget(FIF.PEOPLE, self)
        icon_widget.setFixedSize(28, 28)
        outer.addWidget(icon_widget, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        text_col.setContentsMargins(0, 0, 0, 0)

        title_lbl = StrongBodyLabel(title, self)
        desc_lbl = BodyLabel(desc, self)
        desc_lbl.setWordWrap(True)

        text_col.addWidget(title_lbl)
        text_col.addWidget(desc_lbl)
        outer.addLayout(text_col, 1)

        if url:
            link_btn = PushButton(FIF.LINK, _tr("查看", "View"), self)
            link_btn.setFixedWidth(80)
            link_btn.clicked.connect(lambda: __import__("webbrowser").open(url))
            outer.addWidget(link_btn, 0, Qt.AlignVCenter)


# ─────────────────────────────────────────────────────────────────────────── #
# 赞助卡片
# ─────────────────────────────────────────────────────────────────────────── #
class _SponsorCard(CardWidget):
    """单个赞助者卡片"""

    def __init__(self, name: str, note: str, parent=None):
        super().__init__(parent)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 14)
        outer.setSpacing(12)

        icon_widget = IconWidget(FIF.HEART, self)
        icon_widget.setFixedSize(24, 24)
        outer.addWidget(icon_widget, 0, Qt.AlignVCenter)

        name_lbl = StrongBodyLabel(name, self)
        outer.addWidget(name_lbl, 0, Qt.AlignVCenter)

        if note:
            note_lbl = BodyLabel(f"· {note}", self)
            outer.addWidget(note_lbl, 0, Qt.AlignVCenter)

        outer.addStretch()


# ─────────────────────────────────────────────────────────────────────────── #
# 关于窗口
# ─────────────────────────────────────────────────────────────────────────── #
class AboutWindow(FluentWidget):
    """关于本项目窗口。

    继承 FluentWidget：
    - 云母/亚克力背景，与主窗口保持一致
    - 自动跟随系统深浅色切换
    - 无边框 + Fluent 标题栏
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_tr(f"关于 {APP_NAME}", f"About {APP_NAME}"))
        self.resize(700, 600)
        self.setMinimumSize(600, 500)
        if ICON_PATH:
            self.setWindowIcon(QIcon(ICON_PATH))

        # ── 根布局：留出标题栏高度 ─────────────────────────────── #
        root = QVBoxLayout(self)
        root.setContentsMargins(0, self.titleBar.height(), 0, 0)
        root.setSpacing(0)

        # ── 分段选项卡 ────────────────────────────────────────────── #
        self._seg = SegmentedWidget(self)
        self._stack = QStackedWidget(self)
        self._stack.setStyleSheet("QStackedWidget { background: transparent; }")

        seg_row = QHBoxLayout()
        seg_row.setContentsMargins(24, 8, 24, 0)
        seg_row.addWidget(self._seg, 0, Qt.AlignLeft)
        root.addLayout(seg_row)
        root.addSpacing(4)
        root.addWidget(self._stack, 1)

        # ── 各页初始化 ─────────────────────────────────────────────── #
        self._init_info_page()
        self._init_deps_page()
        self._init_acks_page()
        self._init_sponsors_page()

        # 默认显示第一页
        self._seg.setCurrentItem("info")
        self._stack.setCurrentWidget(self._info_scroll)

    # ------------------------------------------------------------------ #
    # Tab 注册
    # ------------------------------------------------------------------ #
    def _add_page(self, widget: QWidget, route_key: str, text: str) -> None:
        widget.setObjectName(route_key)
        self._stack.addWidget(widget)
        self._seg.addItem(
            routeKey=route_key,
            text=text,
            onClick=lambda: self._stack.setCurrentWidget(widget),
        )

    # ------------------------------------------------------------------ #
    # 项目信息页
    # ------------------------------------------------------------------ #
    def _init_info_page(self) -> None:
        self._info_scroll = _make_scroll()

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = VBoxLayout(container)
        layout.setContentsMargins(32, 20, 32, 24)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignTop)

        # ── 应用图标 + 名称卡片 ─────────────────────────── #
        header_card = CardWidget(container)
        header_inner = QVBoxLayout(header_card)
        header_inner.setContentsMargins(24, 22, 24, 22)
        header_inner.setSpacing(8)
        header_inner.setAlignment(Qt.AlignCenter)

        if ICON_PATH:
            icon_lbl = ImageLabel(ICON_PATH, header_card)
            icon_lbl.setFixedSize(88, 88)
            header_inner.addWidget(icon_lbl, 0, Qt.AlignHCenter)

        app_name_lbl = TitleLabel(APP_NAME, header_card)
        ver_lbl = SubtitleLabel(_tr(f"版本  {APP_VERSION}", f"Version {APP_VERSION}"), header_card)
        long_ver_lbl = CaptionLabel(LONG_VER, header_card)
        long_ver_lbl.setAlignment(Qt.AlignCenter)

        desc_lbl = BodyLabel(
            _tr(
                "基于 PySide6 + QFluentWidgets 的桌面时钟工具\n提供多样化的时钟功能与自动化拓展体验。",
                "A desktop clock toolkit built with PySide6 + QFluentWidgets\nwith diverse clock features and automation extensions.",
            ),
            header_card,
        )
        desc_lbl.setAlignment(Qt.AlignCenter)

        header_inner.addWidget(app_name_lbl, 0, Qt.AlignHCenter)
        header_inner.addWidget(ver_lbl, 0, Qt.AlignHCenter)
        header_inner.addWidget(long_ver_lbl, 0, Qt.AlignHCenter)
        header_inner.addSpacing(6)
        header_inner.addWidget(desc_lbl, 0, Qt.AlignHCenter)
        layout.addWidget(header_card)

        # ── 项目链接卡片 ─────────────────────────────────── #
        links_card = CardWidget(container)
        links_inner = QVBoxLayout(links_card)
        links_inner.setContentsMargins(20, 14, 20, 14)
        links_inner.setSpacing(10)

        links_title_lbl = StrongBodyLabel(_tr("项目链接", "Project Links"), links_card)
        links_inner.addWidget(links_title_lbl)
        links_inner.addWidget(_make_separator(links_card))

        github_row = QHBoxLayout()
        github_icon = IconWidget(FIF.GITHUB, links_card)
        github_icon.setFixedSize(20, 20)
        github_lbl = BodyLabel(_tr("GitHub 仓库", "GitHub Repository"), links_card)
        github_link = HyperlinkButton(GITHUB_URL, _tr("打开", "Open"), links_card)
        github_row.addWidget(github_icon)
        github_row.addSpacing(8)
        github_row.addWidget(github_lbl)
        github_row.addStretch()
        github_row.addWidget(github_link)
        links_inner.addLayout(github_row)

        issue_row = QHBoxLayout()
        issue_icon = IconWidget(FIF.FEEDBACK, links_card)
        issue_icon.setFixedSize(20, 20)
        issue_lbl = BodyLabel(_tr("问题反馈 / Issues", "Issues / Feedback"), links_card)
        issue_link = HyperlinkButton(GITHUB_URL + "/issues", _tr("打开", "Open"), links_card)
        issue_row.addWidget(issue_icon)
        issue_row.addSpacing(8)
        issue_row.addWidget(issue_lbl)
        issue_row.addStretch()
        issue_row.addWidget(issue_link)
        links_inner.addLayout(issue_row)

        layout.addWidget(links_card)

        # ── 许可证信息卡片 ───────────────────────────────── #
        license_card = CardWidget(container)
        license_inner = QHBoxLayout(license_card)
        license_inner.setContentsMargins(20, 14, 20, 14)
        license_inner.setSpacing(12)

        lic_icon = IconWidget(FIF.CERTIFICATE, license_card)
        lic_icon.setFixedSize(24, 24)
        lic_text_col = QVBoxLayout()
        lic_title = StrongBodyLabel(_tr("开源许可证", "Open-source License"), license_card)
        lic_desc = BodyLabel(_tr("本项目基于 GNU General Public License Version 3 发行，欢迎学习、修改与分发。", "This project is released under GNU GPL v3. You are welcome to learn, modify, and redistribute it."), license_card)
        lic_desc.setWordWrap(True)
        lic_text_col.addWidget(lic_title)
        lic_text_col.addWidget(lic_desc)

        lic_link = HyperlinkButton(
            GITHUB_URL + "/blob/master/LICENSE",
            _tr("查看 LICENSE", "View LICENSE"),
            license_card,
        )

        license_inner.addWidget(lic_icon, 0, Qt.AlignVCenter)
        license_inner.addLayout(lic_text_col, 1)
        license_inner.addWidget(lic_link, 0, Qt.AlignVCenter)
        layout.addWidget(license_card)
        layout.addStretch()

        self._info_scroll.setWidget(container)
        self._add_page(self._info_scroll, "info", _tr("项目信息", "Project Info"))

    # ------------------------------------------------------------------ #
    # 依赖信息页
    # ------------------------------------------------------------------ #
    def _init_deps_page(self) -> None:
        scroll = _make_scroll()

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = VBoxLayout(container)
        layout.setContentsMargins(32, 16, 32, 16)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)

        hint_lbl = CaptionLabel(
            _tr(
                f"以下为本项目所依赖的第三方库，共 {len(_DEPS)} 项。点击「查看」可访问对应主页。",
                f"Below are the third-party dependencies used by this project ({len(_DEPS)} total). Click 'View' to open the homepage.",
            ),
            container,
        )
        hint_lbl.setWordWrap(True)
        layout.addWidget(hint_lbl)
        layout.addSpacing(6)

        for name, version, zh_desc, en_desc, url in _DEPS:
            desc = _tr(zh_desc, en_desc)
            card = _DepCard(name, version, desc, url, container)
            layout.addWidget(card)

        layout.addStretch()
        scroll.setWidget(container)
        self._add_page(scroll, "deps", _tr("依赖信息", "Dependencies"))

    # ------------------------------------------------------------------ #
    # 鸣谢列表页
    # ------------------------------------------------------------------ #
    def _init_acks_page(self) -> None:
        scroll = _make_scroll()

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = VBoxLayout(container)
        layout.setContentsMargins(32, 16, 32, 16)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)

        hint_lbl = CaptionLabel(_tr("感谢以下项目与人员对小树时钟的贡献与支持！", "Thanks to the following projects and people for their support."), container)
        hint_lbl.setWordWrap(True)
        layout.addWidget(hint_lbl)
        layout.addSpacing(6)

        for zh_title, en_title, zh_desc, en_desc, url in _ACKS:
            title = _tr(zh_title, en_title)
            desc = _tr(zh_desc, en_desc)
            card = _AckCard(title, desc, url, container)
            layout.addWidget(card)

        layout.addStretch()
        scroll.setWidget(container)
        self._add_page(scroll, "acks", _tr("鸣谢列表", "Acknowledgements"))

    # ------------------------------------------------------------------ #
    # 赞助列表页
    # ------------------------------------------------------------------ #
    def _init_sponsors_page(self) -> None:
        scroll = _make_scroll()

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        layout = VBoxLayout(container)
        layout.setContentsMargins(32, 20, 32, 24)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignTop)

        if _SPONSORS:
            hint_lbl = CaptionLabel(
                _tr(
                    f"感谢以下 {len(_SPONSORS)} 位朋友对本项目的慷慨支持！",
                    f"Thanks to these {len(_SPONSORS)} supporters for backing this project!",
                ),
                container,
            )
            hint_lbl.setWordWrap(True)
            layout.addWidget(hint_lbl)
            layout.addSpacing(6)

            for name, note in _SPONSORS:
                card = _SponsorCard(name, note, container)
                layout.addWidget(card)
        else:
            # 空状态卡片
            empty_card = CardWidget(container)
            empty_inner = QVBoxLayout(empty_card)
            empty_inner.setContentsMargins(30, 40, 30, 40)
            empty_inner.setSpacing(12)
            empty_inner.setAlignment(Qt.AlignCenter)

            heart_icon = IconWidget(FIF.HEART, empty_card)
            heart_icon.setFixedSize(48, 48)
            empty_inner.addWidget(heart_icon, 0, Qt.AlignHCenter)

            empty_title = SubtitleLabel(_tr("暂无赞助记录", "No Sponsor Records Yet"), empty_card)
            empty_desc = BodyLabel(
                _tr(
                    "如果您喜欢小树时钟，欢迎通过 GitHub Sponsors 或其他方式支持我们！\n您的每一份支持都是我们持续开源的动力。",
                    "If you enjoy Little Tree Clock, feel free to support us via GitHub Sponsors or other channels.\nEvery bit of support helps us keep this project open-source.",
                ),
                empty_card,
            )
            empty_desc.setWordWrap(True)
            empty_desc.setAlignment(Qt.AlignCenter)

            sponsor_btn = PrimaryPushButton(FIF.HEART, _tr("赞助本项目", "Support This Project"), empty_card)
            sponsor_btn.setFixedWidth(160)
            sponsor_btn.clicked.connect(
                lambda: __import__("webbrowser").open(GITHUB_URL + "/blob/master/SUPPORT.md")
            )

            empty_inner.addWidget(empty_title, 0, Qt.AlignHCenter)
            empty_inner.addSpacing(8)
            empty_inner.addWidget(empty_desc, 0, Qt.AlignHCenter)
            empty_inner.addSpacing(16)
            empty_inner.addWidget(sponsor_btn, 0, Qt.AlignHCenter)

            layout.addWidget(empty_card)

        layout.addStretch()
        scroll.setWidget(container)
        self._add_page(scroll, "sponsors", _tr("赞助列表", "Sponsors"))
