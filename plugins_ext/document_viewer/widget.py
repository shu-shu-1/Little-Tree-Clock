"""文档浏览小组件。"""
from __future__ import annotations

import importlib
from html import escape
from pathlib import Path
from typing import Iterable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QStackedWidget,
)
from qfluentwidgets import BodyLabel, CaptionLabel, CheckBox, ColorPickerButton, PushButton, SmoothScrollArea, SpinBox

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.widgets.fluent_font_picker import FluentFontPicker


_WORD_SUFFIXES = {".docx", ".doc"}
_MARKDOWN_SUFFIXES = {".md", ".markdown"}
_TEXT_SUFFIXES = {".txt"}
_PDF_SUFFIXES = {".pdf"}


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _read_text_file(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gbk", "gb18030"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


class _DocumentEditPanel(QWidget):
    """文档浏览组件编辑面板。"""

    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setVerticalSpacing(10)

        self._full_path = str(props.get("path", "") or "")

        self._path_label = CaptionLabel(Path(self._full_path).name or "（未选择）")
        self._path_label.setWordWrap(True)

        pick_btn = PushButton("选择文档…")
        pick_btn.clicked.connect(self._pick_file)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(self._path_label, 1)
        row_layout.addWidget(pick_btn)
        form.addRow("文档文件:", row)

        self._auto_scroll = CheckBox("启用自动滚动")
        self._auto_scroll.setChecked(bool(props.get("auto_scroll", False)))
        form.addRow("滚动方式:", self._auto_scroll)

        self._scroll_speed = SpinBox()
        self._scroll_speed.setRange(1, 1500)
        self._scroll_speed.setSuffix(" px/s")
        self._scroll_speed.setValue(_safe_int(props.get("auto_scroll_speed", 60), 60))
        form.addRow("自动滚动速度:", self._scroll_speed)

        self._bg_color = ColorPickerButton(
            QColor(str(props.get("bg_color", "#FFFFFF") or "#FFFFFF")),
            "背景颜色",
        )
        form.addRow("背景颜色:", self._bg_color)

        self._font_picker = FluentFontPicker()
        self._font_picker.setCurrentFontFamily(str(props.get("font_family", "") or ""))
        form.addRow("字体:", self._font_picker)

        self._font_size = SpinBox()
        self._font_size.setRange(8, 96)
        self._font_size.setSuffix(" pt")
        self._font_size.setValue(_safe_int(props.get("font_size", 16), 16))
        form.addRow("字体大小:", self._font_size)

        self._word_keep_layout = CheckBox("Word 保留版式（尊崇原样）")
        self._word_keep_layout.setChecked(bool(props.get("word_keep_layout", True)))
        self._word_keep_layout.stateChanged.connect(lambda *_: self._sync_mode_state())
        form.addRow("Word 模式:", self._word_keep_layout)

        self._zoom = SpinBox()
        self._zoom.setRange(20, 400)
        self._zoom.setSuffix(" %")
        self._zoom.setValue(_safe_int(props.get("zoom_percent", 100), 100))
        form.addRow("缩放:", self._zoom)

        self._w_spin = SpinBox()
        self._w_spin.setRange(2, 20)
        self._w_spin.setValue(_safe_int(props.get("grid_w", 6), 6))
        form.addRow("横向格数:", self._w_spin)

        self._h_spin = SpinBox()
        self._h_spin.setRange(2, 20)
        self._h_spin.setValue(_safe_int(props.get("grid_h", 5), 5))
        form.addRow("纵向格数:", self._h_spin)

        self._mode_hint = BodyLabel("")
        self._mode_hint.setWordWrap(True)
        self._mode_hint.setStyleSheet("color:#888;background:transparent;")
        form.addRow("提示:", self._mode_hint)

        self._sync_mode_state()

    def _pick_file(self) -> None:
        start_dir = str(Path(self._full_path).parent) if self._full_path else ""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文档",
            start_dir,
            (
                "支持文档 (*.docx *.doc *.md *.markdown *.txt *.pdf);;"
                "Word 文档 (*.docx *.doc);;"
                "Markdown (*.md *.markdown);;"
                "文本文件 (*.txt);;"
                "PDF 文件 (*.pdf);;"
                "所有文件 (*)"
            ),
        )
        if not file_path:
            return

        self._full_path = file_path
        self._path_label.setText(Path(file_path).name)
        self._sync_mode_state()

    def _sync_mode_state(self) -> None:
        suffix = Path(self._full_path).suffix.lower()
        is_word = suffix in _WORD_SUFFIXES
        is_pdf = suffix in _PDF_SUFFIXES
        keep_layout = is_word and self._word_keep_layout.isChecked()

        self._word_keep_layout.setEnabled(is_word)
        if not is_word and self._word_keep_layout.isChecked():
            self._word_keep_layout.blockSignals(True)
            self._word_keep_layout.setChecked(False)
            self._word_keep_layout.blockSignals(False)
            keep_layout = False

        font_enabled = not keep_layout
        self._font_picker.setEnabled(font_enabled)
        self._font_size.setEnabled(font_enabled)

        zoom_enabled = is_pdf or keep_layout
        self._zoom.setEnabled(zoom_enabled)

        if is_word and keep_layout:
            self._mode_hint.setText("Word 保留版式模式：仅支持缩放；字体与字号设置会被忽略。")
        elif is_word:
            self._mode_hint.setText("Word 普通模式：支持字体与字号设置，适合演示/朗读。")
        elif is_pdf:
            self._mode_hint.setText("PDF 采用逐页渲染，支持手动滚动、自动滚动和缩放。")
        else:
            self._mode_hint.setText("Markdown/TXT 支持手动滚动、自动滚动、字体与字号设置。")

    def collect_props(self) -> dict:
        return {
            "path": self._full_path,
            "auto_scroll": self._auto_scroll.isChecked(),
            "auto_scroll_speed": self._scroll_speed.value(),
            "bg_color": self._bg_color.color.name(QColor.NameFormat.HexRgb),
            "font_family": self._font_picker.currentFontFamily(),
            "font_size": self._font_size.value(),
            "word_keep_layout": self._word_keep_layout.isChecked(),
            "zoom_percent": self._zoom.value(),
            "grid_w": self._w_spin.value(),
            "grid_h": self._h_spin.value(),
        }


class DocumentViewerWidget(WidgetBase):
    """支持 Word/Markdown/TXT/PDF 浏览的组件。"""

    WIDGET_TYPE = "document_viewer"
    WIDGET_NAME = "文档浏览"
    DELETABLE = True
    MIN_W = 2
    MIN_H = 2
    DEFAULT_W = 6
    DEFAULT_H = 5

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)

        self._render_key: tuple | None = None
        self._text_zoom_steps = 0
        self._auto_scroll_speed = 60
        self._bg_color = "#FFFFFF"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._stack = QStackedWidget(self)
        root.addWidget(self._stack, 1)

        self._text_view = QTextBrowser(self)
        self._text_view.setFrameShape(QFrame.Shape.NoFrame)
        self._text_view.setOpenExternalLinks(True)
        self._text_view.setOpenLinks(True)
        # 让右键事件冒泡到外层 WidgetItem，显示组件级菜单（编辑/删除等）。
        self._text_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._text_view.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._text_view.setStyleSheet("QTextBrowser { border: none; padding: 8px; }")
        self._stack.addWidget(self._text_view)

        self._pdf_scroll = SmoothScrollArea(self)
        self._pdf_scroll.setWidgetResizable(True)
        self._pdf_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._pdf_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._pdf_scroll.enableTransparentBackground()
        self._pdf_scroll.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._pdf_scroll.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        self._pdf_content = QWidget(self._pdf_scroll)
        self._pdf_content.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._pdf_layout = QVBoxLayout(self._pdf_content)
        self._pdf_layout.setContentsMargins(8, 8, 8, 8)
        self._pdf_layout.setSpacing(12)
        self._pdf_scroll.setWidget(self._pdf_content)
        self._stack.addWidget(self._pdf_scroll)

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(30)
        self._auto_timer.timeout.connect(self._on_auto_scroll)

        self._show_text_hint("点击右键 → 编辑", "选择 Word、Markdown、TXT 或 PDF 文档", self._bg_color)
        self.refresh()

    def get_edit_widget(self):
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _DocumentEditPanel(props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.config.grid_w = max(2, int(props.get("grid_w", self.DEFAULT_W)))
        self.config.grid_h = max(2, int(props.get("grid_h", self.DEFAULT_H)))
        self.refresh()

    def refresh(self) -> None:
        props = self.config.props

        path_text = str(props.get("path", "") or "").strip()
        suffix = Path(path_text).suffix.lower()
        doc_type = self._detect_doc_type(suffix)

        keep_layout = bool(props.get("word_keep_layout", True))
        zoom_percent = max(20, min(400, _safe_int(props.get("zoom_percent", 100), 100)))
        bg_color = self._normalize_hex_color(str(props.get("bg_color", "#FFFFFF") or "#FFFFFF"))
        self._bg_color = bg_color
        font_family = str(props.get("font_family", "") or "")
        font_size = max(8, min(96, _safe_int(props.get("font_size", 16), 16)))

        self._apply_background_color(bg_color)

        render_key = self._build_render_key(
            doc_type=doc_type,
            path_text=path_text,
            keep_layout=keep_layout,
            zoom_percent=zoom_percent,
            bg_color=bg_color,
            font_family=font_family,
            font_size=font_size,
        )

        if render_key != self._render_key:
            self._render_key = render_key
            self._render_document(
                doc_type=doc_type,
                path_text=path_text,
                keep_layout=keep_layout,
                zoom_percent=zoom_percent,
                bg_color=bg_color,
                font_family=font_family,
                font_size=font_size,
            )

        self._auto_scroll_speed = max(1, min(1500, _safe_int(props.get("auto_scroll_speed", 60), 60)))
        auto_scroll = bool(props.get("auto_scroll", False))
        self._sync_auto_scroll(auto_scroll)

    @staticmethod
    def _detect_doc_type(suffix: str) -> str:
        if suffix in _WORD_SUFFIXES:
            return "word"
        if suffix in _MARKDOWN_SUFFIXES:
            return "markdown"
        if suffix in _TEXT_SUFFIXES:
            return "text"
        if suffix in _PDF_SUFFIXES:
            return "pdf"
        return "unknown"

    @staticmethod
    def _build_render_key(
        *,
        doc_type: str,
        path_text: str,
        keep_layout: bool,
        zoom_percent: int,
        bg_color: str,
        font_family: str,
        font_size: int,
    ) -> tuple:
        if doc_type == "word" and keep_layout:
            return (doc_type, path_text, keep_layout, zoom_percent, bg_color)
        if doc_type == "pdf":
            return (doc_type, path_text, zoom_percent, bg_color)
        return (doc_type, path_text, bg_color, font_family, font_size)

    @staticmethod
    def _normalize_hex_color(value: str, fallback: str = "#FFFFFF") -> str:
        color = QColor(str(value or "").strip())
        if not color.isValid():
            color = QColor(fallback)
        return color.name(QColor.NameFormat.HexRgb)

    @staticmethod
    def _is_dark_color(hex_color: str) -> bool:
        color = QColor(hex_color)
        if not color.isValid():
            return False
        luminance = 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()
        return luminance < 0.55

    def _palette_for_bg(self, bg_color: str) -> dict[str, str]:
        if self._is_dark_color(bg_color):
            return {
                "text": "#F2F2F2",
                "muted": "#CFCFCF",
                "link": "#80C8FF",
                "warn": "#F3C969",
                "table_border": "rgba(255,255,255,0.30)",
            }
        return {
            "text": "#1F1F1F",
            "muted": "#5A5A5A",
            "link": "#0B62D6",
            "warn": "#9A5B00",
            "table_border": "rgba(0,0,0,0.22)",
        }

    def _apply_background_color(self, bg_color: str) -> None:
        self._text_view.setStyleSheet(
            "QTextBrowser {"
            f"background: {bg_color};"
            "border: none;"
            "padding: 8px;"
            "}"
        )
        self._pdf_scroll.setStyleSheet(
            "QScrollArea {"
            f"background: {bg_color};"
            "border: none;"
            "}"
        )
        self._pdf_scroll.viewport().setStyleSheet(f"background:{bg_color};")
        self._pdf_content.setStyleSheet(f"background:{bg_color};")

    def _render_document(
        self,
        *,
        doc_type: str,
        path_text: str,
        keep_layout: bool,
        zoom_percent: int,
        bg_color: str,
        font_family: str,
        font_size: int,
    ) -> None:
        if not path_text:
            self._show_text_hint("点击右键 → 编辑", "选择 Word、Markdown、TXT 或 PDF 文档", bg_color)
            return

        path = Path(path_text)
        if not path.exists() or not path.is_file():
            self._show_text_hint("文件不可用", f"未找到文件：{escape(path_text)}", bg_color)
            return

        if doc_type == "markdown":
            self._render_markdown(path, font_family, font_size, bg_color)
            return

        if doc_type == "text":
            self._render_plain_text(path, font_family, font_size, bg_color)
            return

        if doc_type == "word":
            self._render_word(path, keep_layout, zoom_percent, bg_color, font_family, font_size)
            return

        if doc_type == "pdf":
            self._render_pdf(path, zoom_percent, bg_color)
            return

        self._show_text_hint(
            "不支持的文件格式",
            f"当前仅支持 Word、Markdown、TXT、PDF。\n文件：{escape(path.name)}",
            bg_color,
        )

    def _sync_auto_scroll(self, enabled: bool) -> None:
        bar = self._active_scrollbar()
        can_scroll = bar is not None and bar.maximum() > 0
        should_run = enabled and can_scroll

        if should_run and not self._auto_timer.isActive():
            self._auto_timer.start()
        elif not should_run and self._auto_timer.isActive():
            self._auto_timer.stop()

    def _active_scrollbar(self):
        if self._stack.currentWidget() is self._pdf_scroll:
            return self._pdf_scroll.verticalScrollBar()
        return self._text_view.verticalScrollBar()

    def _on_auto_scroll(self) -> None:
        bar = self._active_scrollbar()
        if bar is None or bar.maximum() <= 0:
            return

        delta = max(1, round(self._auto_scroll_speed * self._auto_timer.interval() / 1000.0))
        next_value = bar.value() + int(delta)
        if next_value >= bar.maximum():
            bar.setValue(bar.maximum())
            self._auto_timer.stop()
            return
        bar.setValue(next_value)

    def _default_style(self, font_family: str, font_size: int, bg_color: str) -> str:
        palette = self._palette_for_bg(bg_color)
        family_part = f"font-family:'{escape(font_family)}';" if font_family else ""
        return (
            "body {"
            "background: transparent;"
            f"color: {palette['text']};"
            f"font-size: {font_size}pt;"
            f"{family_part}"
            "line-height: 1.65;"
            "}"
            "p { margin: 0.35em 0; }"
            "pre { white-space: pre-wrap; word-break: break-word; }"
            f"table, th, td {{ border: 1px solid {palette['table_border']}; border-collapse: collapse; padding: 4px; }}"
            f"a {{ color: {palette['link']}; }}"
        )

    def _word_preserve_style(self, bg_color: str) -> str:
        palette = self._palette_for_bg(bg_color)
        return (
            "body {"
            "background: transparent;"
            f"color: {palette['text']};"
            "line-height: 1.5;"
            "}"
            "p { margin: 0.35em 0; }"
            f"table, th, td {{ border: 1px solid {palette['table_border']}; border-collapse: collapse; padding: 4px; }}"
            "img { max-width: 100%; }"
            f"a {{ color: {palette['link']}; }}"
        )

    def _show_text_hint(self, title: str, detail: str = "", bg_color: str = "#FFFFFF") -> None:
        self._stack.setCurrentWidget(self._text_view)
        self._reset_text_zoom()
        self._text_view.document().setDefaultStyleSheet(self._default_style("", 14, bg_color))

        body = [f"<h3>{escape(title)}</h3>"]
        if detail:
            body.append(f"<p>{detail.replace(chr(10), '<br>')}</p>")
        self._text_view.setHtml("<html><body>" + "".join(body) + "</body></html>")

    def _apply_text_zoom(self, zoom_percent: int) -> None:
        self._reset_text_zoom()
        steps = int(round((zoom_percent - 100) / 10))
        if steps > 0:
            self._text_view.zoomIn(steps)
        elif steps < 0:
            self._text_view.zoomOut(-steps)
        self._text_zoom_steps = steps

    def _reset_text_zoom(self) -> None:
        if self._text_zoom_steps > 0:
            self._text_view.zoomOut(self._text_zoom_steps)
        elif self._text_zoom_steps < 0:
            self._text_view.zoomIn(-self._text_zoom_steps)
        self._text_zoom_steps = 0

    def _render_markdown(self, path: Path, font_family: str, font_size: int, bg_color: str) -> None:
        try:
            raw = _read_text_file(path)
        except Exception as exc:
            self._show_text_hint("读取 Markdown 失败", escape(str(exc)), bg_color)
            return

        self._stack.setCurrentWidget(self._text_view)
        self._reset_text_zoom()
        self._text_view.document().setDefaultStyleSheet(self._default_style(font_family, font_size, bg_color))
        self._text_view.setMarkdown(raw)

        bar = self._text_view.verticalScrollBar()
        bar.setValue(0)

    def _render_plain_text(self, path: Path, font_family: str, font_size: int, bg_color: str) -> None:
        try:
            raw = _read_text_file(path)
        except Exception as exc:
            self._show_text_hint("读取文本失败", escape(str(exc)), bg_color)
            return

        body_html = "<pre>" + escape(raw) + "</pre>"
        self._stack.setCurrentWidget(self._text_view)
        self._reset_text_zoom()
        self._text_view.document().setDefaultStyleSheet(self._default_style(font_family, font_size, bg_color))
        self._text_view.setHtml("<html><body>" + body_html + "</body></html>")

        bar = self._text_view.verticalScrollBar()
        bar.setValue(0)

    def _render_word(
        self,
        path: Path,
        keep_layout: bool,
        zoom_percent: int,
        bg_color: str,
        font_family: str,
        font_size: int,
    ) -> None:
        suffix = path.suffix.lower()
        if suffix == ".doc":
            self._show_text_hint("暂不支持 .doc 旧格式", "请先将文件另存为 .docx 后再打开。", bg_color)
            return

        if keep_layout:
            html, warning = self._convert_docx_preserve_html(path)
            if not html:
                self._show_text_hint("Word 解析失败", warning or "未能读取文档内容", bg_color)
                return

            self._stack.setCurrentWidget(self._text_view)
            self._reset_text_zoom()
            palette = self._palette_for_bg(bg_color)
            self._text_view.document().setDefaultStyleSheet(self._word_preserve_style(bg_color))

            wrapped = html
            if warning:
                wrapped = (
                    f"<p style='color:{palette['warn']};'>"
                    f"提示：{escape(warning)}"
                    "</p>"
                    + html
                )
            self._text_view.setHtml("<html><body>" + wrapped + "</body></html>")
            self._apply_text_zoom(zoom_percent)
            self._text_view.verticalScrollBar().setValue(0)
            return

        try:
            html = self._convert_docx_plain_html(path)
        except Exception as exc:
            self._show_text_hint("Word 解析失败", escape(str(exc)), bg_color)
            return

        self._stack.setCurrentWidget(self._text_view)
        self._reset_text_zoom()
        self._text_view.document().setDefaultStyleSheet(self._default_style(font_family, font_size, bg_color))
        self._text_view.setHtml("<html><body>" + html + "</body></html>")
        self._text_view.verticalScrollBar().setValue(0)

    def _render_pdf(self, path: Path, zoom_percent: int, bg_color: str) -> None:
        self._stack.setCurrentWidget(self._pdf_scroll)
        self._clear_pdf_layout()

        try:
            fitz = importlib.import_module("fitz")
        except Exception:
            self._set_pdf_hint(
                "缺少依赖：pymupdf（PyMuPDF）。\n请在插件权限弹窗中允许安装依赖后重试。",
                bg_color,
            )
            return

        scale = max(0.2, min(4.0, zoom_percent / 100.0))

        try:
            doc = fitz.open(str(path))
        except Exception as exc:
            self._set_pdf_hint(f"PDF 打开失败：{escape(str(exc))}", bg_color)
            return

        with doc:
            if doc.page_count <= 0:
                self._set_pdf_hint("PDF 文件为空。", bg_color)
                return

            palette = self._palette_for_bg(bg_color)

            for index in range(doc.page_count):
                page = doc.load_page(index)
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)

                img_format = QImage.Format.Format_RGB888 if pix.n < 4 else QImage.Format.Format_RGBA8888
                image = QImage(pix.samples, pix.width, pix.height, pix.stride, img_format).copy()
                pixmap = QPixmap.fromImage(image)

                page_wrap = QWidget(self._pdf_content)
                page_wrap.setStyleSheet("background: transparent;")
                page_layout = QVBoxLayout(page_wrap)
                page_layout.setContentsMargins(0, 0, 0, 0)
                page_layout.setSpacing(4)

                page_label = QLabel(page_wrap)
                page_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
                page_label.setPixmap(pixmap)
                page_label.setStyleSheet("background: transparent;")

                index_label = CaptionLabel(f"第 {index + 1} / {doc.page_count} 页", page_wrap)
                index_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
                index_label.setStyleSheet(
                    f"color:{palette['muted']};background:transparent;"
                )

                page_layout.addWidget(page_label, 0, Qt.AlignmentFlag.AlignHCenter)
                page_layout.addWidget(index_label)

                self._pdf_layout.addWidget(page_wrap)

        self._pdf_layout.addStretch(1)
        self._pdf_scroll.verticalScrollBar().setValue(0)

    def _clear_pdf_layout(self) -> None:
        while self._pdf_layout.count():
            item = self._pdf_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_pdf_hint(self, text: str, bg_color: str = "#FFFFFF") -> None:
        self._stack.setCurrentWidget(self._pdf_scroll)
        self._clear_pdf_layout()

        palette = self._palette_for_bg(bg_color)

        self._pdf_layout.addStretch(1)
        hint = CaptionLabel(text, self._pdf_content)
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color:{palette['muted']};background:transparent;")
        self._pdf_layout.addWidget(hint)
        self._pdf_layout.addStretch(1)

    def _convert_docx_preserve_html(self, path: Path) -> tuple[str, str]:
        warning = ""

        try:
            mammoth = importlib.import_module("mammoth")

            with path.open("rb") as fp:
                result = mammoth.convert_to_html(fp)
            html = str(result.value or "").strip()
            if html:
                messages = [str(msg) for msg in getattr(result, "messages", []) if str(msg).strip()]
                if messages:
                    warning = "；".join(messages[:3])
                return html, warning
            warning = "mammoth 未输出有效内容，已回退兼容模式。"
        except Exception:
            warning = "mammoth 不可用，已回退兼容模式。"

        try:
            return self._convert_docx_html(path, preserve_styles=True), warning
        except Exception as exc:
            if warning:
                return "", f"{warning} {exc}"
            return "", str(exc)

    def _convert_docx_plain_html(self, path: Path) -> str:
        return self._convert_docx_html(path, preserve_styles=False)

    def _convert_docx_html(self, path: Path, *, preserve_styles: bool) -> str:
        try:
            docx_module = importlib.import_module("docx")
            table_module = importlib.import_module("docx.table")
            paragraph_module = importlib.import_module("docx.text.paragraph")
        except Exception as exc:
            raise RuntimeError(f"缺少依赖 python-docx：{exc}") from exc

        Document = getattr(docx_module, "Document")
        Table = getattr(table_module, "Table")
        Paragraph = getattr(paragraph_module, "Paragraph")

        doc = Document(str(path))
        blocks: list[str] = []

        for block in self._iter_docx_blocks(doc, Paragraph, Table):
            if isinstance(block, Paragraph):
                blocks.append(self._paragraph_to_html(block, preserve_styles=preserve_styles))
            elif isinstance(block, Table):
                blocks.append(self._table_to_html(block, preserve_styles=preserve_styles))

        content = "".join(part for part in blocks if part.strip())
        if not content:
            return "<p>（Word 文档为空）</p>"
        return content

    @staticmethod
    def _iter_docx_blocks(doc, paragraph_type, table_type) -> Iterable:
        body = doc.element.body
        for child in body.iterchildren():
            tag = str(getattr(child, "tag", ""))
            if tag.endswith("}p"):
                yield paragraph_type(child, doc)
            elif tag.endswith("}tbl"):
                yield table_type(child, doc)

    def _paragraph_to_html(self, paragraph, *, preserve_styles: bool) -> str:
        runs_html: list[str] = []

        if paragraph.runs:
            for run in paragraph.runs:
                text = escape(run.text or "")
                if not text:
                    continue
                text = text.replace("\n", "<br>").replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")

                if preserve_styles:
                    style_parts: list[str] = []
                    if run.bold:
                        style_parts.append("font-weight:700;")
                    if run.italic:
                        style_parts.append("font-style:italic;")
                    if run.underline:
                        style_parts.append("text-decoration:underline;")

                    font = getattr(run, "font", None)
                    if font is not None:
                        name = str(getattr(font, "name", "") or "").strip()
                        if name:
                            style_parts.append(f"font-family:'{escape(name)}';")
                        size = getattr(font, "size", None)
                        size_pt = getattr(size, "pt", None)
                        if size_pt:
                            style_parts.append(f"font-size:{float(size_pt):.2f}pt;")
                        color_obj = getattr(font, "color", None)
                        rgb = getattr(color_obj, "rgb", None)
                        if rgb:
                            style_parts.append(f"color:#{rgb};")

                    if style_parts:
                        runs_html.append(f"<span style='{''.join(style_parts)}'>{text}</span>")
                    else:
                        runs_html.append(text)
                else:
                    if run.bold:
                        text = f"<strong>{text}</strong>"
                    if run.italic:
                        text = f"<em>{text}</em>"
                    if run.underline:
                        text = f"<u>{text}</u>"
                    runs_html.append(text)
        else:
            plain = escape(paragraph.text or "")
            if plain:
                runs_html.append(plain)

        if not runs_html:
            return "<p><br></p>"

        para_style = ""
        align = getattr(paragraph, "alignment", None)
        align_name = str(getattr(align, "name", "") or "").lower()
        if "center" in align_name:
            para_style += "text-align:center;"
        elif "right" in align_name:
            para_style += "text-align:right;"
        elif "justify" in align_name:
            para_style += "text-align:justify;"

        if para_style:
            return f"<p style='{para_style}'>{''.join(runs_html)}</p>"
        return f"<p>{''.join(runs_html)}</p>"

    def _table_to_html(self, table, *, preserve_styles: bool) -> str:
        rows_html: list[str] = []
        for row in table.rows:
            cells_html: list[str] = []
            for cell in row.cells:
                cell_blocks = [
                    self._paragraph_to_html(para, preserve_styles=preserve_styles)
                    for para in cell.paragraphs
                ]
                cell_html = "".join(cell_blocks) or "<p><br></p>"
                cells_html.append(f"<td>{cell_html}</td>")
            rows_html.append("<tr>" + "".join(cells_html) + "</tr>")

        return "<table>" + "".join(rows_html) + "</table>"
