"""自定义 URL Scheme 注册与解析服务。"""

from __future__ import annotations

import sys
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from app.constants import URL_SCHEME, URL_VIEW_MAP
from app.utils.logger import logger

# Windows 注册表仅在 Windows 下可用
_WIN = sys.platform == "win32"
if _WIN:
    import winreg


@dataclass(frozen=True)
class UrlTarget:
    """URL 解析结果。"""

    action: str
    object_name: str | None = None
    zone_id: str = ""


_VIEW_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# view_key -> (object_name, owner_plugin_id)
_PLUGIN_OPEN_VIEWS: dict[str, tuple[str, str]] = {}


def _normalize_view_key(view_key: str) -> str:
    return str(view_key or "").strip().lower()


def _split_url_parts(url: str) -> list[str]:
    parsed = urlparse(url)
    if parsed.scheme.lower() != URL_SCHEME:
        return []

    parts = [p for p in parsed.path.strip("/").split("/") if p]
    # urlparse 对 ltclock://open/alarm 会把 "open" 放到 netloc
    if parsed.netloc:
        parts = [parsed.netloc] + parts
    return parts


def _python_exe() -> str:
    return sys.executable


def _main_script() -> str:
    return str(Path(__file__).resolve().parent.parent.parent / "main.py")


def _registry_key() -> str:
    return URL_SCHEME


def _command_key_path() -> str:
    return f"Software\\Classes\\{_registry_key()}\\shell\\open\\command"


def _open_command() -> str:
    exe = _python_exe()
    if getattr(sys, "frozen", False):
        return f'"{exe}" --url "%1"'

    main = _main_script()
    return f'"{exe}" "{main}" --url "%1"'


def current_command() -> str:
    """读取当前 URL Scheme 注册命令；未注册时返回空字符串。"""
    if not _WIN:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _command_key_path()) as k:
            val, _ = winreg.QueryValueEx(k, "")
            return str(val or "").strip()
    except OSError:
        return ""


def repair_registration_if_needed() -> tuple[bool, str]:
    """若协议已注册但命令与当前版本不一致，则自动修复。"""
    if not _WIN:
        return False, "URL Scheme 注册仅支持 Windows"

    current = current_command()
    if not current:
        return True, "URL Scheme 未注册，无需修复"

    expected = _open_command().strip()
    if current.strip() == expected:
        return True, "URL Scheme 启动命令已是最新"

    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _command_key_path()) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, expected)
        logger.info("URL Scheme 启动命令已修复：old='{}', new='{}'", current, expected)
        return True, "URL Scheme 启动命令已修复"
    except Exception as exc:  # noqa: BLE001
        msg = f"URL Scheme 启动命令修复失败：{exc}"
        logger.error(msg)
        return False, msg


def list_open_views() -> dict[str, str]:
    """返回当前可用的 open 路由映射（内置 + 插件注册）。"""
    result = dict(URL_VIEW_MAP)
    for key, (obj_name, _) in _PLUGIN_OPEN_VIEWS.items():
        result[key] = obj_name
    return result


def register_open_view(
    view_key: str,
    object_name: str,
    *,
    plugin_id: str = "",
) -> tuple[bool, str]:
    """注册 ``ltclock://open/<view_key>`` 路由。"""
    key = _normalize_view_key(view_key)
    obj = str(object_name or "").strip()
    owner = str(plugin_id or "").strip()

    if not _VIEW_KEY_RE.match(key):
        logger.warning("URL open 路由注册失败：非法 view_key='{}'", view_key)
        return False, f"view_key 不合法: {view_key}"
    if not obj:
        logger.warning("URL open 路由注册失败：object_name 为空（view_key='{}'）", view_key)
        return False, "object_name 不能为空"

    builtin_target = URL_VIEW_MAP.get(key)
    if builtin_target is not None and builtin_target != obj:
        logger.warning("URL open 路由注册失败：{} 为内置路由且目标冲突（{} -> {}）", key, builtin_target, obj)
        return False, f"{key} 为内置路由，不能改绑到 {obj}"
    if builtin_target == obj:
        return True, f"{key} 已是内置路由"

    existing = _PLUGIN_OPEN_VIEWS.get(key)
    if existing is not None:
        existing_obj, existing_owner = existing
        if existing_obj == obj and existing_owner == owner:
            return True, f"{key} 已注册"
        if existing_owner and owner and existing_owner != owner:
            logger.warning("URL open 路由注册失败：{} 已被 {} 注册，当前 owner={} 无权覆盖", key, existing_owner, owner)
            return False, f"{key} 已被插件 {existing_owner} 注册"
        logger.warning("URL open 路由注册失败：{} 已存在且绑定 {}", key, existing_obj)
        return False, f"{key} 已存在，当前绑定到 {existing_obj}"

    _PLUGIN_OPEN_VIEWS[key] = (obj, owner)
    logger.info("URL open 路由注册成功: {} -> {} (owner={})", key, obj, owner or "<host>")
    return True, f"已注册 {URL_SCHEME}://open/{key}"


def unregister_open_view(
    view_key: str,
    *,
    plugin_id: str = "",
) -> tuple[bool, str]:
    """注销插件注册的 ``open`` 路由。"""
    key = _normalize_view_key(view_key)
    owner = str(plugin_id or "").strip()

    if key in URL_VIEW_MAP:
        logger.warning("URL open 路由注销失败：{} 为内置路由", key)
        return False, f"{key} 为内置路由，不能注销"

    existing = _PLUGIN_OPEN_VIEWS.get(key)
    if existing is None:
        logger.warning("URL open 路由注销失败：{} 未注册", key)
        return False, f"{key} 未注册"

    _, existing_owner = existing
    if owner and existing_owner and owner != existing_owner:
        logger.warning("URL open 路由注销失败：{} 属于 {}，当前 owner={} 无权操作", key, existing_owner, owner)
        return False, f"{key} 属于插件 {existing_owner}，当前插件无权注销"

    _PLUGIN_OPEN_VIEWS.pop(key, None)
    logger.info("URL open 路由已注销: {} (owner={})", key, existing_owner or "<host>")
    return True, f"已注销 {URL_SCHEME}://open/{key}"


def build_open_url(view_key: str) -> str:
    key = _normalize_view_key(view_key)
    return f"{URL_SCHEME}://open/{key}"


def build_fullscreen_url(zone_id: str) -> str:
    zid = quote(str(zone_id or "").strip(), safe="")
    return f"{URL_SCHEME}://fullscreen/{zid}"


def is_registered() -> bool:
    if not _WIN:
        return False
    return bool(current_command())


def register() -> tuple[bool, str]:
    if not _WIN:
        return False, "URL Scheme 注册仅支持 Windows"

    try:
        root = f"Software\\Classes\\{_registry_key()}"

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, root) as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f"URL:{URL_SCHEME} Protocol")
            winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{root}\\shell\\open\\command") as k:
            winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _open_command())

        logger.info("URL Scheme '{}://' 注册成功", URL_SCHEME)
        return True, f"已成功注册 {URL_SCHEME}:// 协议"

    except Exception as exc:  # noqa: BLE001
        msg = f"注册失败：{exc}"
        logger.error(msg)
        return False, msg


def unregister() -> tuple[bool, str]:
    if not _WIN:
        return False, "URL Scheme 注册仅支持 Windows"

    def _del_tree(key_path: str) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, access=winreg.KEY_ALL_ACCESS) as k:
                while True:
                    try:
                        sub = winreg.EnumKey(k, 0)
                        _del_tree(f"{key_path}\\{sub}")
                    except OSError:
                        break
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except OSError:
            pass

    root = f"Software\\Classes\\{_registry_key()}"
    _del_tree(f"{root}\\shell\\open\\command")
    _del_tree(f"{root}\\shell\\open")
    _del_tree(f"{root}\\shell")
    _del_tree(root)

    logger.info("URL Scheme '{}://' 已注销", URL_SCHEME)
    return True, f"已移除 {URL_SCHEME}:// 协议注册"


def parse_url_target(url: str) -> UrlTarget | None:
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() != URL_SCHEME:
            logger.debug("URL 解析忽略：scheme='{}' 非目标协议", parsed.scheme)
            return None

        parts = _split_url_parts(url)
        if not parts:
            logger.warning("URL 解析失败：无有效路径部分，url='{}'", url)
            return None

        action = parts[0].lower()
        if action == "open" and len(parts) >= 2:
            view_key = _normalize_view_key(parts[1])
            object_name = list_open_views().get(view_key)
            if object_name:
                logger.info("URL 解析成功：open -> {}", object_name)
                return UrlTarget(action="open", object_name=object_name)
            logger.warning("URL 解析失败：未知 open 路由 '{}', url='{}'", view_key, url)
            return None

        if action == "fullscreen":
            zone_id = ""
            if len(parts) >= 2:
                zone_id = unquote(parts[1]).strip()
            if not zone_id:
                zone_id = str(parse_qs(parsed.query).get("zone_id", [""])[0]).strip()
            if zone_id:
                logger.info("URL 解析成功：fullscreen -> zone_id={}", zone_id)
                return UrlTarget(action="fullscreen", zone_id=zone_id)
            logger.warning("URL 解析失败：fullscreen 缺少 zone_id，url='{}'", url)
            return None
    except Exception:  # noqa: BLE001
        logger.exception("URL 解析异常：url='{}'", url)
    return None


def parse_url(url: str) -> str | None:
    """解析 ltclock://open/<view_key>，返回视图 objectName；无法识别返回 None。"""
    target = parse_url_target(url)
    if target is None or target.action != "open":
        return None
    return target.object_name
