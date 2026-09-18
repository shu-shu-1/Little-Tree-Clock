"""每日一图视图及相关后台线程"""

import io

import requests
from PIL import Image

from qfluentwidgets import (
    ImageLabel,
    ProgressRing,
    IndeterminateProgressRing,
    PushButton,
    InfoBar,
    InfoBarPosition,
)
from PySide6.QtCore import QThread, Signal, Qt, QRect
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QFrame, QLabel

from app.constants import BING_API_URL, BING_BASE_URL, USER_AGENT, TEMP_DIR
from app.services.i18n_service import I18nService, pick
from app.utils.fs import write_bytes_with_uac


def _tr(i18n: I18nService, zh: str, en: str) -> str:
    return pick(zh, en)


class BingFetchThread(QThread):
    """从 Bing API 获取近 7 天的壁纸元数据列表"""

    finished = Signal(list)  # 失败时发送 ["Error"]

    def run(self):
        try:
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": USER_AGENT,
            }
            resp = requests.get(BING_API_URL, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            img_list = []
            for item in data["images"]:
                raw_date = item["enddate"]
                img_list.append(
                    {
                        "copyright": item["copyright"],
                        "date": f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}",
                        "urlbase": BING_BASE_URL + item["urlbase"],
                        "url": BING_BASE_URL + item["url"],
                        "title": item["title"],
                        "copyrightlink": item["copyrightlink"],
                    }
                )
            self.finished.emit(img_list)
        except Exception:
            self.finished.emit(["Error"])


class ImageDownloadThread(QThread):
    progress = Signal(int)  # 0–100
    finished = Signal(str)  # 失败时发送空字符串

    def __init__(self, url: str, save_dir: str = TEMP_DIR, filename: str = "today"):
        super().__init__()
        self._url = url
        self._save_dir = save_dir
        self._filename = filename

    def run(self):
        try:
            headers = {"User-Agent": USER_AGENT}
            resp = requests.get(self._url, headers=headers, stream=True, timeout=30)
            resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0)) or (4 * 1024 * 1024)
            downloaded = 0
            buf = io.BytesIO()

            for chunk in resp.iter_content(chunk_size=4096):
                buf.write(chunk)
                downloaded += len(chunk)
                self.progress.emit(min(int(downloaded / total * 100), 99))

            buf.seek(0)
            img = Image.open(buf)
            fmt = (img.format or "jpeg").lower()
            path = f"{self._save_dir}/{self._filename}.{fmt}"

            buf.seek(0)
            write_bytes_with_uac(path, buf.getvalue(), ensure_parent=True)

            self.progress.emit(100)
            self.finished.emit(path)
        except Exception:
            self.finished.emit("")


class TodayView(QFrame):
    """每日一图页面，切换至该页面时自动获取今日壁纸"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("today")
        self._i18n = I18nService.instance()

        self._meta: list[dict] = []
        self._auto_fetched = False

        self._build_ui()

    def _build_ui(self):
        self._spinner = IndeterminateProgressRing(self)
        self._spinner.setFixedSize(40, 40)
        self._spinner.setStrokeWidth(4)
        self._spinner.setGeometry(QRect(50, 45, 40, 40))
        self._spinner.hide()

        self._ring = ProgressRing(self)
        self._ring.setRange(0, 100)
        self._ring.setValue(0)
        self._ring.setFixedSize(80, 80)
        self._ring.setStrokeWidth(6)
        self._ring.setTextVisible(True)
        self._ring.setGeometry(QRect(35, 35, 80, 80))
        self._ring.hide()

        self._info_label = QLabel(self)
        self._info_label.setGeometry(QRect(50, 110, 700, 130))
        self._info_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._info_label.setWordWrap(True)
        self._info_label.setText(self._i18n.t("today.fetching_wallpaper"))
        font = QFont()
        font.setFamilies(["微软雅黑"])
        font.setPointSize(11)
        self._info_label.setFont(font)

        self._preview = ImageLabel(self)
        self._preview.setBorderRadius(8, 8, 8, 8)
        self._preview.setGeometry(QRect(50, 260, 356, 200))

        self._btn = PushButton(text=_tr(self._i18n, "重新获取", "Retry"), parent=self)
        self._btn.setGeometry(QRect(50, 480, 100, 32))
        self._btn.clicked.connect(self._start_fetch)
        self._btn.hide()  # 首次加载完成前隐藏

    def showEvent(self, event):
        super().showEvent(event)
        if not self._auto_fetched:
            self._auto_fetched = True
            self._start_fetch()

    def _start_fetch(self):
        self._btn.setEnabled(False)
        self._btn.hide()

        self._ring.hide()
        self._spinner.show()

        self._info_label.setText(self._i18n.t("today.fetching_info"))

        self._fetch_thread = BingFetchThread()
        self._fetch_thread.finished.connect(self._on_fetch_finished)
        self._fetch_thread.start()

    def _on_fetch_finished(self, meta: list):
        if not meta or meta[0] == "Error" or "url" not in meta[0]:
            self._show_error(self._i18n.t("today.error"), self._i18n.t("today.fetch_failed"))
            self._reset()
            return

        self._meta = meta

        self._spinner.hide()
        self._ring.setValue(0)
        self._ring.show()

        self._info_label.setText(self._i18n.t("today.downloading", title=meta[0]["title"]))
        self._start_download(meta[0]["url"])

    def _start_download(self, url: str):
        self._dl_thread = ImageDownloadThread(url)
        self._dl_thread.progress.connect(self._ring.setValue)
        self._dl_thread.finished.connect(self._on_download_finished)
        self._dl_thread.start()

    def _on_download_finished(self, path: str):
        if not path:
            self._show_error(
                self._i18n.t("today.error"),
                _tr(
                    self._i18n,
                    "图片下载过程中发生错误，请重试",
                    "An error occurred while downloading image, please retry",
                ),
            )
            self._reset()
            return

        self._ring.setValue(100)

        pixmap = QPixmap(path)
        self._preview.setImage(pixmap)
        self._preview.scaledToHeight(200)

        title = self._meta[0]["title"]
        copyright_ = self._meta[0]["copyright"]
        self._info_label.setText(
            _tr(
                self._i18n,
                f"今日标题：{title}\n版权信息：{copyright_}",
                f"Today's title: {title}\nCopyright: {copyright_}",
            )
        )

        InfoBar.success(
            title=self._i18n.t("today.success"),
            content=_tr(
                self._i18n, f"今日壁纸「{title}」已成功加载", f"Today's wallpaper '{title}' loaded successfully"
            ),
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

        self._btn.show()
        self._btn.setEnabled(True)

    def _show_error(self, title: str, content: str):
        InfoBar.error(
            title=title,
            content=content,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=4000,
            parent=self,
        )

    def _reset(self):
        self._spinner.hide()
        self._ring.hide()
        self._info_label.setText(self._i18n.t("today.fetch_failed"))
        self._btn.show()
        self._btn.setEnabled(True)
