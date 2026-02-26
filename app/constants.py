# 应用全局常量
import sys
from pathlib import Path

APP_NAME    = "小树时钟"
APP_VERSION = "0.1.0"
LONG_VER    = "Core.0.1.0.Alpha.20260223.1-Internal"

# 是否为测试版：True 时所有界面显示对角水印
IS_BETA          = True

# 测试版附加说明（右下角显示）；留空则不显示该行
BETA_TEST_INFO   = ""

URL_SCHEME  = "ltclock"          # 自定义 URL 协议名，如 ltclock://open/alarm

# URL 路径 → 视图 objectName 的映射
URL_VIEW_MAP = {
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

BASE_DIR        = _APP_DIR
CONFIG_DIR      = str(_APP_DIR / "config")
TEMP_DIR        = str(_APP_DIR / "temp")
PLUGINS_DIR     = str(_APP_DIR / "plugins_ext")   # 外部插件目录
ICON_PATH       = str(_RESOURCE_DIR / "icon.png")

# 配置文件
ALARM_CONFIG    = str(BASE_DIR / "config" / "alarms.json")
AUTOMATION_CONFIG = str(BASE_DIR / "config" / "automation.json")
SETTINGS_CONFIG = str(BASE_DIR / "config" / "settings.json")
WORLD_TIME_CONFIG = str(BASE_DIR / "config" / "world_time.json")
NTP_CONFIG      = str(BASE_DIR / "config" / "ntp.json")
FOCUS_CONFIG    = str(BASE_DIR / "config" / "focus.json")
TIMER_CONFIG    = str(BASE_DIR / "config" / "timers.json")
WIDGET_LAYOUT_CONFIG = str(BASE_DIR / "config" / "widget_layouts.json")

# 小组件画布
WIDGET_CELL_SIZE = 120   # 每格像素尺寸

# 网络
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

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
