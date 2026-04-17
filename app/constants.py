# 应用全局常量
import sys
from pathlib import Path


IS_BETA         =   True                    # 是否为测试版：True 时所有界面显示对角水印
IS_PUBLIC       =   False                   # 是否公开发布

# 数据存储模式
# True  = 使用系统标准目录（通过 platformdirs 获取）
#         Windows: C:\Users\<用户>\AppData\Local\LittleTreeClock\小树时钟
#         macOS:   ~/Library/Application Support/小树时钟
#         Linux:   ~/.local/share/littletreeclock
# False = 使用应用目录（便携模式，数据跟随应用）
USE_SYSTEM_DATA_DIR = False

DEV_CODE_NAME   =   "Sow"                   # 开发代号

APP_NAME        =   "小树时钟"              # 应用名称
APP_VERSION     =   "0.114.514"                # 主版本号.次版本号.修订号，遵循语义化版本规范
VERSION_TYPE    =   "Alpha"                 # Alpha/Beta/Release
BUILD_TIME = "2026-04-12"            # 编译时间
BUILD_NUMBER = 2                       # 编译版本号，整数递增

# 完整版本字符串
LONG_VER        =   f"Core.{APP_VERSION}.{VERSION_TYPE}.{DEV_CODE_NAME}.{BUILD_TIME}.{BUILD_NUMBER}-{'Public' if IS_PUBLIC else 'Internal'}"

# 测试版附加说明（右下角显示）；留空则不显示该行
BETA_TEST_INFO  =   ""

# 自定义 URL 协议名
URL_SCHEME      =   "ltclock"          

# URL 路径 -> 视图 objectName 的映射
URL_VIEW_MAP = {
    "home":        "homeView",
    "world_time":  "worldTimeView",
    "alarm":       "alarmView",
    "timer":       "timerView",
    "stopwatch":   "stopwatchView",
    "focus":       "focusView",
    "plugin":      "pluginView",
    "automation":  "automationView",
    "settings":    "settingsView",
    "debug":       "debugView",   # 仅可通过 URL 打开
}

# 本地路径
# 打包后（sys.frozen=True）：
#   _APP_DIR      = exe 所在目录（用于 config/plugins/logs 等用户可写内容）
#   _RESOURCE_DIR = PyInstaller 解压的临时目录（_internal/，只读资源）
# 开发时两者相同。
if getattr(sys, "frozen", False):
    _APP_DIR      = Path(sys.executable).parent
    _RESOURCE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    _APP_DIR      = Path(__file__).resolve().parent.parent
    _RESOURCE_DIR = _APP_DIR

# 根据 USE_SYSTEM_DATA_DIR 决定数据存储目录
if USE_SYSTEM_DATA_DIR:
    from platformdirs import user_data_dir
    _DATA_DIR = Path(user_data_dir("小树时钟", "LittleTreeClock"))
else:
    _DATA_DIR = _APP_DIR

BASE_DIR        = _APP_DIR
CONFIG_DIR      = str(_DATA_DIR / "config")
TEMP_DIR        = str(_DATA_DIR / "temp")
PLUGINS_DIR     = str(_DATA_DIR / "plugins_ext")   # 外部插件目录
LOGS_DIR        = str(_DATA_DIR / "logs")          # 日志目录
ICON_PATH       = str(_RESOURCE_DIR / "icon.png")

# 配置文件
ALARM_CONFIG    = str(_DATA_DIR / "config" / "alarms.json")
AUTOMATION_CONFIG = str(_DATA_DIR / "config" / "automation.json")
SETTINGS_CONFIG = str(_DATA_DIR / "config" / "settings.json")
UPDATE_STATE_CONFIG = str(_DATA_DIR / "config" / "update.json")
WORLD_TIME_CONFIG = str(_DATA_DIR / "config" / "world_time.json")
NTP_CONFIG      = str(_DATA_DIR / "config" / "ntp.json")
FOCUS_CONFIG    = str(_DATA_DIR / "config" / "focus.json")
TIMER_CONFIG    = str(_DATA_DIR / "config" / "timers.json")
WIDGET_LAYOUT_CONFIG = str(_DATA_DIR / "config" / "widget_layouts.json")
RECOMMENDATIONS_CONFIG = str(_DATA_DIR / "config" / "recommendations.json")
PERMISSION_CONFIG = str(_DATA_DIR / "config" / "permission.json")
PERMISSION_DATA_DIR = str(_DATA_DIR / "config" / "permission")
CENTRAL_CONTROL_CONFIG = str(_DATA_DIR / "config" / "central_control.json")

# 小组件画布
WIDGET_CELL_SIZE = 120   # 每格像素尺寸

# 网络
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) "
    "Gecko/20100101"
    "Firefox/148.0"
)

# pip 镜像源列表（用于插件依赖安装）
# 每项格式：(显示名称, index-url)；空 url 表示使用 pip 默认源（PyPI 官方）
PIP_MIRRORS: list[tuple[str, str]] = [
    ("PyPI 官方",     ""),
    ("清华大学 TUNA", "https://pypi.tuna.tsinghua.edu.cn/simple/"),
    ("阿里云",        "https://mirrors.aliyun.com/pypi/simple/"),
    ("华为云",        "https://repo.huaweicloud.com/repository/pypi/simple/"),
    ("腾讯云",        "https://mirrors.cloud.tencent.com/pypi/simple/"),
    ("豆瓣",          "https://pypi.doubanio.com/simple/"),
]

# 闹钟相关
ALARM_CHECK_INTERVAL_MS = 1_000      # 闹钟轮询周期（毫秒）
MAX_ALARMS              = 100

# 计时器/秒表
TIMER_TICK_MS           = 10         # 计时器刷新（毫秒，10ms 保证百分位精度）

# 自动化
MAX_AUTOMATION_RULES    = 50

# 常用时区列表（IANA 时区名称）
PRESET_TIMEZONES = [
    ("本地时间",   "local"),
    ("协调世界时", "UTC"),
    ("北京/上海",  "Asia/Shanghai"),
    ("东京",       "Asia/Tokyo"),
    ("首尔",       "Asia/Seoul"),
    ("新加坡",     "Asia/Singapore"),
    ("迪拜",       "Asia/Dubai"),
    ("莫斯科",     "Europe/Moscow"),
    ("柏林/巴黎",  "Europe/Berlin"),
    ("伦敦",       "Europe/London"),
    ("纽约",       "America/New_York"),
    ("芝加哥",     "America/Chicago"),
    ("洛杉矶",     "America/Los_Angeles"),
    ("圣保罗",     "America/Sao_Paulo"),
    ("悉尼",       "Australia/Sydney"),
]
