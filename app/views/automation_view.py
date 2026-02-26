"""自动化规则管理视图 —— 使用 Pivot 顶部导航分页"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Slot, Signal, QMimeData
from PySide6.QtGui import QPainter, QPen, QColor, QDrag
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QStackedWidget, QLabel,
)
from qfluentwidgets import (
    SmoothScrollArea, FluentIcon as FIF, PushButton,
    CardWidget, TitleLabel, BodyLabel, CaptionLabel,
    StrongBodyLabel, SwitchButton, LineEdit, SpinBox,
    InfoBar, InfoBarPosition, MessageBox,
    ToolButton, Pivot, PrimaryPushButton, ComboBox,
    TabWidget,
)

from app.models.automation_model import (
    AutomationRule, AutomationStore,
    TriggerType, ActionType,
    TriggerConfig, ActionConfig,
)
from app.automation.engine import AutomationEngine


# ─────────────────────────────────────────────── helpers ────────────────── #

# 插件触发器名称缓存：{trigger_id: display_name}，每次插件扫描完成时刷新
_plugin_trigger_names: dict[str, str] = {}

# 触发器显示名称
TRIGGER_LABELS: dict[str, str] = {
    TriggerType.NONE:               "无触发器（仅手动执行）",
    TriggerType.APP_STARTUP:        "应用启动",
    TriggerType.APP_SHUTDOWN:       "应用退出",
    TriggerType.ALARM_FIRED:        "闹钟触发",
    TriggerType.TIMER_DONE:         "计时器结束",
    TriggerType.TIME_OF_DAY:        "每天某时刻",
    TriggerType.SCHEDULE_INTERVAL:  "每隔 N 分钟",
    TriggerType.MANUAL:             "手动触发（测试）",
    TriggerType.FOCUS_DISTRACTED:   "专注：不专注超限",
    TriggerType.FOCUS_SESSION_DONE: "专注：会话（轮次）结束",
    TriggerType.FOCUS_BREAK_START:  "专注：休息开始",
    TriggerType.FOCUS_BREAK_END:    "专注：休息结束",
    TriggerType.PLUGIN:             "[插件] 自定义触发器",
}

# 动作显示名称
ACTION_LABELS: dict[str, str] = {
    ActionType.NOTIFICATION: "弹出通知",
    ActionType.PLAY_SOUND:   "播放音效",
    ActionType.RUN_COMMAND:  "运行命令",
    ActionType.OPEN_URL:     "打开网址",
    ActionType.LOG:          "写入日志",
    ActionType.SHOW_WINDOW:  "显示主窗口",
    ActionType.HIDE_WINDOW:  "隐藏主窗口",
    ActionType.START_FOCUS:  "开始专注",
    ActionType.STOP_FOCUS:   "停止专注",
    ActionType.WAIT:         "等待（延迟）",
}

# 需要参数的触发器字段定义：[(key, label, kind, default, extra)]
TRIGGER_PARAM_DEFS: dict[str, list] = {
    TriggerType.TIME_OF_DAY: [
        ("hour",   "小时（0–23）", "spin", 8,  (0, 23)),
        ("minute", "分钟（0–59）", "spin", 0,  (0, 59)),
    ],
    TriggerType.SCHEDULE_INTERVAL: [
        ("interval_minutes", "间隔分钟数", "spin", 60, (1, 1440)),
    ],
    TriggerType.ALARM_FIRED: [
        ("alarm_id", "闹钟 ID（可选，留空则匹配所有）", "text", "", "填写闹钟 ID 或留空"),
    ],
    TriggerType.PLUGIN: [
        ("trigger_id", "触发器", "combo", "", "请选择插件触发器…"),
    ],
}

# 需要参数的动作字段定义
ACTION_PARAM_DEFS: dict[str, list] = {
    ActionType.NOTIFICATION: [
        ("title",   "通知标题", "text", "小树时钟", "通知标题"),
        ("content", "通知内容", "text", "",        "通知内容"),
    ],
    ActionType.PLAY_SOUND: [
        ("path", "音频文件路径", "text", "", "例如：C:/sounds/alert.wav"),
    ],
    ActionType.RUN_COMMAND: [
        ("command", "命令", "text", "", "例如：notepad.exe"),
    ],
    ActionType.OPEN_URL: [
        ("url", "网址", "text", "", "例如：https://example.com"),
    ],
    ActionType.LOG: [
        ("message", "日志内容", "text", "", "要写入日志的文字"),
    ],
    ActionType.WAIT: [
        ("seconds", "等待秒数", "spin", 1, (1, 3600)),
    ],
}


def _make_param_form(defs: list) -> tuple[QWidget, dict]:
    """根据字段定义生成参数表单，返回 (widget, {key: input_widget})"""
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 4, 0, 0)
    layout.setSpacing(6)
    inputs: dict = {}

    for item in defs:
        key, label, kind, default, extra = item
        row = QHBoxLayout()
        row.addWidget(BodyLabel(f"{label}："))
        if kind == "spin":
            spin = SpinBox()
            spin.setRange(*extra)
            spin.setValue(int(default))
            row.addWidget(spin)
            inputs[key] = spin
        elif kind == "combo":
            combo = ComboBox()
            combo.setPlaceholderText(str(extra) if extra else "请选择…")
            row.addWidget(combo, 1)
            inputs[key] = combo
        else:
            edit = LineEdit()
            edit.setPlaceholderText(str(extra))
            edit.setText(str(default))
            row.addWidget(edit, 1)
            inputs[key] = edit
        layout.addLayout(row)

    return w, inputs


def _read_param_form(inputs: dict) -> dict:
    params = {}
    for key, widget in inputs.items():
        if isinstance(widget, SpinBox):
            params[key] = widget.value()
        elif isinstance(widget, ComboBox):
            data = widget.currentData()
            params[key] = data if data is not None else ""
        else:
            params[key] = widget.text().strip()
    return params


def _fill_param_form(inputs: dict, params: dict) -> None:
    for key, widget in inputs.items():
        val = params.get(key)
        if val is None:
            continue
        if isinstance(widget, SpinBox):
            widget.setValue(int(val))
        elif isinstance(widget, ComboBox):
            idx = widget.findData(str(val))
            if idx >= 0:
                widget.setCurrentIndex(idx)
            elif str(val):
                # 触发器已不可用（插件已卸载），添加占位项
                widget.addItem(f"⚠ 未知触发器（{val}）", userData=str(val))
                widget.setCurrentIndex(widget.count() - 1)
        else:
            widget.setText(str(val))


# ────────────────────────────────────────── _DragHandle ──────────────────── #

class _DragHandle(QLabel):
    """动作卡片左侧拖拽把手"""

    def __init__(self, card: "ActionCard", parent=None):
        super().__init__("⠿", parent)
        self._card = card
        self._drag_start = None
        self.setFixedWidth(18)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setStyleSheet("color: #999; font-size: 18px; letter-spacing: 1px;")
        self.setToolTip("拖拽调整顺序")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()

    def mouseMoveEvent(self, event) -> None:
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._drag_start is not None:
            if (event.pos() - self._drag_start).manhattanLength() > 6:
                self._start_drag()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_start = None

    def _start_drag(self) -> None:
        container = self._card.parent()
        if not hasattr(container, "find_card_index"):
            return
        idx = container.find_card_index(self._card)
        if idx < 0:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-action-index", str(idx).encode())
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)


# ────────────────────────────────────────── ActionListWidget ─────────────── #

class ActionListWidget(QWidget):
    """带拖拽排序的动作卡片容器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._cards: list[ActionCard] = []
        self._drop_index: int = -1

    # ── 公开接口 ─────────────────────────────────────────────────── #

    def add_card(self, card: "ActionCard") -> None:
        self._cards.append(card)
        self._layout.addWidget(card)

    def remove_card(self, card: "ActionCard") -> None:
        if card in self._cards:
            self._cards.remove(card)
        self._layout.removeWidget(card)
        card.hide()

    def clear_cards(self) -> None:
        for card in self._cards:
            self._layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

    def cards(self) -> "list[ActionCard]":
        return list(self._cards)

    def find_card_index(self, card: "ActionCard") -> int:
        try:
            return self._cards.index(card)
        except ValueError:
            return -1

    # ── 拖拽事件 ─────────────────────────────────────────────────── #

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-action-index"):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-action-index"):
            event.acceptProposedAction()
            self._drop_index = self._pos_to_index(event.position().y())
            self.update()

    def dragLeaveEvent(self, event) -> None:
        self._drop_index = -1
        self.update()

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat("application/x-action-index"):
            src = int(bytes(event.mimeData().data("application/x-action-index")).decode())
            dst = self._pos_to_index(event.position().y())
            self._move_card(src, dst)
            event.acceptProposedAction()
        self._drop_index = -1
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_index < 0 or not self._cards:
            return
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#0078d4"), 2))
        y = self._indicator_y(self._drop_index)
        painter.drawLine(0, y, self.width(), y)

    # ── 内部辅助 ─────────────────────────────────────────────────── #

    def _pos_to_index(self, y: float) -> int:
        for i, card in enumerate(self._cards):
            if y < card.geometry().center().y():
                return i
        return len(self._cards)

    def _indicator_y(self, index: int) -> int:
        if index <= 0 or not self._cards:
            return 0
        if index >= len(self._cards):
            last = self._cards[-1]
            return last.y() + last.height()
        prev = self._cards[index - 1]
        curr = self._cards[index]
        return (prev.y() + prev.height() + curr.y()) // 2

    def _move_card(self, src: int, dst: int) -> None:
        if src == dst or src < 0 or src >= len(self._cards):
            return
        card = self._cards.pop(src)
        if dst > src:
            dst -= 1
        self._cards.insert(dst, card)
        for c in self._cards:
            self._layout.removeWidget(c)
        for c in self._cards:
            self._layout.addWidget(c)


# ─────────────────────────────────────────────── ActionCard ──────────────── #

class ActionCard(CardWidget):
    """单个动作配置卡片（含类型选择 + 动态参数 + 删除按钮）"""

    deleteRequested = Signal()

    def __init__(self, action: Optional[ActionConfig] = None,
                 plugin_api=None, parent=None):
        super().__init__(parent)
        self.setObjectName("actionCard")
        self._plugin_api = plugin_api

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 8, 12, 8)
        outer.setSpacing(6)

        # 顶栏：拖拽把手 + 类型选择 + 删除
        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        self._handle = _DragHandle(self)
        top_row.addWidget(self._handle)
        top_row.addWidget(BodyLabel("动作类型："))
        self._type_combo = ComboBox()
        for atype, alabel in ACTION_LABELS.items():
            self._type_combo.addItem(alabel, userData=atype)
        # 追加插件注册的自定义动作
        if plugin_api is not None:
            for pid, _ in plugin_api.list_custom_actions().items():
                self._type_combo.addItem(f"[插件] {pid}", userData=pid)
        top_row.addWidget(self._type_combo, 1)
        del_btn = ToolButton(FIF.DELETE)
        del_btn.clicked.connect(self.deleteRequested)
        top_row.addWidget(del_btn)
        outer.addLayout(top_row)

        # 动态参数区（QStackedWidget）
        self._param_stack = QStackedWidget()
        self._param_stack.setVisible(False)
        outer.addWidget(self._param_stack)

        self._empty_page = QWidget()
        self._param_stack.addWidget(self._empty_page)

        self._param_pages: dict[str, tuple[QWidget, dict]] = {}
        for atype, defs in ACTION_PARAM_DEFS.items():
            page, inputs = _make_param_form(defs)
            self._param_pages[atype] = (page, inputs)
            self._param_stack.addWidget(page)

        self._type_combo.currentIndexChanged.connect(self._on_type_changed)

        if action:
            # 若是未知类型（旧插件动作），尝试动态加入 combo
            if self._type_combo.findData(action.type) < 0:
                self._type_combo.addItem(f"[插件] {action.type}", userData=action.type)
            idx = self._type_combo.findData(action.type)
            if idx >= 0:
                self._type_combo.setCurrentIndex(idx)
            # 无论 index 是否改变都强制刷新参数区（修复 index=0 时不刷新的 bug）
            self._on_type_changed()
            _, inputs = self._param_pages.get(action.type, (None, {}))
            if inputs:
                _fill_param_form(inputs, action.params)
        else:
            self._on_type_changed()

    @Slot()
    def _on_type_changed(self) -> None:
        atype = self._type_combo.currentData()
        if atype in self._param_pages:
            page, _ = self._param_pages[atype]
            self._param_stack.setCurrentWidget(page)
            self._param_stack.setVisible(True)
        else:
            self._param_stack.setCurrentWidget(self._empty_page)
            self._param_stack.setVisible(False)

    def get_action(self) -> ActionConfig:
        atype = self._type_combo.currentData()
        _, inputs = self._param_pages.get(atype, (None, {}))
        params = _read_param_form(inputs) if inputs else {}
        return ActionConfig(type=atype, params=params)

    def refresh_plugin_actions(self, plugin_api) -> None:
        """插件扫描完成后刷新自定义动作列表"""
        self._plugin_api = plugin_api
        current = self._type_combo.currentData()
        # 移除旧的插件条目（userData 不在 ACTION_LABELS 中）
        built_in = set(ACTION_LABELS.keys())
        i = 0
        while i < self._type_combo.count():
            if self._type_combo.itemData(i) not in built_in:
                self._type_combo.removeItem(i)
            else:
                i += 1
        # 重新加入
        for pid in plugin_api.list_custom_actions():
            self._type_combo.addItem(f"[插件] {pid}", userData=pid)
        # 恢复之前的选择
        idx = self._type_combo.findData(current)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)


# ─────────────────────────────────────────────── TriggerParamsWidget ──────── #

class TriggerParamsWidget(QWidget):
    """根据触发器类型动态显示/隐藏参数配置"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        self._empty_page = QWidget()
        self._stack.addWidget(self._empty_page)

        self._pages: dict[str, tuple[QWidget, dict]] = {}
        for ttype, defs in TRIGGER_PARAM_DEFS.items():
            page, inputs = _make_param_form(defs)
            self._pages[ttype] = (page, inputs)
            self._stack.addWidget(page)

    def set_trigger_type(self, ttype: str) -> None:
        if ttype in self._pages:
            page, _ = self._pages[ttype]
            self._stack.setCurrentWidget(page)
            self.setVisible(True)
        else:
            self._stack.setCurrentWidget(self._empty_page)
            self.setVisible(False)

    def get_params(self, ttype: str) -> dict:
        _, inputs = self._pages.get(ttype, (None, {}))
        return _read_param_form(inputs) if inputs else {}

    def fill_params(self, ttype: str, params: dict) -> None:
        _, inputs = self._pages.get(ttype, (None, {}))
        if inputs:
            _fill_param_form(inputs, params)

    def refresh_plugin_triggers(self, plugin_api) -> None:
        """插件扫描完成后刷新 PLUGIN 触发器下拉列表并更新全局名称缓存"""
        global _plugin_trigger_names
        triggers = plugin_api.list_custom_triggers()  # {tid: {"name", "description"}}
        _plugin_trigger_names = {tid: info["name"] for tid, info in triggers.items()}

        page_data = self._pages.get(TriggerType.PLUGIN)
        if not page_data:
            return
        _, inputs = page_data
        combo = inputs.get("trigger_id")
        if not isinstance(combo, ComboBox):
            return

        current_data = combo.currentData()
        combo.clear()
        for tid, info in triggers.items():
            name = info["name"]
            display = f"{name}（{tid}）" if name != tid else tid
            combo.addItem(display, userData=tid)

        # 恢复之前的选择（或添加未知占位项）
        if current_data:
            idx = combo.findData(current_data)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                combo.addItem(f"⚠ 未知触发器（{current_data}）", userData=current_data)
                combo.setCurrentIndex(combo.count() - 1)


# ─────────────────────────────────────────────── RuleCard ────────────────── #

class RuleCard(CardWidget):
    editRequested   = Signal(str)
    deleteRequested = Signal(str)
    runRequested    = Signal(str)

    def __init__(self, rule: AutomationRule, parent=None):
        super().__init__(parent)
        self.rule_id = rule.id

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)

        info = QVBoxLayout()
        self.name_lbl   = StrongBodyLabel(rule.name)
        self.detail_lbl = CaptionLabel(self._detail_text(rule))
        info.addWidget(self.name_lbl)
        info.addWidget(self.detail_lbl)

        self.switch = SwitchButton()
        self.switch.setChecked(rule.enabled)
        self.run_btn  = ToolButton(FIF.PLAY)
        self.edit_btn = ToolButton(FIF.EDIT)
        self.del_btn  = ToolButton(FIF.DELETE)
        self.run_btn.setToolTip("立即手动执行（测试）")

        self.edit_btn.clicked.connect(lambda: self.editRequested.emit(self.rule_id))
        self.del_btn.clicked.connect(lambda: self.deleteRequested.emit(self.rule_id))
        self.run_btn.clicked.connect(lambda: self.runRequested.emit(self.rule_id))

        row.addLayout(info, 1)
        row.addWidget(self.switch)
        row.addWidget(self.run_btn)
        row.addWidget(self.edit_btn)
        row.addWidget(self.del_btn)
        self.setFixedHeight(76)

    @staticmethod
    def _detail_text(rule: AutomationRule) -> str:
        if rule.trigger.type == TriggerType.PLUGIN:
            tid = rule.trigger.params.get("trigger_id", "")
            if tid and tid in _plugin_trigger_names:
                trig = f"[插件] {_plugin_trigger_names[tid]}"
            elif tid:
                trig = f"[插件] 未知触发器（{tid}）"
            else:
                trig = TRIGGER_LABELS[TriggerType.PLUGIN]
        else:
            trig = TRIGGER_LABELS.get(rule.trigger.type, rule.trigger.type)
        act_labels = [ACTION_LABELS.get(a.type, a.type) for a in rule.actions]
        acts = "、".join(act_labels) if act_labels else "（无动作）"
        return f"触发：{trig}  →  动作：{acts}"

    def refresh(self, rule: AutomationRule) -> None:
        self.name_lbl.setText(rule.name)
        self.detail_lbl.setText(self._detail_text(rule))
        self.switch.setChecked(rule.enabled)


# ─────────────────────────────────────────────── AutomationListPage ──────── #

class AutomationListPage(SmoothScrollArea):
    """规则列表页：显示所有规则卡片"""

    editRequested  = Signal(str)   # rule_id
    ruleDeleted    = Signal(str)   # rule_id（删除后通知外部关闭对应 Tab）

    def __init__(self, engine: AutomationEngine, parent=None):
        super().__init__(parent)
        self.setObjectName("automationListPage")
        self._engine = engine
        self._store: AutomationStore = engine._store
        self._cards: dict[str, RuleCard] = {}

        container = QWidget()
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(0, 0, 0, 16)
        self._layout.setSpacing(8)

        # 工具栏
        bar = QHBoxLayout()
        self._count_lbl = CaptionLabel("共 0 条规则")
        add_btn = PushButton(FIF.ADD, "新建规则")
        add_btn.clicked.connect(self._on_add)
        bar.addWidget(self._count_lbl)
        bar.addStretch()
        bar.addWidget(add_btn)
        self._layout.addLayout(bar)

        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(6)
        self._layout.addLayout(self._cards_layout)
        self._layout.addStretch()

        self.setWidget(container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._load_cards()

    def _load_cards(self) -> None:
        for rule in self._store.all():
            self._append_card(rule)
        self._update_count()

    def _append_card(self, rule: AutomationRule) -> None:
        card = RuleCard(rule)
        card.switch.checkedChanged.connect(
            lambda checked, rid=rule.id: self._store.set_enabled(rid, checked)
        )
        card.editRequested.connect(self.editRequested)
        card.deleteRequested.connect(self._on_delete)
        card.runRequested.connect(self._on_run)
        self._cards[rule.id] = card
        self._cards_layout.addWidget(card)

    def add_rule_from_engine(self, rule: AutomationRule) -> None:
        """编辑页 + 按钮新建规则后同步到列表（不触发 editRequested）"""
        self._append_card(rule)
        self._update_count()

    def refresh_card(self, rule: AutomationRule) -> None:
        card = self._cards.get(rule.id)
        if card:
            card.refresh(rule)

    def _update_count(self) -> None:
        n = len(self._cards)
        self._count_lbl.setText(f"共 {n} 条规则")

    @Slot()
    def _on_add(self) -> None:
        rule = AutomationRule()
        self._store.add(rule)
        self._append_card(rule)
        self._update_count()
        self.editRequested.emit(rule.id)

    def _on_delete(self, rule_id: str) -> None:
        rule = self._store.get(rule_id)
        name = rule.name if rule else rule_id
        dlg = MessageBox("确认删除", f"确定要删除规则「{name}」吗？", self.window())
        dlg.yesButton.setText("删除")
        dlg.cancelButton.setText("取消")
        if dlg.exec():
            self._store.remove(rule_id)
            card = self._cards.pop(rule_id, None)
            if card:
                self._cards_layout.removeWidget(card)
                card.deleteLater()
            self._update_count()
            self.ruleDeleted.emit(rule_id)

    def _on_run(self, rule_id: str) -> None:
        rule = self._store.get(rule_id)
        if rule:
            self._engine.execute_rule_by_id(rule_id)
            InfoBar.success("已执行", f"规则「{rule.name}」手动执行完毕",
                            parent=self.window(),
                            position=InfoBarPosition.TOP_RIGHT, duration=2000)


# ─────────────────────────────────────────────── AutomationEditPage ──────── #

class AutomationEditPage(SmoothScrollArea):
    """规则编辑页：包含触发器、多动作配置的完整表单"""

    saved = Signal(str)   # 保存后发出 rule_id

    def __init__(self, store: AutomationStore, plugin_api=None, parent=None):
        super().__init__(parent)
        self.setObjectName("automationEditPage")
        self._store      = store
        self._plugin_api = plugin_api
        self._rule_id: Optional[str] = None
        self._action_cards: list[ActionCard] = []
        self._action_list = ActionListWidget()

        self._container = QWidget()
        self._main_layout = QVBoxLayout(self._container)
        self._main_layout.setContentsMargins(0, 0, 0, 24)
        self._main_layout.setSpacing(12)

        # ── 无选中占位符 ──────────────────────────────────────────────
        self._placeholder = QWidget()
        ph_layout = QVBoxLayout(self._placeholder)
        ph_layout.setAlignment(Qt.AlignCenter)
        ph_icon = BodyLabel("📋")
        ph_icon.setAlignment(Qt.AlignCenter)
        ph_icon.setStyleSheet("font-size: 36px;")
        ph_text = StrongBodyLabel("请先在「规则列表」中选择或新建一条规则")
        ph_text.setAlignment(Qt.AlignCenter)
        ph_sub = CaptionLabel("点击规则卡片上的「编辑」按钮即可开始编辑")
        ph_sub.setAlignment(Qt.AlignCenter)
        ph_layout.addStretch()
        ph_layout.addWidget(ph_icon)
        ph_layout.addSpacing(8)
        ph_layout.addWidget(ph_text)
        ph_layout.addWidget(ph_sub)
        ph_layout.addStretch()
        self._main_layout.addWidget(self._placeholder)

        # ── 编辑表单 ─────────────────────────────────────────────────
        self._form = QWidget()
        self._form.setVisible(False)
        form_layout = QVBoxLayout(self._form)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(12)

        # 基本信息卡
        basic_card = CardWidget()
        basic_inner = QVBoxLayout(basic_card)
        basic_inner.setContentsMargins(16, 12, 16, 12)
        basic_inner.setSpacing(8)
        basic_inner.addWidget(StrongBodyLabel("基本信息"))

        name_row = QHBoxLayout()
        name_row.addWidget(BodyLabel("名称："))
        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText("规则名称")
        name_row.addWidget(self._name_edit, 1)

        enable_row = QHBoxLayout()
        enable_row.addWidget(BodyLabel("启用规则："))
        self._enable_sw = SwitchButton()
        self._enable_sw.setChecked(True)
        enable_row.addWidget(self._enable_sw)
        enable_row.addStretch()

        desc_row = QHBoxLayout()
        desc_row.addWidget(BodyLabel("描述："))
        self._desc_edit = LineEdit()
        self._desc_edit.setPlaceholderText("可选描述")
        desc_row.addWidget(self._desc_edit, 1)

        basic_inner.addLayout(name_row)
        basic_inner.addLayout(enable_row)
        basic_inner.addLayout(desc_row)

        # 触发器卡
        trig_card = CardWidget()
        trig_inner = QVBoxLayout(trig_card)
        trig_inner.setContentsMargins(16, 12, 16, 12)
        trig_inner.setSpacing(8)
        trig_inner.addWidget(StrongBodyLabel("触发器"))

        trig_type_row = QHBoxLayout()
        trig_type_row.addWidget(BodyLabel("触发方式："))
        self._trig_combo = ComboBox()
        for ttype, tlabel in TRIGGER_LABELS.items():
            self._trig_combo.addItem(tlabel, userData=ttype)
        trig_type_row.addWidget(self._trig_combo, 1)
        trig_inner.addLayout(trig_type_row)

        self._trig_params = TriggerParamsWidget()
        trig_inner.addWidget(self._trig_params)
        self._trig_combo.currentIndexChanged.connect(self._on_trig_type_changed)

        # 动作列表卡
        actions_card = CardWidget()
        self._actions_inner = QVBoxLayout(actions_card)
        self._actions_inner.setContentsMargins(16, 12, 16, 12)
        self._actions_inner.setSpacing(8)

        actions_header = QHBoxLayout()
        actions_header.addWidget(StrongBodyLabel("动作列表"))
        actions_header.addStretch()
        add_action_btn = PushButton(FIF.ADD, "添加动作")
        add_action_btn.clicked.connect(self._on_add_action)
        actions_header.addWidget(add_action_btn)
        self._actions_inner.addLayout(actions_header)

        self._action_list.setParent(actions_card)
        self._actions_inner.addWidget(self._action_list)

        self._no_action_lbl = CaptionLabel("暂无动作 —— 点击「添加动作」来添加")
        self._no_action_lbl.setAlignment(Qt.AlignCenter)
        self._actions_inner.addWidget(self._no_action_lbl)

        # 保存按钮
        save_row = QHBoxLayout()
        save_row.addStretch()
        self._save_btn = PrimaryPushButton(FIF.SAVE, "保存规则")
        self._save_btn.clicked.connect(self._on_save)
        save_row.addWidget(self._save_btn)

        form_layout.addWidget(basic_card)
        form_layout.addWidget(trig_card)
        form_layout.addWidget(actions_card)
        form_layout.addLayout(save_row)

        self._main_layout.addWidget(self._form)

        self.setWidget(self._container)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._on_trig_type_changed()

    # ── 加载规则到表单 ───────────────────────────────────────────────── #

    def load_rule(self, rule_id: str) -> None:
        rule = self._store.get(rule_id)
        if rule is None:
            self.clear_selection()
            return

        self._rule_id = rule_id
        self._placeholder.setVisible(False)
        self._form.setVisible(True)

        self._name_edit.setText(rule.name)
        self._desc_edit.setText(rule.description)
        self._enable_sw.setChecked(rule.enabled)

        idx = self._trig_combo.findData(rule.trigger.type)
        if idx >= 0:
            self._trig_combo.setCurrentIndex(idx)
        self._trig_params.set_trigger_type(rule.trigger.type)
        self._trig_params.fill_params(rule.trigger.type, rule.trigger.params)

        self._clear_action_cards()
        for action in rule.actions:
            self._add_action_card(action)
        self._update_no_action_label()

    def clear_selection(self) -> None:
        self._rule_id = None
        self._placeholder.setVisible(True)
        self._form.setVisible(False)

    # ── 内部 ─────────────────────────────────────────────────────────── #

    @Slot()
    def _on_trig_type_changed(self) -> None:
        ttype = self._trig_combo.currentData() or TriggerType.NONE
        self._trig_params.set_trigger_type(ttype)

    def _clear_action_cards(self) -> None:
        self._action_list.clear_cards()
        self._action_cards.clear()

    @Slot()
    def _on_add_action(self) -> None:
        self._add_action_card()
        self._update_no_action_label()

    def _add_action_card(self, action: Optional[ActionConfig] = None) -> ActionCard:
        card = ActionCard(action, plugin_api=self._plugin_api)
        card.deleteRequested.connect(lambda c=card: self._on_remove_action(c))
        self._action_cards.append(card)
        self._action_list.add_card(card)
        return card

    def _on_remove_action(self, card: ActionCard) -> None:
        if card in self._action_cards:
            self._action_cards.remove(card)
        self._action_list.remove_card(card)
        card.deleteLater()
        self._update_no_action_label()

    def _update_no_action_label(self) -> None:
        self._no_action_lbl.setVisible(len(self._action_list.cards()) == 0)

    @Slot()
    def _on_save(self) -> None:
        if not self._rule_id:
            InfoBar.warning("未选择规则", "请先选择一条规则再保存",
                            parent=self.window(),
                            position=InfoBarPosition.TOP_RIGHT, duration=2000)
            return

        rule = self._store.get(self._rule_id)
        if rule is None:
            return

        rule.name        = self._name_edit.text().strip() or "新规则"
        rule.description = self._desc_edit.text().strip()
        rule.enabled     = self._enable_sw.isChecked()

        ttype = self._trig_combo.currentData()
        t_params = self._trig_params.get_params(ttype)
        rule.trigger = TriggerConfig(type=ttype, params=t_params)
        rule.actions = [card.get_action() for card in self._action_list.cards()]

        self._store.update(rule)
        self.saved.emit(rule.id)
        InfoBar.success("已保存", f"规则「{rule.name}」保存成功",
                        parent=self.window(),
                        position=InfoBarPosition.TOP_RIGHT, duration=2000)

    def refresh_plugin_triggers(self, plugin_api) -> None:
        """刷新当前编辑页的触发器下拉列表"""
        self._plugin_api = plugin_api
        self._trig_params.refresh_plugin_triggers(plugin_api)


# ─────────────────────────────────────────────── EditTabsPage ───────────── #

class EditTabsPage(QWidget):
    """多标签编辑页 —— 每条规则在独立 Tab 中编辑，支持同时编辑多条"""

    ruleSaved = Signal(str)   # rule_id
    ruleAdded = Signal(str)   # 通过 + 按钮新建的 rule_id

    def __init__(self, store: AutomationStore, plugin_api=None, parent=None):
        super().__init__(parent)
        self._store = store
        self._plugin_api = plugin_api
        self._tab_pages: dict[str, AutomationEditPage] = {}   # rule_id -> page

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 占位符（无 Tab 时显示） ────────────────────────────────
        self._placeholder = QWidget()
        ph_layout = QVBoxLayout(self._placeholder)
        ph_layout.setAlignment(Qt.AlignCenter)
        ph_icon = BodyLabel("📋")
        ph_icon.setAlignment(Qt.AlignCenter)
        ph_icon.setStyleSheet("font-size: 36px;")
        ph_text = StrongBodyLabel("请先在「规则列表」中打开一条规则")
        ph_text.setAlignment(Qt.AlignCenter)
        ph_sub = CaptionLabel("在列表点「编辑」打开已有规则；点击上方 + 新建规则")
        ph_sub.setAlignment(Qt.AlignCenter)
        ph_layout.addStretch()
        ph_layout.addWidget(ph_icon)
        ph_layout.addSpacing(8)
        ph_layout.addWidget(ph_text)
        ph_layout.addWidget(ph_sub)
        ph_layout.addStretch()
        outer.addWidget(self._placeholder)

        # ── TabWidget（自带 TabBar + StackedWidget 联动） ─────────
        self._tab_widget = TabWidget(self)
        self._tab_widget.setMovable(True)
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setScrollable(True)
        self._tab_widget.setTabMaximumWidth(240)
        self._tab_widget.setVisible(False)
        outer.addWidget(self._tab_widget, 1)

        self._tab_widget.tabAddRequested.connect(self._on_add_tab)
        self._tab_widget.tabCloseRequested.connect(self._on_close_tab)

    # ── 公开接口 ─────────────────────────────────────────────────── #

    def open_rule(self, rule_id: str) -> None:
        """打开规则编辑 Tab（已存在则切换到该 Tab）"""
        if rule_id in self._tab_pages:
            idx = self._index_of(rule_id)
            if idx >= 0:
                self._tab_widget.setCurrentIndex(idx)
            return

        rule = self._store.get(rule_id)
        if rule is None:
            return

        page = AutomationEditPage(self._store, plugin_api=self._plugin_api)
        page.load_rule(rule_id)
        # 填充当前已注册的插件触发器下拉（在 load_rule 之后调用，确保 fill_params 能选中正确项）
        if self._plugin_api is not None:
            page.refresh_plugin_triggers(self._plugin_api)
        page.saved.connect(lambda rid: self._on_page_saved(rid))

        self._tab_pages[rule_id] = page
        self._tab_widget.addTab(page, rule.name, routeKey=rule_id)
        idx = self._index_of(rule_id)
        if idx >= 0:
            self._tab_widget.setCurrentIndex(idx)

        self._placeholder.setVisible(False)
        self._tab_widget.setVisible(True)

    def close_rule(self, rule_id: str) -> None:
        """关闭指定规则的 Tab（规则被删除时调用）"""
        idx = self._index_of(rule_id)
        if idx >= 0:
            self._do_close(idx, rule_id)

    def refresh_rule(self, rule_id: str) -> None:
        """规则名称变更后刷新 Tab 标题"""
        rule = self._store.get(rule_id)
        if not rule:
            return
        idx = self._index_of(rule_id)
        if idx >= 0:
            self._tab_widget.setTabText(idx, rule.name)

    # ── 内部槽 ───────────────────────────────────────────────────── #

    @Slot()
    def _on_add_tab(self) -> None:
        """TabBar 右侧 + 按钮：新建规则并在新 Tab 中打开"""
        rule = AutomationRule()
        self._store.add(rule)
        self.open_rule(rule.id)
        self.ruleAdded.emit(rule.id)

    def refresh_plugin_actions(self, plugin_api) -> None:
        """插件扫描完成后，刷新所有打开的编辑页的动作下拉列表"""
        self._plugin_api = plugin_api
        for page in self._tab_pages.values():
            page._plugin_api = plugin_api
            for card in page._action_list.cards():
                card.refresh_plugin_actions(plugin_api)

    def refresh_plugin_triggers(self, plugin_api) -> None:
        """插件扫描完成后，刷新所有打开的编辑页的触发器下拉列表"""
        self._plugin_api = plugin_api
        for page in self._tab_pages.values():
            page.refresh_plugin_triggers(plugin_api)

    @Slot(int)
    def _on_close_tab(self, index: int) -> None:
        item = self._tab_widget.tabBar.tabItem(index)
        if item:
            self._do_close(index, item.routeKey())

    def _do_close(self, index: int, rule_id: str) -> None:
        page = self._tab_pages.pop(rule_id, None)
        self._tab_widget.removeTab(index)
        if page:
            page.deleteLater()
        if self._tab_widget.count() == 0:
            self._tab_widget.setVisible(False)
            self._placeholder.setVisible(True)

    def _index_of(self, rule_id: str) -> int:
        """返回 rule_id 对应的 Tab 下标，找不到返回 -1"""
        for i in range(self._tab_widget.count()):
            item = self._tab_widget.tabBar.tabItem(i)
            if item and item.routeKey() == rule_id:
                return i
        return -1

    def _on_page_saved(self, rule_id: str) -> None:
        self.refresh_rule(rule_id)
        self.ruleSaved.emit(rule_id)


# ─────────────────────────────────────────────── AutomationView ──────────── #

class AutomationView(QWidget):
    """自动化主视图 —— Pivot 切换「规则列表」/「编辑标签」"""

    def __init__(self, engine: AutomationEngine, plugin_api=None, parent=None):
        super().__init__(parent)
        self.setObjectName("automationView")
        self._engine     = engine
        self._store      = engine._store
        self._plugin_api = plugin_api

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(0)

        title_row = QHBoxLayout()
        title_row.addWidget(TitleLabel("自动化"))
        title_row.addStretch()
        outer.addLayout(title_row)
        outer.addSpacing(8)

        # Pivot 导航栏
        self._pivot = Pivot()
        outer.addWidget(self._pivot, 0, Qt.AlignLeft)

        # 页面容器
        self._stacked = QStackedWidget()
        outer.addWidget(self._stacked, 1)

        # ── 规则列表页 ────────────────────────────────────────────
        self._list_page = AutomationListPage(engine)
        self._list_page.editRequested.connect(self._navigate_to_edit)
        self._list_page.ruleDeleted.connect(self._on_rule_deleted)
        self._stacked.addWidget(self._list_page)
        self._pivot.addItem(
            routeKey="listPage",
            text="规则列表",
            onClick=lambda: self._stacked.setCurrentWidget(self._list_page),
        )

        # ── 多标签编辑页 ──────────────────────────────────────────
        self._edit_tabs = EditTabsPage(self._store, plugin_api=plugin_api)
        self._edit_tabs.ruleSaved.connect(self._on_rule_saved)
        self._edit_tabs.ruleAdded.connect(self._on_tab_rule_added)
        self._stacked.addWidget(self._edit_tabs)
        self._pivot.addItem(
            routeKey="editPage",
            text="编辑标签",
            onClick=lambda: self._stacked.setCurrentWidget(self._edit_tabs),
        )

        self._stacked.currentChanged.connect(self._on_page_changed)
        self._stacked.setCurrentWidget(self._list_page)
        self._pivot.setCurrentItem("listPage")

    def _navigate_to_edit(self, rule_id: str) -> None:
        self._edit_tabs.open_rule(rule_id)
        self._stacked.setCurrentWidget(self._edit_tabs)
        self._pivot.setCurrentItem("editPage")

    @Slot(int)
    def _on_page_changed(self, index: int) -> None:
        widget = self._stacked.widget(index)
        if widget is self._list_page:
            self._pivot.setCurrentItem("listPage")
        elif widget is self._edit_tabs:
            self._pivot.setCurrentItem("editPage")

    def _on_rule_saved(self, rule_id: str) -> None:
        rule = self._store.get(rule_id)
        if rule:
            self._list_page.refresh_card(rule)

    def _on_tab_rule_added(self, rule_id: str) -> None:
        """编辑页 + 按钮新建规则后，同步到规则列表"""
        rule = self._store.get(rule_id)
        if rule:
            self._list_page.add_rule_from_engine(rule)

    def _on_rule_deleted(self, rule_id: str) -> None:
        self._edit_tabs.close_rule(rule_id)

    def refresh_plugin_actions(self, plugin_api) -> None:
        """插件加载/卸载后更新动作下拉列表、触发器列表及规则列表显示"""
        self._plugin_api = plugin_api
        self._edit_tabs.refresh_plugin_actions(plugin_api)
        # 刷新触发器名称缓存和所有打开编辑页的触发器下拉
        self._edit_tabs.refresh_plugin_triggers(plugin_api)
        # 刷新列表页中所有规则卡片显示（触发器名称可能变化）
        for rule in self._store.all():
            self._list_page.refresh_card(rule)
