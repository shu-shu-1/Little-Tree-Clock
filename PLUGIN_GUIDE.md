# 插件开发指南

> 适用版本：小树时钟 ≥ 0.10.3

---

## 目录

- [插件开发指南](#插件开发指南)
  - [目录](#目录)
  - [1. 快速开始](#1-快速开始)
  - [2. 目录结构规范](#2-目录结构规范)
    - [推荐：包形式（功能完整）](#推荐包形式功能完整)
    - [简单：单文件形式](#简单单文件形式)
  - [3. 清单文件 plugin.json](#3-清单文件-pluginjson)
    - [3.1 权限声明（permissions）](#31-权限声明permissions)
    - [3.2 依赖包自动安装机制](#32-依赖包自动安装机制)
    - [3.3 多语言元数据（i18n）](#33-多语言元数据i18n)
  - [4. 主入口类 Plugin](#4-主入口类-plugin)
    - [生命周期方法](#生命周期方法)
  - [5. 插件类型（PluginType）](#5-插件类型plugintype)
  - [6. 依赖插件开发（LibraryPlugin）](#6-依赖插件开发libraryplugin)
    - [为什么要用依赖插件？](#为什么要用依赖插件)
    - [开发步骤](#开发步骤)
    - [依赖加载顺序](#依赖加载顺序)
    - [卸载依赖插件](#卸载依赖插件)
  - [7. PluginAPI 接口参考](#7-pluginapi-接口参考)
    - [7.1 钩子注册](#71-钩子注册)
    - [7.2 持久化配置](#72-持久化配置)
    - [7.3 用户通知](#73-用户通知)
    - [7.4 宿主服务访问](#74-宿主服务访问)
    - [7.5 依赖插件访问](#75-依赖插件访问)
    - [7.6 自动化扩展](#76-自动化扩展)
    - [7.7 全局事件订阅](#77-全局事件订阅)
    - [7.8 启动参数与宿主上下文](#78-启动参数与宿主上下文)
    - [7.9 语言与 i18n 辅助](#79-语言与-i18n-辅助)
    - [7.10 时间工具](#710-时间工具)
    - [7.11 首页卡片与推荐扩展](#711-首页卡片与推荐扩展)
    - [7.12 URL Scheme 路由扩展](#712-url-scheme-路由扩展)
    - [7.13 布局文件打开扩展](#713-布局文件打开扩展)
  - [8. 钩子（HookType）列表](#8-钩子hooktype列表)
  - [9. 自动化集成](#9-自动化集成)
    - [基本步骤](#基本步骤)
  - [10. 组件右键菜单与分离窗口](#10-组件右键菜单与分离窗口)
    - [10.1 自定义右键菜单](#101-自定义右键菜单)
    - [10.2 分离为置顶窗口](#102-分离为置顶窗口)
  - [11. 持久化配置](#11-持久化配置)
  - [12. UI 扩展点](#12-ui-扩展点)
    - [12.1 设置面板](#121-设置面板)
    - [12.2 侧边栏面板](#122-侧边栏面板)
      - [实现步骤](#实现步骤)
      - [完整示例](#完整示例)
      - [注意事项](#注意事项)
    - [12.3 画布小组件（WidgetBase）](#123-画布小组件widgetbase)
  - [13. 注意事项与最佳实践](#13-注意事项与最佳实践)
    - [✅ 应当](#-应当)
    - [❌ 不应当](#-不应当)
    - [依赖管理](#依赖管理)
  - [14. 全局事件系统（EventBus）](#14-全局事件系统eventbus)
    - [订阅与取消订阅](#订阅与取消订阅)
    - [内置事件类型一览](#内置事件类型一览)
    - [插件间广播（PLUGIN\_CUSTOM）](#插件间广播plugin_custom)
    - [回调签名约定](#回调签名约定)
  - [15. 插件管理操作](#15-插件管理操作)
    - [15.1 导入插件](#151-导入插件)
    - [15.2 启用与禁用](#152-启用与禁用)
    - [15.3 卸载插件](#153-卸载插件)
  - [16. 画布扩展 API（Canvas Extension API）](#16-画布扩展-apicanvas-extension-api)
    - [16.1 组件类型注册（`register_widget_type` / `unregister_widget_type`）](#161-组件类型注册register_widget_type--unregister_widget_type)
    - [16.2 顶栏按钮工厂（`register_canvas_topbar_btn_factory`）](#162-顶栏按钮工厂register_canvas_topbar_btn_factory)
    - [16.3 画布共享服务（`register_canvas_service`）](#163-画布共享服务register_canvas_service)
    - [16.4 画布布局读写（`apply_canvas_layout` / `get_canvas_layout`）](#164-画布布局读写apply_canvas_layout--get_canvas_layout)
    - [16.5 共享布局预设库插件（`layout_presets`）](#165-共享布局预设库插件layout_presets)
    - [16.6 教育插件示例：考试面板与自习时间安排](#166-教育插件示例考试面板与自习时间安排)


---

## 1. 快速开始

在 `plugins_ext/` 目录下创建一个子目录（即插件包）：

```
plugins_ext/
└── my_plugin/
    ├── plugin.json     ← 清单
    └── __init__.py     ← 插件代码
```

`__init__.py` 最简实现：

```python
from app.plugins import BasePlugin, HookType, PluginAPI, PluginMeta

class Plugin(BasePlugin):
    meta = PluginMeta(id="my_plugin", name="我的插件")

    def on_load(self, api: PluginAPI) -> None:
        self._api = api  # 保存引用，供其他方法使用
        api.register_hook(HookType.ON_ALARM_AFTER, self._alarm_cb)

    def _alarm_cb(self, alarm_id: str) -> None:
        self._api.show_toast("闹钟触发", f"alarm_id = {alarm_id}")
```

启动应用后，插件管理器会自动扫描 `plugins_ext/` 并加载所有符合规范的插件。

---

## 2. 目录结构规范

### 推荐：包形式（功能完整）

```
plugins_ext/
└── my_plugin/                 ← 目录名建议与 plugin.json 中的 id 一致
    ├── plugin.json            ← 清单文件（强烈推荐）
    ├── __init__.py            ← 必须，包含 Plugin 类
    ├── requirements.txt       ← 可选，PyPI 依赖声明
    └── assets/                ← 可选，图标、图片等静态资源
        └── icon.png
```

### 简单：单文件形式

```
plugins_ext/
└── my_plugin.py               ← 包含 Plugin 类，适合极简插件
```

> 插件配置与运行数据统一存储在 `plugins_ext/._data/<plugin_id>/`，例如 `plugins_ext/._data/my_plugin/config.json`。

---

## 3. 清单文件 plugin.json

`plugin.json` 位于插件目录根部，所有字段如下：

```json
{
  "id":               "my_plugin",
  "name":             "我的插件",
    "name_i18n": {
        "zh-CN": "我的插件",
        "en-US": "My Plugin"
    },
  "version":          "1.0.0",
  "author":           "作者名 <email@example.com>",
  "description":      "一句话描述插件功能",
    "description_i18n": {
        "zh-CN": "一句话描述插件功能",
        "en-US": "One-line plugin description"
    },
  "homepage":         "https://github.com/yourname/my_plugin",
    "icon":             "assets/icon.png",
  "plugin_type":      "feature",
  "min_host_version": "0.1.0",
  "requires":         [],
    "dependencies":     ["requests>=2.31.0"],
    "permissions":      ["network", "install_pkg"],
  "tags":             ["notification", "alarm"]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 全局唯一标识符，`snake_case`，全英文小写+数字+下划线 |
| `name` | string \| object | ✅* | 用户可见名称；支持字符串或多语言对象（如 `{\"zh-CN\":\"插件\",\"en-US\":\"Plugin\"}`） |
| `name_i18n` | object | | 名称多语言映射（可选），优先于 `name` 的默认语义 |
| `version` | string | | 语义化版本，默认 `"1.0.0"` |
| `author` | string | | 作者名或邮箱 |
| `description` | string \| object | | 功能描述；支持字符串或多语言对象 |
| `description_i18n` | object | | 描述多语言映射（可选） |
| `homepage` | string | | 项目主页 / 文档 URL |
| `icon` | string | | 插件图标，支持 `data:image/...;base64,...` 或本地图片路径（相对路径按插件目录解析） |
| `plugin_type` | string | | `"feature"`（默认）或 `"library"` |
| `min_host_version` | string | | 要求的最低宿主版本，为空不限制 |
| `requires` | array | | 依赖的其他插件 ID 列表（与 PyPI 包无关）|
| `dependencies` | array | | PyPI 依赖包列表（与 `requirements.txt` 等效）；仅支持标准包名/版本约束，缺失时会在声明了 `install_pkg` 权限后请求用户授权并自动安装 |
| `permissions` | array | | 所需系统权限，首次加载时向用户展示授权确认 |
| `tags` | array | | 分类标签 |

> `plugin.json` 中的元数据会覆盖 `Plugin.meta` 类属性，两者均写时以 `plugin.json` 为准。
>
> `*` 必填规则：`name` 与 `name_i18n` 至少提供一个即可。
>
> `icon` 未配置或加载失败时，插件管理页会显示「主题色纯色背景 + 插件名首字符」（英文字符自动大写）的占位图标。

### 3.1 权限声明（permissions）

插件需要访问敏感系统资源时，**必须**在 `permissions` 字段中声明。
首次加载时宿主会弹出授权确认对话框；用户拒绝后插件将不会被加载。

| 权限值 | 说明 |
|--------|------|
| `"network"` | 发起网络请求（HTTP / WebSocket 等）|
| `"fs_read"` | 读取任意文件路径 |
| `"fs_write"` | 写入或删除任意文件 |
| `"os_exec"` | 执行外部命令（`subprocess` / `os.system`）|
| `"os_env"` | 读写系统环境变量 |
| `"clipboard"` | 读写剪贴板 |
| `"notification"` | 发送系统原生通知 |
| `"install_pkg"` | 允许在启动时自动安装 `dependencies`/`requirements.txt` 中声明的缺失 PyPI 包（用户仍需在弹窗中批准）|

> 插件专属配置目录（`config.json`）和 `plugins_ext/._data/<id>/` 下的数据目录**无需**声明权限，可直接读写。

> ⚠️ **安全说明**：权限系统为**声明式**而非运行时执行沙箱；即插件在加载后可通过普通 Python 代码访问系统资源。
> 因此，请只安装信任来源的插件。

> 🔍 **静态扫描**：宿主在加载插件时会对所有 `.py` 源文件进行简单关键词扫描（检测 `requests`、
> `subprocess`、`os.environ`、`QClipboard` 等典型模式）。若发现代码中使用了但 `permissions`
> 中未声明的权限，会在插件界面弹出警告通知。
>
> **重要限制**：
> - 扫描只覆盖部分已知模式，存在**误报**（误判）和**漏报**（绕过）；
> - 插件可通过动态 `import`、字符串拼接、间接调用等方式规避检测；
> - 扫描结果**仅供参考**，不代表插件实际会或不会执行对应操作；
> - 宿主**无法沙箱隔离**插件，权限声明的意义在于明面上的透明度，而非访问控制。

---

### 3.2 依赖包自动安装机制

应用启动时，管理器会自动检测插件的 Python 依赖包是否已安装。检测来源优先级：

1. 插件目录下的 `requirements.txt`（首选）
2. `plugin.json` 中的 `dependencies` 字段（次选）

> 只有在插件声明了 `install_pkg` 权限时，缺失依赖才会进入自动安装流程。
> 为安全起见，仅支持标准 PyPI 包名 / 版本约束；URL、路径和 pip 选项会被忽略。

**安装流程：**

```
应用启动
    └─ 检测插件 A 是否有缺失包
        ├─ [ 无缺失 ] ─────────────────────────> 直接加载插件
        └─ [ 有缺失 ]
            ├─ 未声明 install_pkg 权限 ───────> 跳过自动安装，继续加载并提示告警
            └─ 已声明 install_pkg 权限
                ├─ 本次允许 / 始终允许 ───────> 自动安装到 plugins_ext/_lib/
                └─ 拒绝 / 安装失败 ───────────> 继续加载并提示相关功能可能不可用
```

**安装目标路径和注意事项：**

- 包被安装到 `plugins_ext/_lib/`，**所有插件**共享。
- `_lib/` 已自动加入 `sys.path`，插件可直接 `import`。
- 打包运行时使用嵌入式 pip（`pip._internal`），无需外部 Python 环境。
- 开发环境下使用 `sys.executable -m pip --target plugins_ext/_lib`。
- 用户选择**始终允许**后，同一插件后续缺失包无需再次确认。
- 若用户拒绝安装、未声明 `install_pkg` 权限或安装失败，管理器会保留告警并继续尝试加载；若插件在模块导入阶段就强依赖这些包，仍可能最终加载失败。

### 3.3 多语言元数据（i18n）

宿主目前支持语言：

- `zh-CN`（简体中文）
- `en-US`（English）

插件名称和描述支持两种写法：

1) 直接写字符串（单语言）

```json
{
    "name": "我的插件",
    "description": "仅中文描述"
}
```

2) 写多语言对象（推荐）

```json
{
    "name": {
        "zh-CN": "我的插件",
        "en-US": "My Plugin"
    },
    "description": {
        "zh-CN": "中文说明",
        "en-US": "English description"
    }
}
```

或使用显式字段 `name_i18n` / `description_i18n`。运行时宿主会根据当前界面语言自动选择最合适的文本。

---

## 4. 主入口类 Plugin

- **类名必须为 `Plugin`**，管理器按此名称查找。
- 继承自 `app.plugins.BasePlugin`。
- `meta` 类属性为回退声明，通常由 `plugin.json` 覆盖。

```python
from app.plugins import BasePlugin, HookType, PluginAPI, PluginMeta

class Plugin(BasePlugin):
    # 回退元数据（无 plugin.json 时生效）
    meta = PluginMeta(
        id          = "my_plugin",
        name        = "我的插件",
        version     = "1.0.0",
        author      = "作者",
        description = "描述",
    )

    def __init__(self):
        self._api: PluginAPI | None = None

    def on_load(self, api: PluginAPI) -> None:
        """插件初始化：注册钩子、读取配置等。"""
        self._api = api
        # ... 注册逻辑

    def on_unload(self) -> None:
        """插件卸载：清理定时器、释放资源等。"""
        pass
```

### 生命周期方法

| 方法 | 调用时机 | 说明 |
|------|----------|------|
| `on_load(api)` | 插件被加载后 | 注册钩子、读取配置、初始化状态 |
| `on_unload()` | 插件被卸载前 | 停止后台线程、清理资源 |
| `create_settings_widget()` | UI 需要时 | 返回设置面板 `QWidget`，可为 `None` |
| `create_sidebar_widget()` | 插件加载后立即调用一次 | 返回侧边栏独立导航页 `QWidget`，可为 `None` |
| `get_sidebar_icon()` | 调用 `create_sidebar_widget()` 后 | 侧边栏图标，支持 `FIF.*` / `QIcon` / 图片路径字符串，`None` 使用默认 |
| `get_sidebar_label()` | 调用 `create_sidebar_widget()` 后 | 侧边栏显示文字，默认为 `meta.name` |

---

## 5. 插件类型（PluginType）

| 类型字段值 | Python 枚举 | 基类 | 适用场景 |
|-----------|-----------|------|----------|
| `"feature"` | `PluginType.FEATURE` | `BasePlugin` | 面向用户的实际功能，可订阅闹钟/计时器钩子、注册自动化动作、扩展 UI |
| `"library"` | `PluginType.LIBRARY` | `LibraryPlugin` | 面向开发者的可复用工具库，不直接面向用户，需实现 `export()` |

> `plugin.json` 中的 `plugin_type` 优先级高于代码中 `meta.plugin_type`。
> 继承 `LibraryPlugin` 时管理器会自动将 `plugin_type` 修正为 `LIBRARY`。

---

## 6. 依赖插件开发（LibraryPlugin）

### 为什么要用依赖插件？

当多个插件需要共享相同的能力（如 HTTP 客户端、数据库连接、地理编码库）时，
可将共享逻辑封装成一个依赖插件，避免代码重复。

### 开发步骤

**第一步：创建依赖插件**

```
plugins_ext/
└── my_lib/
    ├── plugin.json     ← plugin_type: "library"
    └── __init__.py     ← Plugin 继承自 LibraryPlugin
```

`plugin.json`:
```json
{
  "id": "my_lib",
  "name": "My 库",
  "plugin_type": "library",
  "requires": []
}
```

`__init__.py`:
```python
from app.plugins import LibraryPlugin, PluginAPI, PluginMeta, PluginType

class MyLibInterface:
    """公开接口对象（推荐与实现分离）"""
    def do_something(self, data: str) -> str:
        return data.upper()

class Plugin(LibraryPlugin):
    meta = PluginMeta(
        id="my_lib", name="My 库",
        plugin_type=PluginType.LIBRARY,
    )

    def __init__(self):
        self._iface = MyLibInterface()

    def on_load(self, api: PluginAPI) -> None:
        pass  # 无需订阅钩子，或根据需要订阅

    def export(self) -> MyLibInterface:
        """**必须实现**：返回公开接口对象"""
        return self._iface
```

**第二步：功能插件声明依赖并调用**

`plugin.json`:
```json
{
  "id": "my_feature",
  "name": "我的功能",
  "plugin_type": "feature",
  "requires": ["my_lib"]
}
```

`__init__.py`:
```python
from app.plugins import BasePlugin, PluginAPI, PluginMeta

class Plugin(BasePlugin):
    meta = PluginMeta(id="my_feature", name="我的功能", requires=["my_lib"])

    def on_load(self, api: PluginAPI) -> None:
        # 获取依赖插件接口
        lib = api.get_plugin("my_lib")
        if lib is None:
            api.show_toast("初始化失败", "依赖 my_lib 不可用", level="error")
            return
        result = lib.do_something("hello")
        api.show_toast("库返回", result)
```

### 依赖加载顺序

管理器会对所有插件进行 **拓扑排序**：

- `requires` 中声明的依赖一定先于依赖方加载。
- 如果依赖插件加载失败，依赖方也会加载失败并展示错误。
- 循环依赖会被检测并记录警告（不允许）。

### 卸载依赖插件

**卸载依赖插件前，请先卸载所有依赖它的功能插件**，避免运行时出现悬空引用错误。

```python
# 正确卸载顺序：先卸载依赖方，再卸载依赖插件
plugin_manager.unload("my_feature")   # 先卸载依赖方
plugin_manager.unload("my_lib")       # 再卸载依赖插件
```

> `unload()` 不返回值；稳妥的卸载顺序需由业务逻辑保证。已有插件管理界面提供了启用/禁用开关，可用来替代手动卸载，详见「[§14.2 启用与禁用](#142-启用与禁用)」。

---

## 7. PluginAPI 接口参考

`on_load` 传入的 `api` 对象是插件与宿主通信的唯一通道。

### 7.1 钩子注册

钩子让插件可以"监听"宿主内部事件，而无需持有宿主对象的引用。

**注册与取消注册：**

```python
from app.plugins import HookType

def on_load(self, api):
    self._api = api
    # 注册：同一回调可注册到多个钩子类型
    api.register_hook(HookType.ON_ALARM_AFTER,  self._on_alarm)
    api.register_hook(HookType.ON_TIMER_DONE,   self._on_timer_done)
    api.register_hook(HookType.ON_FOCUS_START,  self._on_focus_start)

def on_unload(self):
    # 可选：若插件需要在运行中提前停用能力，可手动注销
    self._api.unregister_hook(HookType.ON_ALARM_AFTER, self._on_alarm)
    self._api.unregister_hook(HookType.ON_TIMER_DONE,  self._on_timer_done)
    self._api.unregister_hook(HookType.ON_FOCUS_START, self._on_focus_start)
```

> 宿主会在插件**禁用、卸载**或 `on_load` **失败回滚**时，自动清理仍残留的钩子注册。
> 手动调用 `unregister_hook` 的主要用途，是在**插件仍保持加载状态**时临时关闭某项能力，
> 或者尽早释放长生命周期对象引用。

**各钩子回调签名：**

| 枚举值 | 触发时机 | 回调签名 |
|--------|----------|----------|
| `ON_ALARM_BEFORE` | 闹钟即将触发（可取消） | `(alarm_id: str) -> bool \| None`<br>返回 `True` 取消本次闹钟 |
| `ON_ALARM_AFTER`  | 闹钟已触发 | `(alarm_id: str) -> None` |
| `ON_TIMER_DONE`   | 计时器归零 | `(timer_id: str) -> None` |
| `ON_STOPWATCH_LAP`| 秒表记圈 | `(lap_time_ms: int) -> None` |
| `ON_FOCUS_START`  | 专注会话开始 | `(session_minutes: int) -> None` |
| `ON_FOCUS_END`    | 专注会话结束 | `(session_minutes: int) -> None` |

**示例 — 取消特定闹钟：**

```python
def _on_alarm(self, alarm_id: str) -> bool | None:
    # 查出闹钟标签
    alarm_svc = self._api.get_service("alarm_service")
    if alarm_svc:
        alarm = alarm_svc.get(alarm_id)
        if alarm and "[静音]" in alarm.label:
            return True   # 告知宿主取消本次触发
    return None           # None / False 均为"不取消"
```

**示例 — 计时器完成时推送通知：**

```python
def _on_timer_done(self, timer_id: str) -> None:
    self._api.show_toast("计时完成", f"计时器 {timer_id} 已归零", level="success")
```

### 7.2 持久化配置

插件配置以 JSON 格式保存在插件专属目录中，**宿主启动时自动加载，写入时立即落盘**。

- **统一路径**：`plugins_ext/._data/<plugin_id>/config.json`

**基本读写：**

```python
# 写入（支持任意 JSON 可序列化值）
api.set_config("enabled",         True)
api.set_config("max_retries",     3)
api.set_config("last_sync",       "2024-01-01T00:00:00")
api.set_config("ignored_ids",     ["abc", "def"])

# 读取（键不存在时返回 default）
enabled  = api.get_config("enabled",     default=True)
retries  = api.get_config("max_retries", default=5)
ids      = api.get_config("ignored_ids", default=[])
```

**点号路径——读写嵌套结构：**

```python
# 写入嵌套键（中间层自动创建）
api.set_config("ui.theme",         "dark")
api.set_config("ui.font_size",     14)
api.set_config("stats.run_count",  api.get_config("stats.run_count", 0) + 1)

# 读取嵌套键
theme     = api.get_config("ui.theme",        default="light")
font_size = api.get_config("ui.font_size",    default=12)
runs      = api.get_config("stats.run_count", default=0)
```

生成的 `config.json` 示例：

```json
{
  "enabled": true,
  "max_retries": 3,
  "ui": {
    "theme": "dark",
    "font_size": 14
  },
  "stats": {
    "run_count": 7
  }
}
```

> **注意事项：**
> - 值必须是 JSON 可序列化类型：`bool`、`int`、`float`、`str`、`list`、`dict`、`None`。
> - 所有读写均在**主线程**执行；如需在后台线程中写配置，请用
>   `QTimer.singleShot(0, lambda: api.set_config(...))` 切回主线程。
> - 请勿直接操作宿主的 `config/` 目录，使用 `api.get_config` / `api.set_config` 以保证隔离。

**插件数据目录：**

当插件需要保存自己的 JSON、缓存文件或素材副本时，请使用公开方法：

```python
data_dir = api.get_data_dir()
data_file = api.resolve_data_path("cache", "last_result.json")
if data_file is not None:
    data_file.write_text("{}", encoding="utf-8")
```

> `get_data_dir()` 返回插件专属目录；`resolve_data_path()` 会自动创建父目录。

### 7.3 用户通知

```python
api.show_toast("标题", "详细内容", level="info")
```

| `level` 值 | 图标 | 含义 | 典型用途 |
|------------|------|------|---------|
| `"info"`    | ℹ（蓝）| 普通信息 | 操作完成、状态更新 |
| `"success"` | ✓（绿）| 操作成功 | 保存成功、任务完成 |
| `"warning"` | ⚠（橙）| 需要注意 | 非致命错误、配置缺失 |
| `"error"`   | ✕（红）| 错误/失败 | 初始化异常、网络失败 |

图标和强调色会根据深色/浅色主题自动适配。

### 7.4 宿主服务访问

```python
alarm_svc = api.get_service("alarm_service")
if alarm_svc:
    alarms = alarm_svc.get_all()
```

可用服务名称：

| 名称 | 类型 | 说明 |
|------|------|------|
| `"alarm_service"` | `AlarmService` | 闹钟管理 |
| `"focus_service"` | `FocusService` | 专注计时 |
| `"settings_service"` | `SettingsService` | 应用设置读写 |
| `"ntp_service"` | `NtpService` | 网络时间同步 |
| `"notification_service"` | `NotificationService` | 系统通知 |
| `"world_zone_service"` | `WorldZoneService` | 只读获取世界时钟 zone 列表、显示名和目标画布信息 |
| `"recommendation_service"` | `RecommendationService` | 推荐打分服务，可注册自定义特征并排序 |
| `"url_scheme_service"` | `url_scheme_service` 模块 | URL 路由注册、URL 构建与解析 |

例如，插件若需要让用户选择“把功能应用到哪个全屏画布”，可以读取 zone 列表：

```python
zone_svc = api.get_service("world_zone_service")
if zone_svc:
    for zone in zone_svc.list_zone_options():
        print(zone["id"], zone["display_name"])
```

```python
from app.plugins import PluginPermission

if api.has_permission(PluginPermission.NOTIFICATION):
    notif = api.get_service("notification_service")
    if notif:
        notif.show("插件提醒", "这是一条系统通知")
```

也可以在真正需要时再申请：

```python
from app.plugins import PluginPermission

if not api.has_permission(PluginPermission.NOTIFICATION):
    api.request_permission(
        PluginPermission.NOTIFICATION,
        reason="仅在规则触发时发送系统通知，平时不会访问通知能力。",
    )

notif = api.get_service("notification_service")
if notif:
    notif.show("插件提醒", "现在可以发送通知了")
```

> 对权限敏感的宿主服务（如 `notification_service`、`ntp_service`），若插件未获得相应权限，`get_service()` 会返回 `None`。
> `world_zone_service` 是宿主提供的只读辅助服务，不涉及额外系统权限，适合用于目标画布选择、zone 显示名称解析等场景。
> `recommendation_service` 与 `url_scheme_service` 用于功能扩展（首页卡片推荐、URL 深链注册），默认无需额外系统权限。
> `request_permission()` 仅适用于插件**已声明**的系统权限；`install_pkg` 仍只用于启动阶段依赖安装，不支持在运行期动态申请。
> 启动期权限审查、运行期 `request_permission()` 决策，以及手动修改权限设置，都会追加到 `plugins_ext/._data/plugin_permission_audit.jsonl`；插件管理界面也会展示最近几条记录，便于排查权限变化来源。

### 7.5 依赖插件访问

```python
lib = api.get_plugin("my_lib_id")
if lib is None:
    # 依赖不可用，根据需要降级运行或退出
    return
result = lib.some_method()
```
返回为目标插件 `export()` 的返回对象。未加载、未启用或未实现 `export()` 时返回 `None`；
除了库型插件（`plugin_type = library`），功能插件若显式提供 `export()` 也可被依赖方获取。

### 7.6 自动化扩展

**声明触发器（带可选名称）：**

```python
# 基础用法（ID 将直接显示在 UI 中）
api.register_trigger("my_plugin.event")

# 推荐：提供用户可见名称和说明
api.register_trigger(
    "my_plugin.event",
    name="我的插件：事件名称",
    description="当 XXX 条件满足时触发",
)

# 多语言名称/描述（推荐）
api.register_trigger(
    "my_plugin.event",
    name="我的插件：事件名称",  # 回退文案
    description="当 XXX 条件满足时触发",  # 回退文案
    name_i18n={
        "zh-CN": "我的插件：事件名称",
        "en-US": "My Plugin: Event Name",
    },
    description_i18n={
        "zh-CN": "当 XXX 条件满足时触发",
        "en-US": "Triggered when condition XXX is met",
    },
)
```

> 注册后，用户在「自动化 → 编辑规则 → 触发器」的下拉列表中会看到 **`名称（trigger_id）`** 格式的选项。
> 若插件被删除，已使用该触发器的规则会在列表中显示为「⚠ 未知触发器（trigger_id）」。

> `name_i18n` / `description_i18n` 会根据宿主当前语言自动显示；未命中时回退到 `name` / `description`。

**主动触发自动化规则：**

```python
# 当条件满足时，调用此方法驱动匹配规则执行
api.fire_trigger("my_plugin.event", extra_key=value)
```

**注册自定义动作：**

```python
api.register_action("my_plugin.do_something", self._execute_action)
```

动作执行器签名为 `(params: dict) -> None`，可选接收第二参数 `context: dict`：

```python
# 简洁写法：只接收 params
def _execute_action(self, params: dict) -> None:
    message = params.get("message", "默认文本")
    self._api.show_toast("动作执行", message)

# 完整写法：同时接收运行时上下文
def _execute_action(self, params: dict, context: dict) -> None:
    """
    params  — 用户在规则编辑器中填写的参数字典
    context — 触发事件时携带的运行时上下文（如 alarm_id）
    """
    message = params.get("message", "默认文本")
    self._api.show_toast("动作执行", message)
```

> 宿主自动检测执行器的参数个数：如果只声明了 `params`，则不传入 `context`；如果同时声明了 `params` 和 `context`，则两者均会传入。两种写法均属支持的合法用法。

**动态注销（可选）：**

```python
api.unregister_trigger("my_plugin.event")
api.unregister_action("my_plugin.do_something")
```

> 宿主会在插件**禁用、卸载**或 `on_load` **失败回滚**时，自动移除仍注册的自定义触发器/动作。
> 显式注销更适合用于运行中临时关闭某个触发器或动作，而不是等待整个插件卸载。

### 7.7 全局事件订阅

通过 `subscribe_event` 订阅宿主发出的内置事件，插件卸载时自动解除：

```python
from app.events import EventType

def on_load(self, api):
    self._api = api
    api.subscribe_event(EventType.ALARM_FIRED, self._on_alarm)
    api.subscribe_event(EventType.FULLSCREEN_CLOSED, self._on_fullscreen_closed)

def _on_alarm(self, alarm_id: str = "", **_):
    self._api.show_toast("闹钟触发", alarm_id)

def _on_fullscreen_closed(self, zone_id: str = "", **_):
    self._stop_background_monitor()
```

> 完整事件类型列表与 payload 说明见「[§13 全局事件系统](#13-全局事件系统eventbus)」。

### 7.8 启动参数与宿主上下文

插件可读取本次启动上下文，并注册只对自己生效的自定义启动参数。

```python
def on_load(self, api):
    self._api = api

    ctx = api.get_startup_args()
    if ctx["hidden_mode"]:
        # 隐藏启动时延迟初始化重量级 UI
        return

    api.register_startup_arg(
        "my-plugin.target",
        self._on_target,
        default="dev",
        help="切换插件运行目标环境",
    )
    api.register_startup_arg(
        "my-plugin.verbose",
        self._on_verbose,
        action="store_true",
    )

def _on_target(self, value: str):
    self._target = value

def _on_verbose(self):
    self._verbose = True
```

启动示例：

```bash
uv run main.py --extra-args "--my-plugin.target prod --my-plugin.verbose"
```

**上下文字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `hidden_mode` | `bool` | 是否以隐藏模式启动 |
| `extra_args` | `str` | 原始 `--extra-args` 字符串 |

**建议：**

- 参数名使用插件 ID 前缀，例如 `my-plugin.verbose`，避免与其他插件冲突。
- 只有通过 `register_startup_arg()` 注册过的参数才会被解析并分发给处理器。
- 启动参数会在**所有插件完成 `on_load` 之后**统一解析，因此适合做“延迟决定”的初始化逻辑。
- 每个插件实例的启动参数只会在一次应用启动流程中派发一次；重新扫描不会重复触发已完成的处理器。

### 7.9 语言与 i18n 辅助

插件可以复用宿主当前语言信息：

```python
lang = api.current_language()
title = api.tr("plugin.title", default="插件")
```

常用方式：

- 使用 `api.current_language()` 决定插件自身 UI 文案、日期格式或默认资源。
- 使用 `api.tr()` 复用宿主已有的公共文案键，避免重复定义简单提示语。
- 对插件元数据和自动化触发器名称，优先使用 `name_i18n` / `description_i18n` 声明式多语言字段。

### 7.10 时间工具

插件应使用 `api.get_corrected_time()` 获取当前时间，而不是 `datetime.now()`，以确保在调试模式下与宿主保持一致。

```python
def on_load(self, api):
    self._api = api

    # 获取校正后的本地时间（推荐）
    local_now = api.get_corrected_time()

    # 获取校正后的 UTC 时间
    utc_now = api.get_corrected_utc()

    # 获取指定时区的时间
    shanghai_time = api.get_corrected_time("Asia/Shanghai")
```

**为什么需要使用校正时间？**

1. **NTP 校正**：若用户启用了 NTP 时间同步，`get_corrected_time()` 会返回网络校准后的时间
2. **调试偏移**：用户可在设置或调试面板中设置时间偏移（按秒），用于测试特殊场景（如跨天、跨月）
3. **一致性**：插件与宿主使用相同的时间基准，避免时间相关功能出现偏差

**时间偏移控制：**

```python
# 获取当前时间偏移（秒）
offset = api.get_time_offset_seconds()

# 设置时间偏移（仅影响通过 API 获取的时间）
api.set_time_offset_seconds(3600)  # 时间提前 1 小时
```

**在服务层中使用：**

如果插件有服务层（Service），建议添加 `_now()` 方法统一获取时间：

```python
class MyService(QObject):
    def __init__(self, api, ...):
        self._api = api

    def now(self) -> datetime:
        """获取校正后的当前时间（公开 API）。"""
        return self._api.get_corrected_time()

    def _now(self) -> datetime:
        """获取校正后的当前时间（内部使用）。"""
        return self._api.get_corrected_time()
```

### 7.11 首页卡片与推荐扩展

插件可通过 `PluginAPI` 向首页注入自定义卡片，并复用宿主推荐引擎进行特征打分。

**1) 注册首页卡片工厂**

```python
def on_load(self, api):
    self._api = api
    api.register_home_card_factory(self._make_home_card, slot="recommend", order=80)

def on_unload(self):
    self._api.unregister_home_card_factory(self._make_home_card)

def _make_home_card(self, ctx: dict):
    """
    ctx 包含：
      - navigate: Callable[[str], None]
      - recommendation_service
      - i18n
      - 其他常用运行时对象（timer/focus/clock 等）
    返回 QWidget（或 QWidget 列表）即可。
    """
    from qfluentwidgets import CardWidget, BodyLabel
    from PySide6.QtWidgets import QVBoxLayout

    card = CardWidget()
    lay = QVBoxLayout(card)
    lay.addWidget(BodyLabel("来自插件的首页卡片"))
    return card
```

`slot` 支持：

- `"top"`：问候卡之后、主推荐之前
- `"recommend"`：推荐区域
- `"extra"`：小贴士/统计区域

`order` 越小越靠前。

**2) 注册并打分自定义推荐特征**

```python
def on_load(self, api):
    self._api = api
    api.register_recommendation_feature("my_plugin.daily_review", "每日复习")

def on_user_open_review(self):
    self._api.record_recommendation_view("my_plugin.daily_review")

def on_review_start(self):
    self._api.record_recommendation_session_start("my_plugin.daily_review")

def on_review_end(self):
    self._api.record_recommendation_session_end("my_plugin.daily_review")

def get_rank(self):
    return self._api.rank_recommendation_features([
        "my_plugin.daily_review",
        "my_plugin.quick_quiz",
    ])
```

> 推荐特征可用于插件内部排序、卡片展示优先级等。内置特征（如 `timer`、`focus`）仍由宿主首页逻辑使用。

### 7.12 URL Scheme 路由扩展

插件可注册新的 `ltclock://open/<view_key>` 路由，指向一个已存在的 `objectName` 视图。

```python
def on_load(self, api):
    self._api = api
    # 例如：ltclock://open/study_schedule -> pluginSidebar_study_schedule
    ok = api.register_url_scheme_view(
        "study_schedule",
        "pluginSidebar_study_schedule",
    )
    if not ok:
        api.show_toast("URL 路由注册失败", level="warning")

def on_unload(self):
    self._api.unregister_url_scheme_view("study_schedule")
```

补充说明：

- 注册成功后，可通过外部链接直接唤起该视图。
- 插件卸载时，宿主会自动清理本插件注册的 URL 路由（即使插件未手动注销）。
- 宿主内置全屏时钟路由为 `ltclock://fullscreen/<zone_id>`，用户可在世界时间卡片「更多」菜单中复制。

### 7.13 布局文件打开扩展

插件可在用户打开 `.ltlayout` 文件时，向「打开方式」列表注册自定义动作。

核心方法：

- `api.register_layout_open_action(...)`
- `api.unregister_layout_open_action(action_id)`

基础示例：

```python
from pathlib import Path
from app.plugins import BasePlugin, PluginAPI, PluginMeta


class Plugin(BasePlugin):
    meta = PluginMeta(id="my_layout_tool", name="布局工具")

    def on_load(self, api: PluginAPI) -> None:
        self._api = api
        api.register_layout_open_action(
            action_id="my_layout_tool.import_as_template",
            title="导入为模板",
            title_i18n={"zh-CN": "导入为模板", "en-US": "Import as Template"},
            description="将布局文件保存为模板",
            description_i18n={
                "zh-CN": "将布局文件保存为模板",
                "en-US": "Save layout file as a reusable template",
            },
            order=50,
            breadcrumb=["插件扩展", "布局工具"],
            handler=self._handle_open_layout,
            wizard_pages=[
                {
                    "type": "text",
                    "title": "模板信息",
                    "title_i18n": {"zh-CN": "模板信息", "en-US": "Template Info"},
                    "description": "请输入模板名称。",
                    "description_i18n": {
                        "zh-CN": "请输入模板名称。",
                        "en-US": "Please enter a template name.",
                    },
                    "field": "template_name",
                    "label": "模板名称",
                    "label_i18n": {"zh-CN": "模板名称", "en-US": "Template Name"},
                    "placeholder": "例如：晚自习布局",
                    "required": True,
                }
            ],
        )

    def on_unload(self) -> None:
        self._api.unregister_layout_open_action("my_layout_tool.import_as_template")

    def _handle_open_layout(
        self,
        file_path: Path,
        *,
        parent=None,
        context: dict | None = None,
    ) -> bool:
        template_name = str((context or {}).get("template_name") or "").strip()
        if not template_name:
            self._api.show_toast("模板名称不能为空", level="warning")
            return False

        # 在这里处理 file_path
        self._api.show_toast("导入成功", f"已保存模板：{template_name}", level="success")
        return True
```

`register_layout_open_action` 常用参数：

- `action_id`：动作唯一 ID，建议使用 `{plugin_id}.{name}`。
- `title` / `title_i18n`：显示在第一步列表中的名称。
- `description` / `description_i18n`：显示在列表「内容说明」列的文案。
- `handler`：执行入口，推荐签名 `handler(file_path: Path, *, parent=None, context=None)`。
- `order`：排序值，越小越靠前。
- `breadcrumb`：来源路径（字符串或字符串列表）。
- `wizard_pages`：可选动态向导定义。

`wizard_pages` 支持两种形式：

- 直接传 `list[dict]`。
- 传 `Callable[[Path], list[dict]]`，按文件路径动态生成步骤。

页面类型与字段：

- `type="info"`：展示说明。
- `type="text"`：文本输入，支持 `field`、`required`、`placeholder`、`default`、`max_length`、`empty_error`。
- `type="select"`：单选列表，支持 `field`、`required`、`options`、`default`、`empty_text`、`empty_error`。

可本地化字段（宿主自动识别）：

- 页面级：`title_i18n`、`description_i18n`、`content_i18n`、`label_i18n`、`placeholder_i18n`、`empty_text_i18n`、`empty_error_i18n`。
- `select.options` 级：`label_i18n`、`description_i18n`。

说明：

- 当向导完成后，宿主会将用户填写结果以 `context` 字典透传给 `handler`。
- 插件卸载/禁用时，宿主会自动清理该插件注册的布局打开动作。

---

## 8. 钩子（HookType）列表

| 枚举值 | 触发时机 | 回调签名 |
|--------|----------|----------|
| `ON_ALARM_AFTER` | 闹钟触发后 | `(alarm_id: str) -> None` |
| `ON_ALARM_BEFORE` | 闹钟即将触发（可取消） | `(alarm_id: str) -> bool \| None` |
| `ON_TIMER_DONE` | 计时器归零 | `(timer_id: str) -> None` |
| `ON_STOPWATCH_LAP` | 秒表记圈 | `(lap_time_ms: int) -> None` |
| `ON_FOCUS_START` | 专注会话开始 | `(session_minutes: int) -> None` |
| `ON_FOCUS_END` | 专注会话结束 | `(session_minutes: int) -> None` |
| `ON_LOAD` | 插件加载后（内部） | `() -> None` |
| `ON_UNLOAD` | 插件卸载前（内部） | `() -> None` |

---

## 9. 自动化集成

插件可以将自己的事件暴露为**自动化触发器**，用户无需了解技术细节，只需在规则编辑界面的下拉列表中选择触发器即可。

### 基本步骤

**第一步：在 `on_load` 中注册触发器，提供人性化名称**

```python
def on_load(self, api: PluginAPI) -> None:
    self._api = api
    # 名称将显示在自动化规则编辑界面的下拉列表中
    api.register_trigger(
        "my_plugin.threshold_exceeded",
        name="我的插件：超过阈值",
        description="当检测值超过设定阈值时触发",
    )
    # 也可注册自定义动作（由规则调用）
    api.register_action("my_plugin.send_alert", self._send_alert)
```

**第二步：在条件满足时调用 `fire_trigger`**

```python
def _on_value_changed(self, value: float) -> None:
    if value > self._threshold:
        # 驱动所有匹配该触发器 ID 的自动化规则执行
        self._api.fire_trigger(
            "my_plugin.threshold_exceeded",
            value=value,           # 可传递任意上下文键值对
            threshold=self._threshold,
        )

def _send_alert(self, params: dict) -> None:
    self._api.show_toast("插件提醒", params.get("message", ""), level="warning")
```

**用户配置流程：**

1. 打开「自动化」→「规则列表」→「新建规则」
2. 触发器：选择「[插件] 自定义触发器」
3. 触发器下拉中选择「我的插件：超过阈值（my_plugin.threshold_exceeded）」
4. 添加所需动作 → 保存

> **插件删除后：** 已使用该触发器的规则不会被删除，但触发器显示为「⚠ 未知触发器（trigger_id）」。
> 重新启用插件后会自动恢复正常显示。

触发器 ID 和动作 ID **建议使用 `{plugin_id}.{name}` 格式**，避免与其他插件冲突。

---

## 10. 组件右键菜单与分离窗口

### 10.1 自定义右键菜单

组件可以通过重写 `get_context_menu_actions()` 方法添加自定义右键菜单项。

```python
from qfluentwidgets import FluentIcon as FIF
from app.widgets.base_widget import WidgetBase

class MyWidget(WidgetBase):
    def get_context_menu_actions(self):
        """返回自定义右键菜单项列表"""
        return [
            ("刷新", FIF.SYNC, self._on_refresh),
            ("分享", FIF.SHARE, self._on_share),
            ("帮助", None, self._on_help),  # icon 可为 None
        ]

    def _on_refresh(self):
        self.refresh()

    def _on_share(self):
        # 分享逻辑
        pass

    def _on_help(self):
        # 帮助逻辑
        pass
```

**返回格式：** `List[Tuple[str, FluentIcon | None, Callable]]`
- 文本：菜单项显示文字
- 图标：`qfluentwidgets.FluentIcon` 枚举值或 `None`
- 回调：无参函数

**菜单显示顺序：**
1. 自定义菜单项（排在最前面）
2. 编辑（若有）
3. 分离为窗口
4. 删除（若有）

### 10.2 分离为置顶窗口

用户可以通过右键菜单选择「分离为窗口」，将组件从画布中分离出来，变为一个独立的置顶窗口。

**功能特性：**
- 始终置顶显示
- 支持拖拽移动
- 拖拽释放后自动吸附到网格
- 半透明黑底背景（若组件未自定义背景样式）
- 支持自定义右键菜单
- 可通过右键菜单「合并到画布」返回原位置

**组件自定义样式处理：**
- 若组件已有自定义背景样式，则保持原样式
- 若组件未设置背景，则使用半透明黑底 (`rgba(0, 0, 0, 0.75)`)

---

## 11. 持久化配置

插件配置自动保存在 `plugins_ext/._data/<plugin_id>/config.json`。

**支持点号路径的嵌套读写：**

```python
# 写入嵌套结构
api.set_config("ui.theme", "dark")
api.set_config("stats.alarm_count", 0)

# 读取嵌套值，不存在时返回默认值
theme = api.get_config("ui.theme", default="light")
count = api.get_config("stats.alarm_count", default=0)
```

生成的 `config.json` 示例：

```json
{
  "ui": { "theme": "dark" },
  "stats": { "alarm_count": 5 }
}
```

> 请勿在插件中直接读写宿主的 `config/` 目录，配置隔离是插件稳定运行的基础。

---

## 12. UI 扩展点

### 12.1 设置面板

在 `Plugin` 类中重写 `create_settings_widget()`，返回一个 `QWidget`。
宿主会将其嵌入「设置 → 插件配置」区域。

```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

def create_settings_widget(self) -> QWidget:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.addWidget(QLabel("插件专属设置"))
    # ... 添加控件
    return w
```

### 12.2 侧边栏面板

插件可以向主窗口左侧导航栏**注入一个完整的顶级面板**，与内置的「闹钟」「计时器」等功能页面平级显示。

**效果：** 宿主加载插件时，自动在侧边栏新增一个导航条目（带图标和文字）；卸载插件时，条目自动移除。

#### 实现步骤

**第一步：重写 `create_sidebar_widget()`**

```python
from PySide6.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import BodyLabel

class Plugin(BasePlugin):
    meta = PluginMeta(id="my_plugin", name="我的插件")

    def create_sidebar_widget(self) -> QWidget:
        """返回侧边栏面板，返回 None 则不注册导航条目"""
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(BodyLabel("这是插件面板内容"))
        # ... 添加更多控件
        return w
```

> **注意**：`create_sidebar_widget()` 在插件整个运行期间**只会被调用一次**，返回的 widget 会被持久持有。
> 不要在此处做耗时初始化，耗时操作应放在 `on_load()` 中完成。

---

**第二步：自定义图标**

重写 `get_sidebar_icon()`，支持三种图标来源：

**方式 A — 使用 FluentIcon 内置图标（推荐，矢量无损）：**

```python
from qfluentwidgets import FluentIcon as FIF

def get_sidebar_icon(self):
    return FIF.MUSIC  # 使用内置 FluentIcon 枚举值
```

> 完整图标列表：https://qfluentwidgets.com/zh/price/icons

**方式 B — 使用插件目录内的自定义图片：**

```python
from pathlib import Path

def get_sidebar_icon(self):
    # 相对于插件 __init__.py 所在目录的路径
    icon_path = Path(__file__).parent / "assets" / "icon.png"
    return str(icon_path)  # 返回绝对路径字符串
```

> 支持 **PNG、SVG、ICO** 格式；建议提供 256×256 甚至更高分辨率的图片，
> 侧边栏会自动缩放。

**方式 C — 使用 QIcon 对象：**

```python
from PySide6.QtGui import QIcon

def get_sidebar_icon(self):
    return QIcon(":/icons/my_icon.png")  # Qt 资源文件或任意路径
```

**不重写时默认使用 `FIF.APPLICATION` 图标。**

---

**第三步：自定义显示文字**

重写 `get_sidebar_label()` 即可改变侧边栏中显示的文字：

```python
def get_sidebar_label(self) -> str:
    return "我的面板"  # 不重写则默认显示 meta.name
```

> 文字建议简短（≤ 5 字），过长会被截断显示。

---

#### 完整示例

```python
from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from qfluentwidgets import BodyLabel, CardWidget, FluentIcon as FIF

from app.plugins import BasePlugin, PluginAPI, PluginMeta


class Plugin(BasePlugin):
    meta = PluginMeta(id="my_panel", name="示例面板")

    def on_load(self, api: PluginAPI) -> None:
        self._api = api

    # ── 侧边栏图标：使用插件目录下的图片 ──
    def get_sidebar_icon(self):
        return str(Path(__file__).parent / "assets" / "panel_icon.png")

    # ── 侧边栏文字 ──
    def get_sidebar_label(self) -> str:
        return "示例面板"

    # ── 面板内容 ──
    def create_sidebar_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 24, 24, 24)

        layout.addWidget(BodyLabel("🎉 这是我的插件面板"))

        btn = QPushButton("点击触发通知")
        btn.clicked.connect(lambda: self._api.show_toast("插件面板", "按钮被点击了"))
        layout.addWidget(btn)

        layout.addStretch()
        return w
```

目录结构：

```
plugins_ext/
└── my_panel/
    ├── __init__.py        ← 上方代码
    ├── plugin.json
    └── assets/
        └── panel_icon.png ← 256×256 PNG
```

---

#### 注意事项

| 事项 | 说明 |
|------|------|
| 初始化时机 | 插件加载完成后立即注入；应用启动时所有插件加载完成后，导航栏中会依次出现各插件条目 |
| 动态刷新 | 重载插件（禁用后重新启用）会先移除旧条目，再重新注入 |
| 多个面板 | 同一插件只能注册**一个**侧边栏面板（`create_sidebar_widget` 只调用一次）|
| 图标缺失 | 若 `get_sidebar_icon()` 返回的路径不存在，宿主会记录警告并回退到默认图标 |
| 与设置面板的区别 | 设置面板嵌入「设置 → 插件配置」区域，侧边栏面板是**独立导航页**，适合功能丰富的插件 |

### 12.3 画布小组件（WidgetBase）

插件可以向**全屏时钟画布**注册可拖动、可编辑的小组件。
用户在画布编辑模式下，从「＋ 添加组件」菜单中选择并放置，就像内置的时钟、计时器组件一样。

**第一步：创建小组件类，继承 `WidgetBase`**

```python
from typing import Any
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, SpinBox
from app.widgets.base_widget import WidgetBase, WidgetConfig

_DEFAULTS = {"text": "默认文字", "font_size": 16}

# ── 编辑面板（可选，返回 None 表示不可编辑）──────────────────────────
class _EditWidget(QWidget):
    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._size = SpinBox()
        self._size.setRange(8, 72)
        self._size.setValue(props.get("font_size", _DEFAULTS["font_size"]))
        layout.addWidget(self._size)

    def collect_props(self) -> dict:
        return {"font_size": self._size.value()}


# ── 小组件主类 ─────────────────────────────────────────────────────
class MyWidget(WidgetBase):
    WIDGET_TYPE  = "my_plugin.my_widget"   # 全局唯一，建议用 {plugin_id}.{name}
    WIDGET_NAME  = "我的组件"               # 显示在「添加组件」菜单
    DELETABLE    = True
    MIN_W, MIN_H         = 2, 1
    DEFAULT_W, DEFAULT_H = 3, 2

    def __init__(self, config: WidgetConfig, services: dict[str, Any], parent=None):
        super().__init__(config, services, parent)
        self._label = BodyLabel("", self)
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)

    @property
    def _props(self) -> dict:
        return self.config.props

    def _get(self, key: str) -> Any:
        return self._props.get(key, _DEFAULTS.get(key))

    def refresh(self) -> None:
        """每秒由画布自动调用，更新显示内容"""
        self._label.setText(self._get("text"))
        font = self._label.font()
        font.setPointSize(self._get("font_size"))
        self._label.setFont(font)

    def get_edit_widget(self) -> QWidget:
        return _EditWidget(self._props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.refresh()
```

**`services` 字典可用的键：**

| 键 | 说明 |
|----|------|
| `"timezone"` | 当前时区字符串（如 `"Asia/Shanghai"`）|
| `"clock_service"` | `ClockService`，可连接 `secondTick` 信号实现每秒刷新 |
| `"notification_service"` | `NotificationService`，可发送通知 |

**第二步：在 `on_load` 中注册**

```python
def on_load(self, api):
    self._api = api
    api.register_widget_type(MyWidget)
```

注册后，用户即可在全屏画布的「＋ 添加组件」菜单中找到「我的组件」并添加到画布。

> **自动清理：** 插件卸载时，管理器会追踪并从注册表移除该插件注册的所有小组件类型。
> 已放置在画布上的实例不会立即消失，但下次保存布局后失效。

---

## 13. 注意事项与最佳实践

### ✅ 应当

- 主类名严格使用 `Plugin`
- 依赖插件主类继承 `LibraryPlugin`，并实现 `export()`
- 在 `plugin.json` 的 `requires` 中声明插件依赖，同时在 `meta.requires` 中同步声明
- 在 `__init__` 中仅做轻量初始化（不访问 `api`）
- 在 `on_load` 中保存 `api` 引用：`self._api = api`
- 使用 `api.get_config` / `api.set_config` 持久化所有插件数据
- 在 `on_unload` 中停止所有后台线程和定时器
- 在钩子/事件回调中捕获内部异常，不向外抛出
- 依赖插件的 `export()` 返回专门接口对象（而不是直接暴露 `self`）
- 画布小组件的 `WIDGET_TYPE` 使用 `{plugin_id}.{name}` 格式
- 在需要系统权限时，在 `plugin.json` 的 `permissions` 字段中声明
- 侧边栏图标优先使用 `FIF.*` 内置矢量图标；使用图片时提供 256×256 以上分辨率
- `create_sidebar_widget()` 只做 UI 构建，避免耗时初始化（应在 `on_load` 中完成）

### ❌ 不应当

- 直接导入宿主内部模块（如 `from app.services.alarm_service import AlarmService`）
- 直接读写 `config/` 目录下的宿主配置文件
- 在 `on_load` 中执行耗时操作（会阻塞 UI 启动）
- 使用与其他插件相同的触发器/动作 ID 或 `WIDGET_TYPE`（可能冲突）
- 依赖插件直接修改 UI 状态
- 未在 `plugin.json` 的 `requires` 中声明依赖就调用 `api.get_plugin()`
- 在类体（`__init__` 之外）进行有副作用的 Qt 操作
- 在画布小组件 `refresh()` 中执行网络请求或耗时 I/O（会阻塞主线程）
- `create_sidebar_widget()` 中存储 widget 实例并在 `on_unload` 中尝试手动移除（宿主会自动清理）

### 依赖管理

在 `requirements.txt` 中声明所需 PyPI 包（这是首选方式）：

```
requests>=2.31.0
pillow>=10.0.0
```

或者在 `plugin.json` 的 `dependencies` 字段中声明（与 `requirements.txt` 等效）：

```json
{
  "dependencies": ["requests>=2.31.0", "pillow>=10.0.0"]
}
```

> **依赖包仅在插件声明了 `install_pkg` 权限时才会自动安装。**
> 管理器检测到缺失包后会展示授权对话框，用户确认后自动安装到 `plugins_ext/_lib/`。
> 为安全起见，依赖声明只支持标准 PyPI 包名 / 版本约束；URL、路径和 pip 选项会被忽略。
> 详细流程见「[§3.2 依赖包自动安装机制](#32-依赖包自动安装机制)」。

---

*更多示例参见 `plugins_ext/example_lib/`（依赖插件）和 `plugins_ext/example_plugin/`（功能插件）。*

---

## 14. 全局事件系统（EventBus）

宿主提供了一个**全局事件总线**，允许插件订阅应用内发生的各类事件。
事件在发出时会携带上下文数据（payload），插件回调在主线程中被安全调用（线程安全）。

### 订阅与取消订阅

```python
from app.events import EventType

def on_load(self, api):
    self._api = api
    # 订阅事件（插件卸载时自动取消）
    api.subscribe_event(EventType.FULLSCREEN_CLOSED, self._on_fullscreen_closed)
    api.subscribe_event(EventType.TIMER_DONE, self._on_timer_done)

def on_unload(self):
    # 也可以手动取消（卸载时会自动清理，此处仅做演示）
    self._api.unsubscribe_event(EventType.FULLSCREEN_CLOSED, self._on_fullscreen_closed)

def _on_fullscreen_closed(self, zone_id: str = "", **_):
    """全屏时钟关闭时停止后台任务"""
    self._stop_background_task()

def _on_timer_done(self, timer_id: str = "", label: str = "", **_):
    """某个计时器归零时触发"""
    self._api.show_toast("计时结束", f"{label} 已归零")
```

> **自动清理：** 通过 `api.subscribe_event` 注册的所有订阅，在插件被卸载时会自动取消，无需手动管理。

### 内置事件类型一览

| 事件类型 | 值 | 触发时机 | payload 键 |
|----------|----|--------|------------|
| `APP_STARTUP` | `app.startup` | 应用启动完成（服务已就绪） | — |
| `APP_SHUTDOWN` | `app.shutdown` | 应用即将退出 | — |
| `APP_SHOWN` | `app.shown` | 主窗口从托盘恢复显示 | — |
| `APP_HIDDEN` | `app.hidden` | 主窗口隐藏到系统托盘 | — |
| `FULLSCREEN_OPENED` | `fullscreen.opened` | 全屏时钟打开 | `zone_id: str` |
| `FULLSCREEN_CLOSED` | `fullscreen.closed` | 全屏时钟关闭 | `zone_id: str` |
| `ALARM_FIRED` | `alarm.fired` | 闹钟触发 | `alarm_id: str` |
| `TIMER_STARTED` | `timer.started` | 计时器开始 | `timer_id`, `label`, `total_ms` |
| `TIMER_PAUSED` | `timer.paused` | 计时器暂停 | `timer_id`, `label` |
| `TIMER_RESET` | `timer.reset` | 计时器重置 | `timer_id`, `label` |
| `TIMER_DONE` | `timer.done` | 计时器归零 | `timer_id`, `label` |
| `FOCUS_STARTED` | `focus.started` | 专注会话开始 | `total_cycles: int`, `preset_name: str` |
| `FOCUS_ENDED` | `focus.ended` | 专注会话全部完成 | — |
| `FOCUS_PHASE_CHANGED` | `focus.phase_changed` | 专注阶段切换 | `phase: str`, `cycle_index: int` |
| `FOCUS_DISTRACTED` | `focus.distracted` | 检测到不专注超限 | `distracted_sec: int` |
| `PLUGIN_LOADED` | `plugin.loaded` | 某插件加载成功 | `plugin_id: str`, `name: str` |
| `PLUGIN_UNLOADED` | `plugin.unloaded` | 某插件被卸载 | `plugin_id: str`, `name: str` |
| `AUTOMATION_TRIGGERED` | `automation.triggered` | 自动化规则执行完毕 | `rule_id`, `rule_name`, `ok: bool` |
| `PLUGIN_CUSTOM` | `plugin.custom` | 插件向其他插件广播自定义事件 | `event_key: str`, `source_plugin: str`, `**data` |

### 插件间广播（PLUGIN_CUSTOM）

任意插件可以通过 `PLUGIN_CUSTOM` 向全局广播自定义事件，实现插件间松耦合通信：

```python
from app.events import EventBus, EventType

# 发送方
EventBus.emit(
    EventType.PLUGIN_CUSTOM,
    event_key="my_plugin.data_ready",
    source_plugin="my_plugin",
    result=42,
)

# 接收方（在 on_load 中订阅）
def _on_custom(self, event_key="", source_plugin="", **data):
    if event_key == "my_plugin.data_ready":
        print("收到数据：", data.get("result"))
```

### 回调签名约定

所有回调均以 `**kwargs` 形式接收 payload，建议使用命名参数 + `**_` 接收多余字段：

```python
def _on_alarm(self, alarm_id: str = "", **_):
    ...

def _on_phase_changed(self, phase: str = "", cycle_index: int = 0, **_):
    ...
```
---

## 15. 插件管理操作

本节说明如何在运行时管理插件（对应宿主内置的「插件管理」界面所提供的能力）。

### 15.1 导入插件

将第三方插件安装到 `plugins_ext/` 目录，支持两种来源：

**方式一：LTCPLUGIN 插件包（本质 ZIP）**

```
my_plugin-1.0.0.ltcplugin
└── my_plugin/
    ├── plugin.json
    ├── __init__.py
    └── requirements.txt
```

通过插件管理界面点击「导入插件」并选择 `.ltcplugin` 文件，系统会：
1. 安全校验压缩包内部路径（防止路径穿越攻击）
2. 解压到 `plugins_ext/<plugin_dir>/`
3. 自动触发重新扫描加载

> 要求插件包内必须有且仅有一个顶层文件夹（如 `my_plugin/`），且该目录包含 `__init__.py`。

**方式二：目录直接复制**

将插件文件夹直接复制到 `plugins_ext/` 下，满足以下结构即可：

```
plugins_ext/
└── my_plugin/
    ├── __init__.py        ← 必须存在
    └── plugin.json        ← 强烈推荐
```

**插件 ID 命名约束**

`plugin.json` 中的 `id` 字段（或目录名作为回退 ID）必须满足：
- 以小写字母开头
- 仅含小写字母（`a-z`）、数字（`0-9`）和下划线（`_`）
- 总长度不超过 64 字符

**示例：** `my_plugin`、`http_lib`、`weather_v2` ✅ &nbsp;&nbsp;`MyPlugin`、`my-plugin`、`../evil` ❌

不符合命名规范的插件 ID 将被拒绝加载，并在日志中记录警告。

---

### 15.2 启用与禁用

插件可通过插件管理界面的开关按钮启用或禁用，**无需重启应用即时生效**：

- **禁用**：立即调用 `on_unload()` 并从运行时注销，下次扫描时跳过加载。
- **启用**：从禁用列表移除，重新触发扫描，自动加载（按依赖顺序）。

禁用状态持久化在 `plugins_ext/._data/plugin_states.json`，重启后恢复。

**代码示例（供宿主或脚本使用）：**

```python
# 禁用插件（立即卸载）
plugin_manager.set_enabled("my_plugin", False)

# 启用插件（自动重新加载）
plugin_manager.set_enabled("my_plugin", True)
```

---

### 15.3 卸载插件

`unload(plugin_id)` 方法立即卸载运行中的插件：

```python
plugin_manager.unload("my_plugin")
```

卸载时自动完成以下清理：
1. 调用插件的 `on_unload()` 方法
2. 取消所有通过 `api.subscribe_event()` 注册的事件订阅
3. 从共享 PluginAPI 中移除该插件注册的钩子、自定义触发器与动作
4. 从画布注册表移除该插件注册的所有小组件类型（`WIDGET_TYPE`）
5. 发出 `pluginUnloaded` 信号（供 UI 刷新）
6. 向 EventBus 广播 `PLUGIN_UNLOADED` 事件

> `unload()` **不检查依赖关系**，若存在其他插件依赖被卸载的插件，
> 依赖方调用 `api.get_plugin()` 时将返回 `None`。
> 推荐在卸载依赖插件前先卸载所有依赖它的功能插件。

---

## 16. 画布扩展 API（Canvas Extension API）

本章说明插件如何通过新增的 PluginAPI 方法与**全屏时钟画布（FullscreenClockWindow）**
做深度集成：注册自定义组件类型、注入顶栏按钮、读写布局预设。

---

### 16.1 组件类型注册（`register_widget_type` / `unregister_widget_type`）

```python
# 注册
api.register_widget_type(MyWidget)   # MyWidget 必须继承 WidgetBase 并提供 WIDGET_TYPE

# 注销（on_unload 中调用）
api.unregister_widget_type(MyWidget.WIDGET_TYPE)
```

> 插件卸载时系统会自动扫描并移除该插件注册的所有组件类型，
> 但显式调用 `unregister_widget_type` 可更早释放资源。

**`WidgetBase` 最小实现：**

```python
from typing import Any

from PySide6.QtWidgets import QWidget

from app.widgets.base_widget import WidgetBase, WidgetConfig

class MyWidget(WidgetBase):
    WIDGET_TYPE    = "my_plugin.my_widget"  # 全局唯一字符串 ID
    WIDGET_NAME    = "我的组件"

    def __init__(self, config: WidgetConfig, services: dict[str, Any], parent=None):
        super().__init__(config, services, parent)
        self._setup_ui()

    def apply_props(self, props: dict) -> None:
        """宿主调用：将新属性写入组件，用于从持久化数据恢复或编辑更新。"""
        super().apply_props(props)
        # 从 props 读取并刷新 UI…

    def get_edit_widget(self) -> QWidget | None:
        """返回在编辑面板中显示的属性编辑器，返回 None 则不可编辑。"""
        return None
```

---

### 16.2 顶栏按钮工厂（`register_canvas_topbar_btn_factory`）

注册一个**工厂函数**，每当用户打开全屏时钟画布（FullscreenClockWindow）时，
系统调用该工厂并将返回的 `QWidget` 或 `QWidget` 列表插入顶栏（编辑按钮左侧）。

```python
def my_factory(zone_id: str) -> list[QWidget]:
    """
    zone_id : 当前打开的 zone（世界时区）ID，可用于区分不同画布。
    返回值  : 要插入顶栏的 QWidget 列表（通常是 PushButton / ToolButton）。
              返回空列表或 None 都将被跳过。
    """
    btn = PushButton("我的按钮")
    btn.clicked.connect(lambda: print(f"当前 zone: {zone_id}"))
    return [btn]

api.register_canvas_topbar_btn_factory(my_factory)
```

也可以直接返回**单个**控件：

```python
def my_factory(zone_id: str) -> QWidget:
    btn = PushButton("我的按钮")
    btn.clicked.connect(lambda: print(zone_id))
    return btn
```

> 工厂函数在主线程中调用，可直接创建 Qt 控件。
> 按钮的生命周期由 `FullscreenClockWindow` 管理，窗口关闭时自动销毁。

---

### 16.3 画布共享服务（`register_canvas_service`）

当插件组件需要共享同一个服务对象（例如 `ExamService`、播放器控制器、数据缓存）时，
可以先注册画布服务，宿主随后会在创建 `WidgetCanvas` 时将其注入到 `services` 字典中：

```python
def on_load(self, api):
    self._svc = MyCanvasService()
    api.register_canvas_service("my_canvas_service", self._svc)
```

组件中即可直接读取：

```python
class MyWidget(WidgetBase):
    def __init__(self, config, services, parent=None):
        super().__init__(config, services, parent)
        self._svc = services.get("my_canvas_service")
```

> 画布共享服务按**组件所属插件**隔离：A 插件注册的 `my_canvas_service` 不会自动暴露给 B 插件的小组件。
> 同时，像 `notification_service` 这类宿主敏感服务也会根据该插件当前权限动态过滤；若插件在运行期通过 `request_permission()` 获准，后续 `services.get(...)` 会立即看到最新结果。

---

### 16.4 画布布局读写（`apply_canvas_layout` / `get_canvas_layout`）

直接读写指定 zone 的画布布局数据，可用于**预设保存/应用**。

```python
# 读取当前布局（返回 list of dict，每项描述一个组件实例）
configs = api.get_canvas_layout(zone_id)

# 应用布局（自动持久化并发出 WIDGET_LAYOUT_CHANGED 事件，
# 所有已打开的同 zone 画布会自动热重载）
api.apply_canvas_layout(zone_id, configs)
```

**布局项格式（configs 中的单个元素）：**

```json
{
  "widget_id":   "uuid",
  "widget_type": "exam_subject",
    "grid_x":      0,
    "grid_y":      0,
    "grid_w":      4,
    "grid_h":      2,
  "props": { "subject_id": "xxx" }
}
```

> 调用 `apply_canvas_layout` 后，系统会发出 `EventType.WIDGET_LAYOUT_CHANGED`
> 事件（附带 `zone_id` 参数），所有订阅该事件的已打开画布会自动调用 `reload_layout()`。

若多个功能插件都需要读写同一套布局预设，**推荐将预设目录与应用逻辑抽成一个 `library` 插件**，
由该依赖插件统一保存/删除/应用预设，业务插件只维护自己的“绑定关系”或“自动切换策略”。

---

### 16.5 共享布局预设库插件（`layout_presets`）

`plugins_ext/layout_presets/` 是项目内置的 `library` 插件，负责统一维护**跨插件共享的全屏画布布局预设**。
它演示了“**带 UI 的依赖插件**”模式：既能通过 `export()` 向其他插件暴露服务，
又能提供自己的侧边栏页面和全屏顶栏按钮。

**目录结构：**

```
plugins_ext/layout_presets/
├── plugin.json          ← 元数据，plugin_type = "library"
├── __init__.py          ← Plugin 主入口（注册侧边栏 / 顶栏按钮 / 事件订阅）
├── models.py            ← LayoutPreset 数据模型
├── service.py           ← LayoutPresetService（预设目录、当前 zone、应用状态）
└── sidebar.py           ← LayoutPresetSidebarPanel（预设管理页）
```

**加载流程（简化）：**

```python
from app.events import EventType

def on_load(self, api):
    world_zone_service = api.get_service("world_zone_service")
    self._svc = LayoutPresetService(
        data_dir=api.get_data_dir(),
        api=api,
        world_zone_service=world_zone_service,
    )
    api.register_canvas_topbar_btn_factory(self._make_topbar_buttons)
    api.subscribe_event(EventType.FULLSCREEN_OPENED, self._on_fullscreen_opened)

def export(self):
    return self._svc
```

**它解决的问题：**

- 统一保存、重命名、删除和应用共享布局预设；
- 通过 `world_zone_service` 让用户选择预设要面向哪个世界时钟画布；
- 在全屏画布顶栏提供“切换预设 / 保存预设”按钮；
- 在侧边栏提供完整的预设目录管理页；
- 让其他功能插件只关注自身业务绑定，而不必各自维护一份预设仓库。

**功能插件调用方式：**

```python
preset_service = api.get_plugin("layout_presets")
if preset_service is None:
    raise RuntimeError("layout_presets 不可用")

preset = preset_service.get_preset(preset_id)
if preset is not None:
    preset_service.apply_preset(preset.id, zone_id)
```

---

### 16.6 教育插件示例：考试面板与自习时间安排

`plugins_ext/exam_panel/` 与 `plugins_ext/study_schedule/` 展示了两个功能插件如何共同复用 `layout_presets`：

- `exam_panel`
  - 管理科目、考试计划、提醒和“科目 → 共享预设”的绑定；
  - 顶栏只保留“切换科目”，不再负责预设的创建/删除；
  - 旧版本本地预设可在加载时迁移到共享预设目录。
- `study_schedule`
  - 提供“事项组 / 事项 / 时间段”的完整侧边栏；
  - 支持按星期自动切换事项组、按时间段自动切换当前事项；
  - 预设优先级为“事项预设 > 事项组预设 > 不绑定”；
  - 可固定目标画布，也可跟随最近打开的全屏画布。

**考试插件加载流程（简化）：**

```python
def on_load(self, api):
    preset_service = api.get_plugin("layout_presets")
    self._svc = ExamService(
        data_dir=api.get_data_dir(),
        api=api,
        preset_service=preset_service,
    )
    api.register_canvas_service("exam_service", self._svc)
    api.register_canvas_topbar_btn_factory(self._make_topbar_buttons)
```

**自习插件加载流程（简化）：**

```python
def on_load(self, api):
    preset_service = api.get_plugin("layout_presets")
    world_zone_service = api.get_service("world_zone_service")
    self._svc = StudyScheduleService(
        data_dir=api.get_data_dir(),
        api=api,
        preset_service=preset_service,
        world_zone_service=world_zone_service,
    )
    api.register_canvas_service("study_service", self._svc)
```

**共享预设应用链路：**

```
功能插件（考试 / 自习）更新当前业务状态
    └─ 解析当前应命中的 preset_id
        └─ layout_presets.apply_preset(preset_id, zone_id)
            └─ api.apply_canvas_layout(zone_id, preset.configs)
                └─ EventBus.emit(WIDGET_LAYOUT_CHANGED, zone_id=zone_id)
                    └─ FullscreenClockWindow._on_layout_changed()
                        └─ WidgetCanvas.reload_layout()
```

**提醒触发链路（考试插件）：**

```
ExamService._check_exam_phase()   ← QTimer 每 30 秒
    └─ _check_reminders()
        └─ reminder_triggered.emit(subject_id, plan_id, reminder_id, msg)
            └─ Plugin._on_reminder()
                └─ trigger_reminder(mode="both", flash=True)
                    ├─ show_reminder_overlay()   ← 全屏半透明叠加层
                    └─ speak_reminder()          ← 后台线程 Windows SAPI / pyttsx3
```
