"""文件系统工具函数。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any


_ELEVATION_WAIT_TIMEOUT_SEC = 25.0


def _is_windows() -> bool:
    return os.name == "nt"


def _is_admin() -> bool:
    """检测当前进程是否具有管理员权限"""
    if not _is_windows():
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (OSError, ImportError):
        # OSError: ctypes 调用失败
        # ImportError: Windows 特定模块不存在
        return False


def _is_permission_error(exc: BaseException) -> bool:
    """检查异常是否为权限相关错误"""
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError):
        winerror = getattr(exc, "winerror", None)
        if winerror in {5, 1314}:  # Access denied / A required privilege is not held
            return True
        if getattr(exc, "errno", None) == 13:  # Permission denied
            return True
    return False


def _should_retry_with_uac(exc: BaseException) -> bool:
    """判断是否应该通过 UAC 提权重试"""
    return _is_windows() and (not _is_admin()) and _is_permission_error(exc)


def _build_elevated_launch(request_path: Path, result_path: Path) -> tuple[str, str]:
    """构建提权进程的命令行参数"""
    if getattr(sys, "frozen", False):
        exe = str(Path(sys.executable).resolve())
        argv = [
            "--elevated-file-op",
            str(request_path),
            "--elevated-file-op-result",
            str(result_path),
        ]
        return exe, subprocess.list2cmdline(argv)

    exe = str(Path(sys.executable).resolve())
    main_py = Path(__file__).resolve().parents[2] / "main.py"
    argv = [
        str(main_py),
        "--elevated-file-op",
        str(request_path),
        "--elevated-file-op-result",
        str(result_path),
    ]
    return exe, subprocess.list2cmdline(argv)


def _request_elevated_operation(payload: dict[str, Any]) -> None:
    """发起提权文件操作请求"""
    temp_root = Path(tempfile.gettempdir()) / "LittleTreeClock" / "uac"
    temp_root.mkdir(parents=True, exist_ok=True)

    token = uuid.uuid4().hex
    request_path = temp_root / f"request_{token}.json"
    result_path = temp_root / f"result_{token}.json"

    try:
        request_path.write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        raise OSError(f"无法写入请求文件: {e}") from e

    try:
        exe, params = _build_elevated_launch(request_path, result_path)
        import ctypes

        ret = int(ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 0))
        if ret <= 32:
            raise PermissionError(f"管理员授权被取消或提权启动失败 (ret={ret})")

        deadline = time.monotonic() + _ELEVATION_WAIT_TIMEOUT_SEC
        while time.monotonic() < deadline:
            if result_path.exists():
                try:
                    response = json.loads(result_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as e:
                    raise OSError(f"无法读取结果文件: {e}") from e

                if bool(response.get("ok", False)):
                    return
                message = str(response.get("error") or "提权操作失败")
                raise PermissionError(message)
            time.sleep(0.1)

        raise TimeoutError("等待提权操作完成超时")
    finally:
        for p in (request_path, result_path):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass


def mkdir_with_uac(
    path: str | Path,
    *,
    parents: bool = True,
    exist_ok: bool = True
) -> None:
    """创建目录，必要时提权"""
    p = Path(path)
    try:
        p.mkdir(parents=parents, exist_ok=exist_ok)
    except OSError as exc:
        if not _should_retry_with_uac(exc):
            raise
        _request_elevated_operation({
            "op": "mkdir",
            "path": str(p),
            "parents": bool(parents),
            "exist_ok": bool(exist_ok),
        })


def write_text_with_uac(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
    ensure_parent: bool = True,
    append: bool = False,
) -> None:
    """写入文本文件，必要时提权"""
    p = Path(path)
    mode = "a" if append else "w"
    try:
        if ensure_parent:
            p.parent.mkdir(parents=True, exist_ok=True)
        with p.open(mode, encoding=encoding) as fp:
            fp.write(text)
    except OSError as exc:
        if not _should_retry_with_uac(exc):
            raise
        _request_elevated_operation({
            "op": "write_text",
            "path": str(p),
            "text": text,
            "encoding": encoding,
            "ensure_parent": bool(ensure_parent),
            "append": bool(append),
        })


def append_text_with_uac(
    path: str | Path,
    text: str,
    *,
    encoding: str = "utf-8",
    ensure_parent: bool = True,
) -> None:
    """追加文本到文件，必要时提权"""
    write_text_with_uac(
        path,
        text,
        encoding=encoding,
        ensure_parent=ensure_parent,
        append=True,
    )


def write_bytes_with_uac(
    path: str | Path,
    data: bytes,
    *,
    ensure_parent: bool = True,
) -> None:
    """写入二进制文件，必要时提权"""
    p = Path(path)
    try:
        if ensure_parent:
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    except OSError as exc:
        if not _should_retry_with_uac(exc):
            raise

        temp_blob = Path(tempfile.gettempdir()) / f"ltc_blob_{uuid.uuid4().hex}.bin"
        try:
            temp_blob.write_bytes(data)
            _request_elevated_operation({
                "op": "write_bytes",
                "path": str(p),
                "blob_path": str(temp_blob),
                "ensure_parent": bool(ensure_parent),
            })
        finally:
            try:
                if temp_blob.exists():
                    temp_blob.unlink()
            except OSError:
                pass


def ensure_dirs(*dirs: str) -> None:
    """确保多个目录存在，若不存在则创建。"""
    for d in dirs:
        mkdir_with_uac(d, parents=True, exist_ok=True)


def _run_op_without_uac(payload: dict[str, Any]) -> None:
    """在提权进程中执行文件操作"""
    op = str(payload.get("op", "")).strip().lower()
    path_text = str(payload.get("path") or "").strip()

    if not path_text:
        raise ValueError("缺少有效 path")

    p = Path(path_text)

    if op == "mkdir":
        p.mkdir(
            parents=bool(payload.get("parents", True)),
            exist_ok=bool(payload.get("exist_ok", True)),
        )
        return

    if op == "write_text":
        if bool(payload.get("ensure_parent", True)):
            p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if bool(payload.get("append", False)) else "w"
        enc = str(payload.get("encoding") or "utf-8")
        text = str(payload.get("text") or "")
        with p.open(mode, encoding=enc) as fp:
            fp.write(text)
        return

    if op == "write_bytes":
        blob_path = Path(str(payload.get("blob_path") or "").strip())
        if not blob_path.exists() or not blob_path.is_file():
            raise FileNotFoundError(f"提权写入缺少数据文件: {blob_path}")
        if bool(payload.get("ensure_parent", True)):
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob_path.read_bytes())
        return

    raise ValueError(f"不支持的提权操作: {op}")


def run_elevated_file_operation(request_file: str, result_file: str | None) -> int:
    """以管理员子进程模式执行文件操作。"""
    response: dict[str, Any] = {"ok": False, "error": "unknown"}
    exit_code = 1

    try:
        payload = json.loads(Path(request_file).read_text(encoding="utf-8"))

        if isinstance(payload, dict) and isinstance(payload.get("ops"), list):
            for op_payload in payload["ops"]:
                if not isinstance(op_payload, dict):
                    raise ValueError("ops 中存在非法操作项")
                _run_op_without_uac(op_payload)
        elif isinstance(payload, dict):
            _run_op_without_uac(payload)
        else:
            raise ValueError("提权请求格式无效")

        response = {"ok": True}
        exit_code = 0

    except (json.JSONDecodeError, OSError, ValueError) as exc:
        response = {"ok": False, "error": str(exc)}
        exit_code = 1

    if result_file:
        try:
            result_path = Path(result_file)
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                json.dumps(response, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    return exit_code
