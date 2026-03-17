"""Plugin development CLI for Little Tree Clock.

Commands:
- init: create a plugin scaffold
- pack: package a plugin folder into .ltcplugin
- validate: validate plugin folder or .ltcplugin format
"""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

PACKAGE_EXTENSION = ".ltcplugin"
PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
VALID_PLUGIN_TYPES = {"feature", "library"}
VALID_PERMISSIONS = {
    "network",
    "fs_read",
    "fs_write",
    "os_exec",
    "os_env",
    "clipboard",
    "notification",
    "install_pkg",
}
IGNORED_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
}
IGNORED_FILE_NAMES = {".DS_Store", "Thumbs.db"}
IGNORED_FILE_SUFFIXES = {".pyc", ".pyo"}


@dataclass
class ValidationResult:
    """Validation output for a plugin target."""

    target: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def is_valid(self, strict_warnings: bool = False) -> bool:
        if self.errors:
            return False
        if strict_warnings and self.warnings:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": str(self.target),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "notes": list(self.notes),
            "valid": self.is_valid(strict_warnings=False),
        }


def _error(result: ValidationResult, message: str) -> None:
    result.errors.append(message)


def _warn(result: ValidationResult, message: str) -> None:
    result.warnings.append(message)


def _note(result: ValidationResult, message: str) -> None:
    result.notes.append(message)


def _print_failure(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)


def _print_success(message: str) -> None:
    print(f"OK: {message}")


def _split_multi_values(values: list[str] | None) -> list[str]:
    if not values:
        return []
    result: list[str] = []
    for value in values:
        for piece in str(value).split(","):
            text = piece.strip()
            if text:
                result.append(text)
    return result


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _dist_name(requirement: str) -> str:
    cleaned = requirement.split(";", 1)[0].strip()
    match = re.match(r"^([A-Za-z0-9_.-]+)", cleaned)
    return (match.group(1) if match else cleaned).strip()


def _is_safe_requirement_spec(requirement: str) -> bool:
    text = requirement.strip()
    if not text:
        return False
    lowered = text.lower()
    if text.startswith("-"):
        return False
    if " @ " in text or "@" in text.split(";", 1)[0]:
        return False
    if "://" in lowered:
        return False
    if lowered.startswith(("git+", "hg+", "svn+", "bzr+", "file:")):
        return False
    dist = _dist_name(text)
    if not dist:
        return False
    if "/" in dist or "\\" in dist:
        return False
    return True


def _looks_like_base64_token(text: str) -> bool:
    compact = str(text or "").replace("\r", "").replace("\n", "").replace(" ", "")
    return len(compact) >= 64 and bool(re.fullmatch(r"[A-Za-z0-9+/=]+", compact))


def _is_valid_base64_payload(payload: str) -> bool:
    compact = str(payload or "").replace("\r", "").replace("\n", "").replace(" ", "")
    if not compact:
        return False
    padding = (-len(compact)) % 4
    if padding:
        compact += "=" * padding
    try:
        base64.b64decode(compact, validate=False)
        return True
    except (binascii.Error, ValueError):
        return False


def _has_valid_name(data: dict[str, Any]) -> bool:
    name_value = data.get("name")
    if isinstance(name_value, str) and name_value.strip():
        return True
    if isinstance(name_value, dict):
        for value in name_value.values():
            if isinstance(value, str) and value.strip():
                return True

    name_i18n = data.get("name_i18n")
    if isinstance(name_i18n, dict):
        for value in name_i18n.values():
            if isinstance(value, str) and value.strip():
                return True
    return False


def _validate_manifest_data(
    data: dict[str, Any],
    result: ValidationResult,
    *,
    context_label: str,
) -> tuple[str, str]:
    plugin_id = str(data.get("id", "")).strip()
    if not plugin_id:
        _error(result, f"{context_label}: missing required field 'id'.")
    elif not PLUGIN_ID_RE.match(plugin_id):
        _error(
            result,
            (
                f"{context_label}: invalid id '{plugin_id}'. "
                "Expected ^[a-z][a-z0-9_]{0,63}$"
            ),
        )

    if not _has_valid_name(data):
        _error(result, f"{context_label}: missing required field 'name' (or 'name_i18n').")

    plugin_type = data.get("plugin_type")
    if plugin_type is not None:
        plugin_type_text = str(plugin_type).strip()
        if plugin_type_text not in VALID_PLUGIN_TYPES:
            _error(
                result,
                (
                    f"{context_label}: invalid plugin_type '{plugin_type_text}'. "
                    f"Supported: {sorted(VALID_PLUGIN_TYPES)}"
                ),
            )

    version = str(data.get("version", "")).strip()
    if not version:
        _warn(result, f"{context_label}: version is empty; default runtime fallback may be used.")

    requires = data.get("requires", [])
    if requires is None:
        requires = []
    if not isinstance(requires, list):
        _error(result, f"{context_label}: field 'requires' must be an array.")
    else:
        for dep in requires:
            dep_text = str(dep).strip()
            if not dep_text:
                _warn(result, f"{context_label}: empty item found in 'requires'.")
                continue
            if not PLUGIN_ID_RE.match(dep_text):
                _error(
                    result,
                    (
                        f"{context_label}: invalid requires item '{dep_text}'. "
                        "Expected plugin id format ^[a-z][a-z0-9_]{0,63}$"
                    ),
                )

    dependencies = data.get("dependencies", [])
    if dependencies is None:
        dependencies = []
    if not isinstance(dependencies, list):
        _error(result, f"{context_label}: field 'dependencies' must be an array.")
    else:
        for spec in dependencies:
            text = str(spec).strip()
            if not text:
                _warn(result, f"{context_label}: empty item found in 'dependencies'.")
                continue
            if not _is_safe_requirement_spec(text):
                _error(
                    result,
                    f"{context_label}: unsafe dependency spec '{text}'.",
                )

    permissions = data.get("permissions", [])
    if permissions is None:
        permissions = []
    if not isinstance(permissions, list):
        _error(result, f"{context_label}: field 'permissions' must be an array.")
    else:
        for perm in permissions:
            perm_text = str(perm).strip()
            if not perm_text:
                _warn(result, f"{context_label}: empty permission item found.")
                continue
            if perm_text not in VALID_PERMISSIONS:
                _error(
                    result,
                    (
                        f"{context_label}: unknown permission '{perm_text}'. "
                        f"Supported: {sorted(VALID_PERMISSIONS)}"
                    ),
                )

    icon = data.get("icon", "")
    if icon is not None and not isinstance(icon, str):
        _error(result, f"{context_label}: field 'icon' must be a string.")
    elif isinstance(icon, str):
        icon_text = icon.strip()
        if icon_text.lower().startswith("data:image/"):
            marker = ";base64,"
            pos = icon_text.lower().find(marker)
            if pos < 0:
                _error(result, f"{context_label}: icon data URI must include ';base64,'.")
            else:
                payload = icon_text[pos + len(marker):].strip()
                if not _is_valid_base64_payload(payload):
                    _error(result, f"{context_label}: icon contains invalid base64 payload.")
        elif _looks_like_base64_token(icon_text) and not _is_valid_base64_payload(icon_text):
            _error(result, f"{context_label}: icon looks like base64 but payload is invalid.")

    tags = data.get("tags", [])
    if tags is not None and not isinstance(tags, list):
        _error(result, f"{context_label}: field 'tags' must be an array.")

    return plugin_id, version


def _validate_requirements_file(path: Path, result: ValidationResult) -> None:
    if not path.exists():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        _error(result, f"requirements.txt is not UTF-8: {path}")
        return

    for line_no, line in enumerate(lines, start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if not _is_safe_requirement_spec(text):
            _warn(
                result,
                (
                    "requirements.txt contains a non-standard or unsafe dependency "
                    f"at line {line_no}: '{text}'."
                ),
            )


def validate_plugin_directory(plugin_dir: Path) -> ValidationResult:
    result = ValidationResult(target=plugin_dir)

    if not plugin_dir.exists():
        _error(result, f"Path does not exist: {plugin_dir}")
        return result
    if not plugin_dir.is_dir():
        _error(result, f"Path is not a directory: {plugin_dir}")
        return result

    entry_file = plugin_dir / "__init__.py"
    manifest_file = plugin_dir / "plugin.json"

    if not entry_file.exists():
        _error(result, "Missing required file: __init__.py")
    if not manifest_file.exists():
        _error(result, "Missing required file: plugin.json")
        return result

    try:
        manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        _error(result, f"Manifest is not UTF-8: {manifest_file}")
        return result
    except json.JSONDecodeError as exc:
        _error(result, f"Invalid JSON in manifest: {manifest_file} ({exc})")
        return result

    plugin_id, _version = _validate_manifest_data(
        manifest_data,
        result,
        context_label="plugin.json",
    )

    if plugin_id and plugin_dir.name != plugin_id:
        _warn(
            result,
            (
                "Directory name and plugin id differ "
                f"(directory='{plugin_dir.name}', id='{plugin_id}')."
            ),
        )

    _validate_requirements_file(plugin_dir / "requirements.txt", result)
    _note(result, f"Validated directory: {plugin_dir}")
    return result


def _validate_zip_member_paths(members: list[str], result: ValidationResult) -> None:
    for member in members:
        if "\\" in member:
            _error(result, f"Archive member uses backslash path separator: {member}")
            continue

        path = PurePosixPath(member)
        if path.is_absolute():
            _error(result, f"Archive member must not be absolute: {member}")
            continue

        if any(part in {"", ".", ".."} for part in path.parts):
            _error(result, f"Archive member contains unsafe path segment: {member}")


def _pick_member(
    members: list[str],
    root_name: str | None,
    file_name: str,
) -> tuple[str | None, list[str]]:
    warnings: list[str] = []

    if root_name:
        preferred = f"{root_name}/{file_name}"
        if preferred in members:
            return preferred, warnings

    candidates = [
        item
        for item in members
        if item == file_name or item.endswith(f"/{file_name}")
    ]
    if len(candidates) == 1:
        return candidates[0], warnings

    if len(candidates) > 1:
        warnings.append(f"Multiple '{file_name}' files found in archive.")
        return None, warnings

    return None, warnings


def validate_plugin_package(package_file: Path) -> ValidationResult:
    result = ValidationResult(target=package_file)

    if not package_file.exists():
        _error(result, f"Path does not exist: {package_file}")
        return result
    if not package_file.is_file():
        _error(result, f"Path is not a file: {package_file}")
        return result
    if package_file.suffix.lower() != PACKAGE_EXTENSION:
        _error(
            result,
            f"Package extension must be '{PACKAGE_EXTENSION}': {package_file.name}",
        )
        return result

    try:
        with zipfile.ZipFile(package_file, "r") as archive:
            members = [name for name in archive.namelist() if not name.endswith("/")]
            if not members:
                _error(result, "Archive is empty.")
                return result

            _validate_zip_member_paths(members, result)
            if result.errors:
                return result

            top_dirs = sorted({PurePosixPath(name).parts[0] for name in members if PurePosixPath(name).parts})
            root_name: str | None = None
            if len(top_dirs) == 1:
                root_name = top_dirs[0]
                _note(result, f"Archive root folder: {root_name}")
            else:
                _warn(
                    result,
                    "Archive has multiple top-level entries; single root folder is recommended.",
                )

            manifest_member, manifest_warnings = _pick_member(members, root_name, "plugin.json")
            for warning in manifest_warnings:
                _warn(result, warning)
            entry_member, entry_warnings = _pick_member(members, root_name, "__init__.py")
            for warning in entry_warnings:
                _warn(result, warning)

            if manifest_member is None:
                _error(result, "Missing plugin.json in archive.")
                return result
            if entry_member is None:
                _error(result, "Missing __init__.py in archive.")
                return result

            try:
                manifest_bytes = archive.read(manifest_member)
                manifest_data = json.loads(manifest_bytes.decode("utf-8"))
            except UnicodeDecodeError:
                _error(result, f"Manifest is not UTF-8 in archive: {manifest_member}")
                return result
            except json.JSONDecodeError as exc:
                _error(result, f"Invalid JSON in archive manifest: {exc}")
                return result

            plugin_id, _version = _validate_manifest_data(
                manifest_data,
                result,
                context_label=f"{manifest_member}",
            )

            if root_name and plugin_id and root_name != plugin_id:
                _warn(
                    result,
                    (
                        "Archive root folder and plugin id differ "
                        f"(root='{root_name}', id='{plugin_id}')."
                    ),
                )

            _note(result, f"Validated package: {package_file}")

    except zipfile.BadZipFile:
        _error(result, "File is not a valid ZIP archive payload.")
    except OSError as exc:
        _error(result, f"Cannot open archive: {exc}")

    return result


def validate_target(path: Path) -> ValidationResult:
    if path.is_dir():
        return validate_plugin_directory(path)
    return validate_plugin_package(path)


def _iter_package_files(plugin_dir: Path) -> list[Path]:
    files: list[Path] = []

    for root, dirnames, filenames in os.walk(plugin_dir):
        root_path = Path(root)
        rel_root_parts = root_path.relative_to(plugin_dir).parts

        dirnames[:] = [
            item
            for item in dirnames
            if item not in IGNORED_DIR_NAMES and not item.startswith(".")
        ]

        if any(part in IGNORED_DIR_NAMES for part in rel_root_parts):
            continue

        for filename in filenames:
            if filename in IGNORED_FILE_NAMES:
                continue
            file_path = root_path / filename
            if file_path.suffix in IGNORED_FILE_SUFFIXES:
                continue
            files.append(file_path)

    files.sort(key=lambda item: item.relative_to(plugin_dir).as_posix())
    return files


def _resolve_output_file(
    plugin_dir: Path,
    plugin_id: str,
    version: str,
    output: str | None,
) -> Path:
    default_name = f"{plugin_id}-{version}{PACKAGE_EXTENSION}"

    if not output:
        return plugin_dir.parent / default_name

    out_path = Path(output)
    if out_path.suffix:
        if out_path.suffix.lower() != PACKAGE_EXTENSION:
            raise ValueError(
                f"Output file must use '{PACKAGE_EXTENSION}' extension: {out_path}"
            )
        return out_path

    return out_path / default_name


def _read_manifest_from_directory(plugin_dir: Path) -> dict[str, Any]:
    manifest_path = plugin_dir / "plugin.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def cmd_validate(args: argparse.Namespace) -> int:
    target = Path(args.target)
    result = validate_target(target)

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Target: {result.target}")
        print("Status: VALID" if result.is_valid(False) else "Status: INVALID")

        if result.errors:
            print("Errors:")
            for item in result.errors:
                print(f"  - {item}")

        if result.warnings:
            print("Warnings:")
            for item in result.warnings:
                print(f"  - {item}")

        if result.notes:
            print("Notes:")
            for item in result.notes:
                print(f"  - {item}")

    return 0 if result.is_valid(strict_warnings=args.strict_warnings) else 1


def _py_string_literal(value: str) -> str:
    return json.dumps(value)


def _render_feature_template(plugin_id: str, name: str, version: str, description: str, author: str) -> str:
    return (
        '"""Auto-generated feature plugin skeleton."""\n'
        "from __future__ import annotations\n\n"
        "from app.plugins import BasePlugin, PluginAPI, PluginMeta\n\n\n"
        "class Plugin(BasePlugin):\n"
        "    meta = PluginMeta(\n"
        f"        id={_py_string_literal(plugin_id)},\n"
        f"        name={_py_string_literal(name)},\n"
        f"        version={_py_string_literal(version)},\n"
        f"        description={_py_string_literal(description)},\n"
        f"        author={_py_string_literal(author)},\n"
        "    )\n\n"
        "    def on_load(self, api: PluginAPI) -> None:\n"
        "        self._api = api\n\n"
        "    def on_unload(self) -> None:\n"
        "        pass\n"
    )


def _render_library_template(plugin_id: str, name: str, version: str, description: str, author: str) -> str:
    return (
        '"""Auto-generated library plugin skeleton."""\n'
        "from __future__ import annotations\n\n"
        "from app.plugins import LibraryPlugin, PluginAPI, PluginMeta, PluginType\n\n\n"
        "class Plugin(LibraryPlugin):\n"
        "    meta = PluginMeta(\n"
        f"        id={_py_string_literal(plugin_id)},\n"
        f"        name={_py_string_literal(name)},\n"
        f"        version={_py_string_literal(version)},\n"
        f"        description={_py_string_literal(description)},\n"
        f"        author={_py_string_literal(author)},\n"
        "        plugin_type=PluginType.LIBRARY,\n"
        "    )\n\n"
        "    def on_load(self, api: PluginAPI) -> None:\n"
        "        self._api = api\n\n"
        "    def on_unload(self) -> None:\n"
        "        pass\n\n"
        "    def export(self):\n"
        "        return self\n"
    )


def cmd_init(args: argparse.Namespace) -> int:
    plugin_id = str(args.plugin_id).strip()
    if not PLUGIN_ID_RE.match(plugin_id):
        _print_failure(
            "Invalid plugin id. Expected format: ^[a-z][a-z0-9_]{0,63}$"
        )
        return 1

    plugin_type = str(args.plugin_type).strip().lower()
    if plugin_type not in VALID_PLUGIN_TYPES:
        _print_failure(f"Invalid plugin type: {plugin_type}")
        return 1

    requires = _dedupe(_split_multi_values(args.require))
    dependencies = _dedupe(_split_multi_values(args.dependency))
    permissions = _dedupe(_split_multi_values(args.permission))
    tags = _dedupe(_split_multi_values(args.tag))

    for dep in requires:
        if not PLUGIN_ID_RE.match(dep):
            _print_failure(f"Invalid requires item: {dep}")
            return 1

    for spec in dependencies:
        if not _is_safe_requirement_spec(spec):
            _print_failure(f"Unsafe dependency spec: {spec}")
            return 1

    for perm in permissions:
        if perm not in VALID_PERMISSIONS:
            _print_failure(f"Unknown permission: {perm}")
            return 1

    output_dir = Path(args.output_dir)
    plugin_dir = output_dir / plugin_id

    if plugin_dir.exists():
        if not args.force:
            _print_failure(f"Destination already exists: {plugin_dir}")
            return 1
        shutil.rmtree(plugin_dir)

    plugin_dir.mkdir(parents=True, exist_ok=True)

    name = str(args.name).strip() or plugin_id
    version = str(args.version).strip() or "1.0.0"
    author = str(args.author).strip()
    description = str(args.description).strip() or "Plugin generated by plugin CLI"
    icon = str(args.icon or "").strip()

    if icon.lower().startswith("data:image/"):
        marker = ";base64,"
        pos = icon.lower().find(marker)
        if pos < 0 or not _is_valid_base64_payload(icon[pos + len(marker):].strip()):
            _print_failure("Invalid icon data URI: expected data:image/...;base64,<payload>")
            return 1
    elif _looks_like_base64_token(icon) and not _is_valid_base64_payload(icon):
        _print_failure("Invalid base64 icon payload.")
        return 1

    manifest = {
        "id": plugin_id,
        "name": name,
        "version": version,
        "author": author,
        "description": description,
        "plugin_type": plugin_type,
        "requires": requires,
        "dependencies": dependencies,
        "permissions": permissions,
        "tags": tags,
    }
    if icon:
        manifest["icon"] = icon

    template = (
        _render_library_template(plugin_id, name, version, description, author)
        if plugin_type == "library"
        else _render_feature_template(plugin_id, name, version, description, author)
    )

    (plugin_dir / "plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(template, encoding="utf-8")
    (plugin_dir / "requirements.txt").write_text(
        "# Optional PyPI dependencies\n",
        encoding="utf-8",
    )
    (plugin_dir / "README.md").write_text(
        "# Plugin\n\nGenerated by tools/plugin_cli.\n",
        encoding="utf-8",
    )

    _print_success(f"Plugin scaffold created: {plugin_dir}")
    return 0


def cmd_pack(args: argparse.Namespace) -> int:
    plugin_dir = Path(args.source)
    validation = validate_plugin_directory(plugin_dir)
    if validation.errors:
        print(f"Cannot package invalid plugin: {plugin_dir}", file=sys.stderr)
        for err in validation.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    if validation.warnings and not args.allow_warnings:
        print("Packaging blocked by warnings (use --allow-warnings to continue):", file=sys.stderr)
        for warning in validation.warnings:
            print(f"  - {warning}", file=sys.stderr)
        return 1

    manifest = _read_manifest_from_directory(plugin_dir)
    plugin_id = str(manifest.get("id", "")).strip()
    version = str(manifest.get("version", "")).strip() or "1.0.0"

    try:
        output_file = _resolve_output_file(plugin_dir, plugin_id, version, args.output)
    except ValueError as exc:
        _print_failure(str(exc))
        return 1

    output_file.parent.mkdir(parents=True, exist_ok=True)
    if output_file.exists() and not args.force:
        _print_failure(f"Output file already exists: {output_file}")
        return 1

    files = _iter_package_files(plugin_dir)
    if not files:
        _print_failure(f"No files to package in: {plugin_dir}")
        return 1

    if output_file.exists() and args.force:
        output_file.unlink()

    with zipfile.ZipFile(output_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            relative = file_path.relative_to(plugin_dir)
            arcname = PurePosixPath(plugin_id, *relative.parts).as_posix()
            archive.write(file_path, arcname)

    _print_success(f"Package created: {output_file}")

    if args.verify:
        verify_result = validate_plugin_package(output_file)
        if not verify_result.is_valid(strict_warnings=False):
            _print_failure("Package verification failed after creation.")
            for err in verify_result.errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
        _print_success("Package verification passed.")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plugin-cli",
        description="Plugin development helper for Little Tree Clock.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a plugin scaffold.")
    init_parser.add_argument("plugin_id", help="Plugin id, e.g. my_plugin")
    init_parser.add_argument("--name", default="", help="Display name")
    init_parser.add_argument("--author", default="", help="Author")
    init_parser.add_argument(
        "--icon",
        default="",
        help="Plugin icon path or base64 data URI",
    )
    init_parser.add_argument(
        "--description",
        default="Plugin generated by plugin CLI",
        help="Plugin description",
    )
    init_parser.add_argument("--version", default="1.0.0", help="Plugin version")
    init_parser.add_argument(
        "--plugin-type",
        choices=sorted(VALID_PLUGIN_TYPES),
        default="feature",
        help="Plugin type",
    )
    init_parser.add_argument(
        "--output-dir",
        default="plugins_ext",
        help="Base folder where plugin directory will be created",
    )
    init_parser.add_argument(
        "--require",
        action="append",
        help="Required plugin id (repeatable, comma-separated supported)",
    )
    init_parser.add_argument(
        "--dependency",
        action="append",
        help="Dependency spec (repeatable, comma-separated supported)",
    )
    init_parser.add_argument(
        "--permission",
        action="append",
        help="Permission key (repeatable, comma-separated supported)",
    )
    init_parser.add_argument(
        "--tag",
        action="append",
        help="Tag (repeatable, comma-separated supported)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite destination if it exists",
    )
    init_parser.set_defaults(func=cmd_init)

    pack_parser = subparsers.add_parser("pack", help="Package plugin directory into .ltcplugin")
    pack_parser.add_argument("source", help="Plugin directory path")
    pack_parser.add_argument(
        "-o",
        "--output",
        default=None,
        help=(
            "Output .ltcplugin file path, or output directory. "
            "Default: <plugin_parent>/<id>-<version>.ltcplugin"
        ),
    )
    pack_parser.add_argument("--force", action="store_true", help="Overwrite output file if exists")
    pack_parser.add_argument(
        "--allow-warnings",
        action="store_true",
        help="Package even if validation produced warnings",
    )
    pack_parser.add_argument(
        "--verify",
        action="store_true",
        help="Validate generated package after packing",
    )
    pack_parser.set_defaults(func=cmd_pack)

    validate_parser = subparsers.add_parser("validate", help="Validate plugin folder or .ltcplugin")
    validate_parser.add_argument("target", help="Plugin directory path or .ltcplugin file path")
    validate_parser.add_argument(
        "--strict-warnings",
        action="store_true",
        help="Treat warnings as validation failures",
    )
    validate_parser.add_argument(
        "--json",
        action="store_true",
        help="Print validation result as JSON",
    )
    validate_parser.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2

    try:
        return int(func(args))
    except KeyboardInterrupt:
        _print_failure("Interrupted by user.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
