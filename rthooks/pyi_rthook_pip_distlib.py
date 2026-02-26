"""
PyInstaller 运行时 Hook — 修复 pip._vendor.distlib 在冻结环境下的资源查找问题

问题根因：
  pip._vendor.distlib.scripts 在模块级别（Windows only）调用：
      for r in finder('pip._vendor.distlib').iterator(""): ...
  picker() 依赖 pkgutil.get_importer()，在 PyInstaller 冻结环境中返回的是
  PyInstaller 自定义加载器（PyiModuleImporter），不是 distlib 认识的
  zipimporter / FileFinder，从而抛出：
      DistlibException: Unable to locate finder for 'pip._vendor.distlib'
  即使 DistlibException 被修复，WRAPPERS 若为空则后续 _get_launcher 报：
      ValueError: Unable to find resource t64.exe in package pip._vendor.distlib

修复方式：
  collect_all("pip") 已将 distlib 的 .exe 启动器文件解压到
  sys._MEIPASS/pip/_vendor/distlib/ 目录。
  本 hook 在启动时直接从该目录读取 .exe 文件的字节并注入 WRAPPERS。
  由于 hook 在 scripts.py 被导入之前执行，scripts.py 的模块级 for 循环
  会从我们的 StubFinder 取到正确的 resource 列表从而填充 WRAPPERS。
"""
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

        # 从真实目录预读所有 .exe 文件
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

        # 导入 resources 模块并注入 finder 补丁
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

        def _patched_finder(package: str):  # type: ignore[no-untyped-def]
            if package == _DISTLIB_PKG:
                return _DirectoryFinder()
            # 其他包走原始逻辑
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
