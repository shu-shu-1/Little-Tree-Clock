"""
自动化引擎

职责
----
1. 订阅宿主事件（闹钟触发、计时器结束、应用启动等）
2. 将事件映射到 AutomationRule 的触发条件
3. 依次执行规则绑定的每个 ActionConfig
4. 支持插件通过 PluginAPI 注册自定义触发器/动作
"""
from __future__ import annotations

import subprocess
import webbrowser
from datetime import datetime

from app.utils.logger import logger
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from app.models.automation_model import (
    AutomationRule, AutomationStore,
    TriggerType, ActionType, ActionConfig,
)

if TYPE_CHECKING:
    from app.plugins.base_plugin import PluginAPI
    from app.services.notification_service import NotificationService


class AutomationEngine(QObject):
    """
    自动化引擎（在 App 中实例化一个即可）。

    使用方式::

        engine = AutomationEngine(store, plugin_api, notif_service)
        engine.fire_event(TriggerType.APP_STARTUP)
        engine.fire_event(TriggerType.ALARM_FIRED, alarm_id="xxx")
    """

    ruleExecuted = Signal(str, bool)   # rule_id, success

    def __init__(
        self,
        store: AutomationStore,
        plugin_api: Optional["PluginAPI"] = None,
        notif_service: Optional["NotificationService"] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._store        = store
        self._plugin_api   = plugin_api
        self._notif        = notif_service
        self._log: list[str] = []
        # 主窗口引用（由 MainWindow 注入，用于 show/hide 动作）
        self._main_window = None
        # 专注服务引用（由 MainWindow 注入，用于 start/stop_focus 动作）
        self._focus_service = None

        # 内置动作执行器注册表
        self._action_executors: Dict[str, Callable] = {
            ActionType.NOTIFICATION: self._exec_notification,
            ActionType.PLAY_SOUND:   self._exec_play_sound,
            ActionType.RUN_COMMAND:  self._exec_run_command,
            ActionType.OPEN_URL:     self._exec_open_url,
            ActionType.LOG:          self._exec_log,
            ActionType.SHOW_WINDOW:  self._exec_show_window,
            ActionType.HIDE_WINDOW:  self._exec_hide_window,
            ActionType.START_FOCUS:  self._exec_start_focus,
            ActionType.STOP_FOCUS:   self._exec_stop_focus,
        }

        # TIME_OF_DAY 触发器的轮询定时器（每分钟检查一次）
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._check_time_triggers)
        self._timer.start()

        # SCHEDULE_INTERVAL 触发器：记录每条规则上次触发时间（rule_id -> last epoch min）
        self._interval_last: Dict[str, int] = {}
        self._interval_timer = QTimer(self)
        self._interval_timer.setInterval(60_000)
        self._interval_timer.timeout.connect(self._check_interval_triggers)
        self._interval_timer.start()

    def set_main_window(self, window) -> None:
        """注入主窗口引用"""
        self._main_window = window

    def set_focus_service(self, svc) -> None:
        """注入专注服务引用"""
        self._focus_service = svc

    # ------------------------------------------------------------------ #
    # 公共事件投递口
    # ------------------------------------------------------------------ #

    @Slot()
    def fire_startup(self):
        self.fire_event(TriggerType.APP_STARTUP)

    def fire_event(self, trigger_type: TriggerType, **context: Any) -> None:
        """投递一个宿主事件；引擎会找到所有匹配的规则并执行。"""
        type_val = trigger_type.value if isinstance(trigger_type, TriggerType) else trigger_type
        # NONE 类型规则不响应任何自动事件
        if type_val in (TriggerType.NONE.value, TriggerType.MANUAL.value):
            return
        for rule in self._store.all():
            if not rule.enabled:
                continue
            if rule.trigger.type != type_val:
                continue
            if not self._match_trigger(rule, context):
                continue
            self._execute_rule(rule, context)

    def fire_plugin_trigger(self, trigger_id: str, **context: Any) -> None:
        """由插件调用：触发指定 ID 的自定义触发器，执行所有匹配的自动化规则。

        Parameters
        ----------
        trigger_id : str
            插件注册的触发器 ID，格式建议为 ``{plugin_id}.{name}``。
        context : Any
            传递给规则动作的上下文参数（可选）。
        """
        for rule in self._store.all():
            if not rule.enabled:
                continue
            if rule.trigger.type != TriggerType.PLUGIN:
                continue
            if rule.trigger.params.get("trigger_id", "") != trigger_id:
                continue
            self._execute_rule(rule, {"trigger_id": trigger_id, **context})

    def execute_rule_by_id(self, rule_id: str) -> bool:
        """不经触发器匹配，直接执行指定 ID 的规则（用于手动立即执行）。

        返回 True 表示规则存在并已尝试执行，False 表示规则不存在。
        """
        rule = self._store.get(rule_id)
        if rule is None:
            return False
        self._execute_rule(rule, {})
        return True

    # ------------------------------------------------------------------ #
    # 内部 — 触发器匹配
    # ------------------------------------------------------------------ #

    def _match_trigger(self, rule: AutomationRule, context: dict) -> bool:
        t = rule.trigger
        p = t.params

        if t.type == TriggerType.ALARM_FIRED:
            # 可选：只匹配特定闹钟 id
            alarm_id = p.get("alarm_id", "")
            return not alarm_id or alarm_id == context.get("alarm_id", "")

        if t.type == TriggerType.TIME_OF_DAY:
            now = datetime.now()
            return now.hour == p.get("hour", -1) and now.minute == p.get("minute", -1)

        if t.type == TriggerType.FOCUS_DISTRACTED:
            # 可选：只匹配特定自动化规则 id（由专注服务投递时携带）
            bound_rule_id = p.get("rule_id", "")
            ctx_rule_id   = context.get("rule_id", "")
            return not bound_rule_id or bound_rule_id == ctx_rule_id

        # 其他触发器无需额外匹配
        return True

    # ------------------------------------------------------------------ #
    # 内部 — 规则执行
    # ------------------------------------------------------------------ #

    def _execute_rule(self, rule: AutomationRule, context: dict) -> None:
        """顺序执行所有动作；遇到 WAIT 时用 QTimer 非阻塞延迟后继续"""
        from PySide6.QtCore import QTimer
        from app.models.automation_model import ActionType
        actions  = list(rule.actions)
        ok_ref   = [True]

        def run_from(index: int) -> None:
            while index < len(actions):
                action = actions[index]
                if action.type == ActionType.WAIT:
                    delay_ms = max(1, int(float(action.params.get("seconds", 1)) * 1000))
                    next_idx = index + 1
                    QTimer.singleShot(delay_ms, lambda i=next_idx: run_from(i))
                    return   # 挂起，等 QTimer 回调
                try:
                    self._execute_action(action, context)
                except Exception as exc:
                    ok_ref[0] = False
                    err_msg = f"[规则:{rule.name}] 动作 {action.type} 异常: {exc}"
                    self._append_log(err_msg)
                    logger.warning("[AutoEngine] {}", err_msg)
                    if self._notif:
                        self._notif.show(
                            "自动化执行出错",
                            f"规则「{rule.name}」动作 {action.type} 失败：{exc}",
                        )
                index += 1
            self.ruleExecuted.emit(rule.id, ok_ref[0])
            try:
                from app.events import EventBus, EventType
                EventBus.emit(EventType.AUTOMATION_TRIGGERED,
                              rule_id=rule.id, rule_name=rule.name, ok=ok_ref[0])
            except Exception:
                pass

        run_from(0)

    def _execute_action(self, action: ActionConfig, context: dict) -> None:
        exec_fn = self._action_executors.get(action.type)
        if exec_fn:
            exec_fn(action.params, context)
            return

        # 尝试从插件 API 取得自定义动作执行器
        if self._plugin_api:
            custom = self._plugin_api.get_action_executor(action.type)
            if custom:
                import inspect
                try:
                    sig = inspect.signature(custom)
                    n_params = len(sig.parameters)
                except (ValueError, TypeError):
                    n_params = 2  # 无法检测时假设接受两个参数
                if n_params >= 2:
                    custom(action.params, context)
                else:
                    custom(action.params)
                return

        self._append_log(f"未知动作类型: {action.type}")

    # ------------------------------------------------------------------ #
    # 内置动作执行器
    # ------------------------------------------------------------------ #

    def _exec_notification(self, params: dict, ctx: dict) -> None:
        title   = params.get("title", "小树时钟")
        content = params.get("content", "")
        if self._notif:
            self._notif.show(title, content)

    def _exec_play_sound(self, params: dict, ctx: dict) -> None:
        # 简单实现：交给 QSoundEffect / subprocess；可由插件覆盖
        path = params.get("path", "")
        if path:
            try:
                from PySide6.QtMultimedia import QSoundEffect
                from PySide6.QtCore import QUrl
                effect = QSoundEffect(self)
                effect.setSource(QUrl.fromLocalFile(path))
                effect.play()
            except Exception:
                pass

    def _exec_run_command(self, params: dict, ctx: dict) -> None:
        cmd = params.get("command", "")
        if cmd:
            subprocess.Popen(cmd, shell=True)

    def _exec_open_url(self, params: dict, ctx: dict) -> None:
        url = params.get("url", "")
        if url:
            webbrowser.open(url)

    def _exec_log(self, params: dict, ctx: dict) -> None:
        msg = params.get("message", "")
        self._append_log(f"[LOG] {msg}")

    def _exec_show_window(self, params: dict, ctx: dict) -> None:
        if self._main_window:
            self._main_window.show()
            self._main_window.raise_()
            self._main_window.activateWindow()

    def _exec_hide_window(self, params: dict, ctx: dict) -> None:
        if self._main_window:
            self._main_window.hide()

    def _exec_start_focus(self, params: dict, ctx: dict) -> None:
        if self._focus_service:
            try:
                self._focus_service.start()
            except Exception as exc:
                self._append_log(f"[START_FOCUS] 失败: {exc}")

    def _exec_stop_focus(self, params: dict, ctx: dict) -> None:
        if self._focus_service:
            try:
                self._focus_service.stop()
            except Exception as exc:
                self._append_log(f"[STOP_FOCUS] 失败: {exc}")

    # ------------------------------------------------------------------ #
    # TIME_OF_DAY 轮询
    # ------------------------------------------------------------------ #

    @Slot()
    def _check_time_triggers(self) -> None:
        self.fire_event(TriggerType.TIME_OF_DAY)

    # ------------------------------------------------------------------ #
    # SCHEDULE_INTERVAL 轮询
    # ------------------------------------------------------------------ #

    @Slot()
    def _check_interval_triggers(self) -> None:
        """每分钟检查 SCHEDULE_INTERVAL 类规则"""
        from datetime import datetime as _dt
        now_min = int(_dt.now().timestamp() // 60)

        for rule in self._store.all():
            if not rule.enabled:
                continue
            if rule.trigger.type != TriggerType.SCHEDULE_INTERVAL:
                continue
            interval = int(rule.trigger.params.get("interval_minutes", 60))
            if interval <= 0:
                continue
            last = self._interval_last.get(rule.id, None)
            if last is None:
                # 首次：记录当前时间，不立即触发
                self._interval_last[rule.id] = now_min
                continue
            if (now_min - last) >= interval:
                self._interval_last[rule.id] = now_min
                self._execute_rule(rule, {})

    # ------------------------------------------------------------------ #
    # 日志
    # ------------------------------------------------------------------ #

    def _append_log(self, msg: str) -> None:
        from datetime import datetime as _dt
        line = f"[{_dt.now():%H:%M:%S}] {msg}"
        self._log.append(line)
        if len(self._log) > 500:
            self._log = self._log[-500:]
        logger.debug("[AutoEngine] {}", msg)

    def get_log(self) -> list[str]:
        return list(self._log)
