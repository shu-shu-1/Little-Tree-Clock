"""布局文件打开用途注册服务。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.services.i18n_service import I18nService
from app.utils.logger import logger


@dataclass
class LayoutFileOpenAction:
    """插件注册的布局文件打开用途。"""

    action_id: str
    plugin_id: str
    title: str
    handler: Callable[[Path], Any]
    description: str = ""
    content: str = ""
    order: int = 100
    breadcrumb: list[str] = field(default_factory=list)
    wizard_pages: Any = None
    title_i18n: dict[str, str] = field(default_factory=dict)
    description_i18n: dict[str, str] = field(default_factory=dict)

    def resolve_title(self) -> str:
        return I18nService.instance().resolve_text(self.title_i18n, self.title or self.action_id)

    def resolve_description(self) -> str:
        # 兼容旧字段：description 与 content 都当作内容说明
        return self.resolve_content()

    def resolve_content(self) -> str:
        fallback = str(self.content or self.description or "")
        return I18nService.instance().resolve_text(self.description_i18n, fallback)

    def resolve_breadcrumb(self) -> list[str]:
        return [str(item).strip() for item in self.breadcrumb if str(item).strip()]


class LayoutFileOpenService:
    """管理 .ltlayout 文件用途选项的注册与查询。"""

    def __init__(self) -> None:
        self._actions: dict[str, LayoutFileOpenAction] = {}

    @staticmethod
    def _normalize_i18n_map(value: dict[str, str] | None) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {
            I18nService.normalize_language(str(key)): text
            for key, text in value.items()
            if isinstance(text, str) and text.strip()
        }

    @staticmethod
    def _normalize_breadcrumb(value: Any) -> list[str]:
        if isinstance(value, str):
            parts = [value]
        elif isinstance(value, (list, tuple)):
            parts = [str(item) for item in value]
        else:
            parts = []
        return [text for text in (str(item or "").strip() for item in parts) if text]

    def register_action(
        self,
        *,
        action_id: str,
        title: str,
        handler: Callable[[Path], Any],
        plugin_id: str,
        description: str = "",
        content: str = "",
        order: int = 100,
        breadcrumb: Any = None,
        wizard_pages: Any = None,
        title_i18n: dict[str, str] | None = None,
        description_i18n: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        key = str(action_id or "").strip()
        owner = str(plugin_id or "").strip()
        if not key:
            return False, "action_id 不能为空"
        if not owner:
            return False, "plugin_id 不能为空"
        if not callable(handler):
            return False, "handler 必须可调用"

        existing = self._actions.get(key)
        if existing is not None and existing.plugin_id != owner:
            msg = f"action_id 已被插件 {existing.plugin_id} 占用"
            logger.warning("[布局打开用途] 注册失败：{}", msg)
            return False, msg

        crumbs = self._normalize_breadcrumb(breadcrumb) or [owner or "插件"]
        desc = str(description or "").strip()
        body = str(content or "").strip()
        if not desc:
            desc = body
        elif not body:
            body = desc

        self._actions[key] = LayoutFileOpenAction(
            action_id=key,
            plugin_id=owner,
            title=str(title or key).strip() or key,
            description=desc,
            content=body,
            handler=handler,
            order=int(order),
            breadcrumb=crumbs,
            wizard_pages=wizard_pages,
            title_i18n=self._normalize_i18n_map(title_i18n),
            description_i18n=self._normalize_i18n_map(description_i18n),
        )
        logger.debug("[布局打开用途] 已注册：action_id={}, plugin_id={}", key, owner)
        return True, "ok"

    def unregister_action(self, action_id: str, *, plugin_id: str = "") -> tuple[bool, str]:
        key = str(action_id or "").strip()
        if not key:
            return False, "action_id 不能为空"

        existing = self._actions.get(key)
        if existing is None:
            return False, "action_id 不存在"

        owner = str(plugin_id or "").strip()
        if owner and existing.plugin_id != owner:
            return False, "无权注销其他插件注册的 action"

        self._actions.pop(key, None)
        logger.debug("[布局打开用途] 已注销：action_id={}, plugin_id={}", key, existing.plugin_id)
        return True, "ok"

    def list_actions(self) -> list[dict[str, Any]]:
        actions = sorted(
            self._actions.values(),
            key=lambda item: (
                item.order,
                "/".join(part.lower() for part in item.resolve_breadcrumb()),
                item.resolve_title().lower(),
                item.action_id,
            ),
        )
        return [
            {
                "action_id": action.action_id,
                "plugin_id": action.plugin_id,
                "title": action.resolve_title(),
                "description": action.resolve_description(),
                "content": action.resolve_content(),
                "breadcrumb": action.resolve_breadcrumb(),
                "wizard_pages": action.wizard_pages,
                "handler": action.handler,
                "order": action.order,
            }
            for action in actions
        ]
