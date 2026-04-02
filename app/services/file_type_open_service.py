"""文件类型打开用途注册服务。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.services.i18n_service import I18nService
from app.utils.logger import logger


@dataclass
class FileTypeOpenAction:
    """由插件注册的文件类型打开用途。"""

    action_id: str
    plugin_id: str
    file_extension: str  # 文件扩展名，如 ".abc"
    title: str
    handler: Callable[[Path], Any]
    description: str = ""
    content: str = ""
    order: int = 100
    breadcrumb: List[str] = field(default_factory=list)
    wizard_pages: Any = None
    title_i18n: Dict[str, str] = field(default_factory=dict)
    description_i18n: Dict[str, str] = field(default_factory=dict)

    def resolve_title(self) -> str:
        return I18nService.instance().resolve_text(self.title_i18n, self.title or self.action_id)

    def resolve_description(self) -> str:
        return self.resolve_content()

    def resolve_content(self) -> str:
        fallback = str(self.content or self.description or "")
        return I18nService.instance().resolve_text(self.description_i18n, fallback)

    def resolve_breadcrumb(self) -> List[str]:
        return [str(item).strip() for item in self.breadcrumb if str(item).strip()]


class FileTypeOpenService:
    """管理未知文件类型打开用途的注册与查询。"""

    def __init__(self) -> None:
        self._actions: Dict[str, FileTypeOpenAction] = {}

    @staticmethod
    def _normalize_i18n_map(value: Optional[Dict[str, str]]) -> Dict[str, str]:
        if not isinstance(value, dict):
            return {}
        result: Dict[str, str] = {}
        for key, text in value.items():
            if isinstance(text, str) and text.strip():
                result[I18nService.normalize_language(str(key))] = text
        return result

    @staticmethod
    def _normalize_breadcrumb(value: Any) -> List[str]:
        parts: List[str] = []
        if isinstance(value, str):
            parts = [value]
        elif isinstance(value, (list, tuple)):
            parts = [str(item) for item in value]

        result: List[str] = []
        for item in parts:
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result

    def register_action(
        self,
        *,
        action_id: str,
        file_extension: str,
        title: str,
        handler: Callable[[Path], Any],
        plugin_id: str,
        description: str = "",
        content: str = "",
        order: int = 100,
        breadcrumb: Any = None,
        wizard_pages: Any = None,
        title_i18n: Optional[Dict[str, str]] = None,
        description_i18n: Optional[Dict[str, str]] = None,
    ) -> tuple[bool, str]:
        key = str(action_id or "").strip()
        owner = str(plugin_id or "").strip()
        ext = str(file_extension or "").strip().lower()
        if not key:
            return False, "action_id 不能为空"
        if not owner:
            return False, "plugin_id 不能为空"
        if not ext:
            return False, "file_extension 不能为空"
        if not ext.startswith("."):
            ext = "." + ext
        if not callable(handler):
            return False, "handler 必须可调用"

        existing = self._actions.get(key)
        if existing is not None and existing.plugin_id != owner:
            msg = f"action_id 已被插件 {existing.plugin_id} 占用"
            logger.warning("[文件类型打开用途] 注册失败：{}", msg)
            return False, msg

        normalized_breadcrumb = self._normalize_breadcrumb(breadcrumb)
        if not normalized_breadcrumb:
            normalized_breadcrumb = [owner or "插件"]

        resolved_description = str(description or "").strip()
        resolved_content = str(content or "").strip() or resolved_description
        if not resolved_description:
            resolved_description = resolved_content

        self._actions[key] = FileTypeOpenAction(
            action_id=key,
            plugin_id=owner,
            file_extension=ext,
            title=str(title or key).strip() or key,
            description=resolved_description,
            content=resolved_content,
            handler=handler,
            order=int(order),
            breadcrumb=normalized_breadcrumb,
            wizard_pages=wizard_pages,
            title_i18n=self._normalize_i18n_map(title_i18n),
            description_i18n=self._normalize_i18n_map(description_i18n),
        )
        logger.debug("[文件类型打开用途] 已注册：action_id={}, plugin_id={}, extension={}", key, owner, ext)
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
        logger.debug("[文件类型打开用途] 已注销：action_id={}, plugin_id={}", key, existing.plugin_id)
        return True, "ok"

    def list_actions(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for action in sorted(
            self._actions.values(),
            key=lambda item: (
                item.order,
                "/".join(action_part.lower() for action_part in item.resolve_breadcrumb()),
                item.resolve_title().lower(),
                item.action_id,
            ),
        ):
            result.append({
                "action_id": action.action_id,
                "plugin_id": action.plugin_id,
                "file_extension": action.file_extension,
                "title": action.resolve_title(),
                "description": action.resolve_description(),
                "content": action.resolve_content(),
                "breadcrumb": action.resolve_breadcrumb(),
                "wizard_pages": action.wizard_pages,
                "handler": action.handler,
                "order": action.order,
            })
        return result

    def get_actions_for_extension(self, file_extension: str) -> List[Dict[str, Any]]:
        """获取指定扩展名的所有可用打开方式。"""
        ext = str(file_extension or "").strip().lower()
        if not ext.startswith("."):
            ext = "." + ext
        result = []
        for action in self._actions.values():
            if action.file_extension == ext:
                result.append({
                    "action_id": action.action_id,
                    "plugin_id": action.plugin_id,
                    "file_extension": action.file_extension,
                    "title": action.resolve_title(),
                    "description": action.resolve_description(),
                    "content": action.resolve_content(),
                    "breadcrumb": action.resolve_breadcrumb(),
                    "wizard_pages": action.wizard_pages,
                    "handler": action.handler,
                    "order": action.order,
                })
        return sorted(
            result,
            key=lambda item: (
                item["order"],
                "/".join(action_part.lower() for action_part in item["breadcrumb"]),
                item["title"].lower(),
                item["action_id"],
            ),
        )

    def list_registered_extensions(self) -> List[Dict[str, str]]:
        """返回所有已注册的文件扩展名列表（插件注册）。"""
        result: List[Dict[str, str]] = []
        seen_exts: set[str] = set()
        for action in self._actions.values():
            ext = action.file_extension
            if ext in seen_exts:
                continue
            seen_exts.add(ext)
            result.append({
                "extension": ext,
                "plugin_id": action.plugin_id,
                "title": action.resolve_title(),
            })
        return sorted(result, key=lambda x: x["extension"])

    def get_handler(self, action_id: str) -> Optional[Callable[[Path], Any]]:
        """根据 action_id 获取 handler。"""
        action = self._actions.get(str(action_id or "").strip())
        return action.handler if action else None
