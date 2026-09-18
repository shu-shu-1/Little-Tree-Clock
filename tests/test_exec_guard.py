"""app.plugins.exec_guard 单元测试（涉及 install() 的用例必须在 finally 中 uninstall() 恢复现场）。"""

from __future__ import annotations

import os
import subprocess
import threading

import pytest

from app.plugins import exec_guard


@pytest.fixture(autouse=True)
def _clean_guard_state(monkeypatch):
    """每个用例前后清理线程上下文与权限回调，避免跨测试污染"""
    exec_guard.clear_current_plugin()
    monkeypatch.setattr(exec_guard, "_permission_checker", None)
    yield
    exec_guard.uninstall()
    exec_guard.clear_current_plugin()


class TestPluginContext:
    def test_set_get_clear(self):
        assert exec_guard.get_current_plugin() is None
        exec_guard.set_current_plugin("my_plugin")
        assert exec_guard.get_current_plugin() == "my_plugin"
        exec_guard.clear_current_plugin()
        assert exec_guard.get_current_plugin() is None

    def test_thread_local_isolation(self):
        exec_guard.set_current_plugin("main_thread_plugin")
        seen = {}

        def worker():
            seen["value"] = exec_guard.get_current_plugin()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert seen["value"] is None  # 其他线程不可见
        assert exec_guard.get_current_plugin() == "main_thread_plugin"


class TestGuardFunc:
    def _wrap(self, func):
        return exec_guard._guard_func(func, "os.system")

    def test_denied_raises_permission_error(self):
        recorded = []

        def checker(pid, action):
            recorded.append((pid, action))
            return False

        exec_guard.set_current_plugin("naughty")
        exec_guard.set_permission_checker(checker)

        wrapper = self._wrap(lambda: recorded.append("ran"))
        with pytest.raises(PermissionError, match="os_exec"):
            wrapper()

        assert recorded == [("naughty", "os.system")]  # 目标函数未执行

    def test_allowed_passes_through(self):
        ran = []

        def checker(pid, action):
            return True

        exec_guard.set_current_plugin("polite")
        exec_guard.set_permission_checker(checker)

        wrapper = self._wrap(lambda: ran.append(True))
        wrapper()
        assert ran == [True]

    def test_no_plugin_context_passes_through(self):
        ran = []
        exec_guard.set_permission_checker(lambda pid, action: False)

        wrapper = self._wrap(lambda: ran.append(True))
        wrapper()
        assert ran == [True]  # 主程序代码不受拦截

    def test_plugin_but_no_checker_passes_through(self):
        ran = []
        exec_guard.set_current_plugin("some_plugin")
        # 未调用 set_permission_checker

        wrapper = self._wrap(lambda: ran.append(True))
        wrapper()
        assert ran == [True]


class TestGuardPopenInit:
    def test_denied(self):
        exec_guard.set_current_plugin("naughty")
        exec_guard.set_permission_checker(lambda pid, action: False)

        init_calls = []

        def fake_init(self, *args, **kwargs):
            init_calls.append(1)

        wrapper = exec_guard._guard_popen_init(fake_init)
        with pytest.raises(PermissionError, match="无执行权限"):
            wrapper(object())

        assert init_calls == []

    def test_allowed(self):
        exec_guard.set_current_plugin("polite")
        exec_guard.set_permission_checker(lambda pid, action: True)

        init_calls = []

        def fake_init(self, *args, **kwargs):
            init_calls.append(kwargs.get("token"))

        wrapper = exec_guard._guard_popen_init(fake_init)
        wrapper(object(), token="x")
        assert init_calls == ["x"]

    def test_real_popen_blocked_end_to_end(self):
        """安装拦截后，插件上下文中的 Popen 被真实阻断"""
        exec_guard.set_current_plugin("naughty")
        exec_guard.set_permission_checker(lambda pid, action: False)
        exec_guard.install()
        try:
            with pytest.raises(PermissionError):
                subprocess.Popen(["cmd", "/c", "echo hi"])
        finally:
            exec_guard.uninstall()


class TestInstallUninstall:
    def test_install_wraps_and_uninstall_restores(self):
        original_system = os.system
        original_popen_init = subprocess.Popen.__init__
        try:
            exec_guard.install()
            assert os.system is not original_system
            assert subprocess.Popen.__init__ is not original_popen_init
            assert exec_guard._installed is True

            exec_guard.uninstall()
            assert os.system is original_system
            assert subprocess.Popen.__init__ is original_popen_init
            assert exec_guard._installed is False
        finally:
            # 无论如何恢复，避免污染其他测试
            os.system = original_system
            subprocess.Popen.__init__ = original_popen_init
            exec_guard._installed = False
            exec_guard._original.clear()

    def test_install_is_idempotent(self):
        exec_guard.install()
        try:
            wrapped_once = os.system
            exec_guard.install()
            assert os.system is wrapped_once  # 未被二次包装
        finally:
            exec_guard.uninstall()

    def test_uninstall_without_install_is_noop(self):
        exec_guard.uninstall()  # 不应抛异常

    def test_main_code_unaffected_after_install(self):
        """未设置插件上下文时，安装拦截不影响主程序调用"""
        calls = []
        original_system = os.system
        os.system = lambda cmd: calls.append(cmd) or 0  # 打桩避免真执行
        try:
            exec_guard.install()
            assert os.system("echo") == 0
            assert calls == ["echo"]
        finally:
            exec_guard.uninstall()
            os.system = original_system
