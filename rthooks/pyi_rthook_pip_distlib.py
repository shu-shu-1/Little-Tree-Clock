"""修复 pip._vendor.distlib 在 PyInstaller 冻结环境下的资源查找问题。"""

import os
import sys

if os.name != "nt" or not getattr(sys, "frozen", False):
    pass  # 非 Windows 或非打包环境：无需处理
else:

    def _apply_distlib_patch() -> None:
        _meipass: str = getattr(sys, "_MEIPASS", "")
        if not _meipass:
            return

        _real_dir = os.path.join(_meipass, "pip", "_vendor", "distlib")
        if not os.path.isdir(_real_dir):
            return

        _exe_resources: dict[str, bytes] = {}
        try:
            for _fname in os.listdir(_real_dir):
                if _fname.endswith(".exe"):
                    _fpath = os.path.join(_real_dir, _fname)
                    with open(_fpath, "rb") as _f:
                        _exe_resources[_fname] = _f.read()
        except Exception:
            return  # 读取失败时保持沉默，不影响启动

        if not _exe_resources:
            return

        try:
            import pip._vendor.distlib.resources as _res
        except ImportError:
            return

        _original_finder = _res.finder

        class _DirectoryResource:
            """模拟 distlib Resource 对象，直接持有文件名和字节"""

            def __init__(self, name: str, data: bytes) -> None:
                self.name = name
                self.bytes = data

        class _DirectoryFinder:
            """直接从 _real_dir 提供资源，无需 pkgutil.get_importer"""

            def iterator(self, resource_type: str):  # noqa: ANN201
                for name, data in _exe_resources.items():
                    yield _DirectoryResource(name, data)

            def find(self, path: str):  # noqa: ANN201
                data = _exe_resources.get(os.path.basename(path))
                if data is not None:
                    return _DirectoryResource(os.path.basename(path), data)
                return None

        _DISTLIB_PKG = "pip._vendor.distlib"

        def _patched_finder(package: str):
            if package == _DISTLIB_PKG:
                return _DirectoryFinder()
            try:
                return _original_finder(package)
            except Exception:

                class _EmptyFinder:
                    def iterator(self, *a, **kw):  # noqa: ANN201
                        return iter([])

                    def find(self, path: str):  # noqa: ANN201
                        return None

                return _EmptyFinder()

        _res.finder = _patched_finder

    _apply_distlib_patch()
