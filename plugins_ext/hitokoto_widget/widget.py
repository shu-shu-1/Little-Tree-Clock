"""随机一言小组件：支持一言 API、诏预接口、自定义 HTTP API、本地文件与外部数据源。"""

from __future__ import annotations

import random
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QLabel,
    QFormLayout,
    QFileDialog,
    QGridLayout,
    QSpacerItem,
    QSizePolicy,
)
from qfluentwidgets import (
    SpinBox,
    ComboBox,
    PushButton,
    LineEdit,
    CheckBox,
    RadioButton,
    ColorPickerButton,
    StrongBodyLabel,
    FluentIcon as FIF,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics

from app.widgets.base_widget import WidgetBase, WidgetConfig
from app.widgets.fluent_font_picker import FluentFontPicker

from .sources import (
    all_external_sources,
    get_external_source,
    normalize_extras,
    read_ext_options,
)
from .url_guard import UnsafeUrlError, safe_get


HITOKOTO_CATEGORIES: list[tuple[str, str]] = [
    ("a", "动画"),
    ("b", "漫画"),
    ("c", "游戏"),
    ("d", "文学"),
    ("e", "原创"),
    ("f", "来自网络"),
    ("g", "其他"),
    ("h", "影视"),
    ("i", "诗词"),
    ("j", "网易云"),
    ("k", "哲学"),
    ("l", "抖机灵"),
]


ZHAOYU_THEMES: list[tuple[str, str]] = [
    ("shuqing", "抒情"),
    ("siji", "四季"),
    ("shanshui", "山水"),
    ("tianqi", "天气"),
    ("renwu", "人物"),
    ("rensheng", "人生"),
    ("shenghuo", "生活"),
    ("jieri", "节日"),
    ("dongwu", "动物"),
    ("zhiwu", "植物"),
    ("shiwu", "食物"),
    ("guji", "古籍"),
]

ZHAOYU_CATALOGS: dict[str, list[tuple[str, str]]] = {
    "shuqing": [
        ("aiqing", "爱情"),
        ("youqing", "友情"),
        ("libie", "离别"),
        ("sinian", "思念"),
        ("sixiang", "思乡"),
        ("shanggan", "伤感"),
        ("gudu", "孤独"),
        ("guiyuan", "闺怨"),
        ("daowang", "悼亡"),
        ("huaigu", "怀古"),
        ("aiguo", "爱国"),
        ("ganen", "感恩"),
    ],
    "siji": [
        ("chuntian", "春天"),
        ("xiatian", "夏天"),
        ("qiutian", "秋天"),
        ("dongtian", "冬天"),
    ],
    "shanshui": [
        ("lushan", "庐山"),
        ("taishan", "泰山"),
        ("jianghe", "江河"),
        ("changjiang", "长江"),
        ("huanghe", "黄河"),
        ("xihu", "西湖"),
        ("pubu", "瀑布"),
    ],
    "tianqi": [
        ("xiefeng", "写风"),
        ("xieyun", "写云"),
        ("xieyu", "写雨"),
        ("xiexue", "写雪"),
        ("caihong", "彩虹"),
        ("taiyang", "太阳"),
        ("yueliang", "月亮"),
        ("xingxing", "星星"),
    ],
    "renwu": [
        ("nvzi", "女子"),
        ("fuqin", "父亲"),
        ("muqin", "母亲"),
        ("laoshi", "老师"),
        ("ertong", "儿童"),
    ],
    "rensheng": [
        ("lizhi", "励志"),
        ("zheli", "哲理"),
        ("qingchun", "青春"),
        ("shiguang", "时光"),
        ("mengxiang", "梦想"),
        ("dushu", "读书"),
        ("zhanzheng", "战争"),
    ],
    "shenghuo": [
        ("xiangcun", "乡村"),
        ("tianyuan", "田园"),
        ("biansai", "边塞"),
        ("xieqiao", "写桥"),
    ],
    "jieri": [
        ("chunjie", "春节"),
        ("yuanxiaojie", "元宵节"),
        ("hanshijie", "寒食节"),
        ("qingmingjie", "清明节"),
        ("duanwujie", "端午节"),
        ("qixijie", "七夕节"),
        ("zhongqiujie", "中秋节"),
        ("chongyangjie", "重阳节"),
    ],
    "dongwu": [
        ("xieniao", "写鸟"),
        ("xiema", "写马"),
        ("xiemao", "写猫"),
    ],
    "zhiwu": [
        ("meihua", "梅花"),
        ("lihua", "梨花"),
        ("taohua", "桃花"),
        ("hehua", "荷花"),
        ("juhua", "菊花"),
        ("liushu", "柳树"),
        ("yezi", "叶子"),
        ("zhuzi", "竹子"),
    ],
    "shiwu": [
        ("xiejiu", "写酒"),
        ("xiecha", "写茶"),
        ("lizhi", "荔枝"),
    ],
    "guji": [
        ("lunyu", "论语"),
        ("shiji", "史记"),
        ("laozi", "老子"),
        ("zhuangzi", "庄子"),
        ("mengzi", "孟子"),
        ("zhongyong", "中庸"),
        ("zuozhuan", "左传"),
        ("liutao", "六韬"),
        ("sushu", "素书"),
        ("liji", "礼记"),
        ("yizhuan", "易传"),
        ("fanjin", "反经"),
        ("mozi", "墨子"),
        ("xunzi", "荀子"),
        ("shangshu", "尚书"),
        ("hanshu", "汉书"),
        ("guanzi", "管子"),
        ("xiaojin", "孝经"),
        ("liezi", "列子"),
        ("wuzi", "吴子"),
        ("jiangyuan", "将苑"),
        ("lunheng", "论衡"),
        ("minshi", "明史"),
        ("sanlue", "三略"),
        ("songshi", "宋史"),
        ("jinshu", "晋书"),
        ("erya", "尔雅"),
        ("chajin", "茶经"),
        ("guoyu", "国语"),
        ("shuoyuan", "说苑"),
        ("yuanshi", "元史"),
        ("suishu", "隋书"),
        ("songshu", "宋书"),
        ("wenzi", "文子"),
        ("zhoushu", "周书"),
        ("weishu", "魏书"),
        ("liangshu", "梁书"),
        ("chenshu", "陈书"),
        ("jinshi", "金史"),
        ("beishi", "北史"),
        ("liaoshi", "辽史"),
        ("nanshi", "南史"),
        ("zhiyan", "知言"),
        ("zhongshuo", "中说"),
        ("hedian", "何典"),
        ("zhonglun", "中论"),
        ("guiguzi", "鬼谷子"),
        ("caigentan", "菜根谭"),
        ("sanguozhi", "三国志"),
        ("sanzijin", "三字经"),
        ("hanfeizi", "韩非子"),
        ("qianziwen", "千字文"),
        ("zhanguoce", "战国策"),
        ("dizigui", "弟子规"),
        ("jin gangjin", "金刚经"),
        ("shanghanlun", "伤寒论"),
        ("hongloumeng", "红楼梦"),
        ("huainanzi", "淮南子"),
        ("shangjunshu", "商君书"),
        ("houhanshu", "后汉书"),
        ("luozhijin", "罗织经"),
        ("chuanxilu", "传习录"),
        ("xiyouji", "西游记"),
        ("simafa", "司马法"),
        ("weiliazi", "尉缭子"),
        ("shuihuzhuan", "水浒传"),
        ("yizhoushu", "逸周书"),
        ("xintangshu", "新唐书"),
        ("jiutangshu", "旧唐书"),
        ("jinghuayuan", "镜花缘"),
        ("nanqishu", "南齐书"),
        ("renwuzhi", "人物志"),
        ("lienvzhuan", "列女传"),
        ("sanshiliuji", "三十六计"),
        ("huangdineijin", "黄帝内经"),
        ("zizhitongjian", "资治通鉴"),
        ("shishuoxinyu", "世说新语"),
        ("lvshichunqiu", "吕氏春秋"),
        ("zengguangxianwen", "增广贤文"),
        ("liaofansixun", "了凡四训"),
        ("wenxindiaolong", "文心雕龙"),
        ("baizhanqilue", "百战奇略"),
        ("sunbinbinfa", "孙膑兵法"),
        ("shenglvqimeng", "声律启蒙"),
        ("youxueqionglin", "幼学琼林"),
        ("sanguoyanyi", "三国演义"),
        ("yanshijiaxun", "颜氏家训"),
        ("weiluyehua", "围炉夜话"),
        ("zhenguanzhengyao", "贞观政要"),
        ("kongzijiaoyu", "孔子家语"),
        ("huangdisijin", "黄帝四经"),
        ("liaozhaizhiyi", "聊斋志异"),
        ("xiaochuangyouji", "小窗幽记"),
        ("gongsunlongzi", "公孙龙子"),
        ("fushengliuji", "浮生六记"),
        ("zhuzijiaxun", "朱子家训"),
        ("suiyuanshihua", "随园诗话"),
        ("jingshitongyan", "警世通言"),
        ("xingshihengyan", "醒世恒言"),
        ("taipingyulan", "太平御览"),
        ("xinwudaishi", "新五代史"),
        ("yushimingyan", "喻世明言"),
        ("jiuwudaishi", "旧五代史"),
        ("jinkuiyaolue", "金匮要略"),
        ("mingruxuean", "明儒学案"),
    ],
}

_ALIGN_MAP = {
    "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
    "center": Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
    "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
}
# 扩展行（徽章）在纵向布局中的水平对齐
_EXTRA_ALIGN_MAP = {
    "left": Qt.AlignmentFlag.AlignLeft,
    "center": Qt.AlignmentFlag.AlignHCenter,
    "right": Qt.AlignmentFlag.AlignRight,
}
_CENTRAL_CONFIG: dict = {}


def set_central_config(config: dict | None) -> None:
    global _CENTRAL_CONFIG
    _CENTRAL_CONFIG = dict(config) if isinstance(config, dict) else {}


def _ui_language() -> str:
    """获取宿主当前界面语言（用于解析外部数据源的本地化名称）。"""
    try:
        from app.services.i18n_service import I18nService

        return I18nService.instance().language or "zh-CN"
    except Exception:
        return "zh-CN"


class _FetchSignals(QObject):
    done = Signal(str, str, list)  # (quote_text, source_info, extra_rows)
    error = Signal(str)  # error_message


class _FetchWorker:
    def __init__(self, signals: _FetchSignals, props: dict):
        self._signals = signals
        self._props = props

    def run(self) -> None:
        try:
            source = self._props.get("source", "hitokoto")
            ext = get_external_source(source)
            if ext is not None:
                self._fetch_external(ext)
            elif source == "hitokoto":
                self._fetch_hitokoto()
            elif source == "zhaoyu":
                self._fetch_zhaoyu()
            elif source == "custom_api":
                self._fetch_custom_api()
            elif source == "local_file":
                self._fetch_local_file()
            else:
                self._signals.error.emit(f"未知来源：{source}（若其由其他插件提供，请确认对应插件已启用）")
        except Exception as exc:
            self._signals.error.emit(str(exc))

    def _fetch_external(self, ext) -> None:
        """调用外部数据源；兼容二元组与三元组返回（第三项为扩展行），异常由 run() 统一处理。"""
        options = read_ext_options(self._props, ext.source_id)
        result = ext.fetch(options, dict(self._props))
        if not isinstance(result, (tuple, list)) or len(result) not in (2, 3):
            raise ValueError(f"数据源 {ext.source_id} 返回格式错误（应为 (正文, 出处[, 扩展行]) 元组）")

        text, source_info = result[0], result[1]
        extras = normalize_extras(result[2]) if len(result) == 3 else []
        text = str(text or "").strip()
        if not text:
            raise ValueError(f"数据源 {ext.source_id} 未返回有效内容")
        self._signals.done.emit(text, str(source_info or "").strip(), extras)

    def _fetch_hitokoto(self) -> None:
        cats = self._props.get("hitokoto_categories", [])
        url = "https://v1.hitokoto.cn/"

        # requests 支持将列表作为同名参数：c=a&c=b
        if cats:
            params: list[tuple[str, str]] = [("c", c) for c in cats]
        else:
            params = []

        try:
            resp = safe_get(url, params=params)
        except UnsafeUrlError as exc:
            self._signals.error.emit(f"请求被安全校验拒绝：{exc}")
            return
        resp.raise_for_status()
        data = resp.json()

        text = data.get("hitokoto", "")
        from_who = (data.get("from_who") or "").strip()
        from_src = (data.get("from") or "").strip()

        if from_who and from_src:
            source_info = f"——{from_who}《{from_src}》"
        elif from_who:
            source_info = f"——{from_who}"
        elif from_src:
            source_info = f"——《{from_src}》"
        else:
            source_info = ""

        self._signals.done.emit(text, source_info, [])

    def _fetch_zhaoyu(self) -> None:
        theme = self._props.get("zhaoyu_theme", "")
        catalog = self._props.get("zhaoyu_catalog", "")

        base_url = "https://hub.saintic.com/openservice/sentence/"
        if theme:
            if catalog:
                url = f"{base_url}{theme}.{catalog}.json"
            else:
                # URL 中的 ".." 表示该主题下的全部分类
                url = f"{base_url}{theme}..json"
        else:
            url = base_url

        try:
            resp = safe_get(url)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("success"):
                self._signals.error.emit("API 返回失败")
                return

            result = data.get("data", {})
            text = result.get("sentence", "")
            author = (result.get("author") or "").strip()
            name = (result.get("name") or "").strip()

            if author and name:
                source_info = f"——{author}《{name}》"
            elif author:
                source_info = f"——{author}"
            elif name:
                source_info = f"——《{name}》"
            else:
                source_info = ""

            self._signals.done.emit(text, source_info, [])
        except UnsafeUrlError as e:
            self._signals.error.emit(f"请求被安全校验拒绝：{e}")
        except Exception as e:
            self._signals.error.emit(f"获取失败：{str(e)}")

    def _fetch_custom_api(self) -> None:
        url = self._props.get("custom_api_url", "").strip()
        if not url:
            self._signals.error.emit("未设置自定义 API 地址")
            return

        try:
            resp = safe_get(url)
        except UnsafeUrlError as exc:
            self._signals.error.emit(f"请求被安全校验拒绝：{exc}")
            return
        resp.raise_for_status()

        json_path = self._props.get("custom_api_json_path", "").strip()

        try:
            data = resp.json()
        except Exception:
            # 纯文本响应
            self._signals.done.emit(resp.text.strip(), "", [])
            return

        if json_path:
            node: object = data
            for key in json_path.split("."):
                if isinstance(node, dict):
                    node = node.get(key, "")
                else:
                    node = ""
                    break
            text = str(node).strip()
        else:
            # 自动探测常见字段
            text = ""
            for field in ("hitokoto", "content", "text", "sentence", "data"):
                if isinstance(data, dict) and field in data:
                    text = str(data[field]).strip()
                    break
            if not text:
                text = str(data)

        self._signals.done.emit(text, "", [])

    def _fetch_local_file(self) -> None:
        file_path = self._props.get("local_file_path", "").strip()
        if not file_path:
            self._signals.error.emit("未设置本地文件路径")
            return

        path = Path(file_path)
        if not path.exists():
            self._signals.error.emit(f"文件不存在：{file_path}")
            return

        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = path.read_text(encoding="gbk", errors="replace")

        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if not lines:
            self._signals.error.emit("文件内容为空")
            return

        self._signals.done.emit(random.choice(lines), "", [])


class _EditPanel(QWidget):
    """小组件编辑面板（嵌入右键→编辑对话框）"""

    def __init__(self, props: dict, parent=None):
        super().__init__(parent)
        self._props = dict(props)
        self._setup_ui()

    def _setup_ui(self) -> None:
        f = QFormLayout(self)
        f.setVerticalSpacing(8)
        f.setContentsMargins(4, 4, 4, 4)

        f.addRow(StrongBodyLabel("内容来源"))

        self._rb_hitokoto = RadioButton("一言 API（v1.hitokoto.cn）")
        self._rb_zhaoyu = RadioButton("诏预接口（古诗词名句）")
        self._rb_custom = RadioButton("自定义 HTTP API")
        self._rb_local = RadioButton("本地文本文件")

        for rb in (self._rb_hitokoto, self._rb_zhaoyu, self._rb_custom, self._rb_local):
            f.addRow(rb)

        src = self._props.get("source", "hitokoto")
        {
            "hitokoto": self._rb_hitokoto,
            "zhaoyu": self._rb_zhaoyu,
            "custom_api": self._rb_custom,
            "local_file": self._rb_local,
        }.get(src, self._rb_hitokoto).setChecked(True)

        # 各来源的设置区统一放在全部单选项之后。
        self._ext_radios: dict[str, RadioButton] = {}
        self._ext_sections: dict[str, QWidget] = {}
        self._ext_controls: dict[str, dict[str, QWidget]] = {}

        lang = _ui_language()
        current_src = str(self._props.get("source", "") or "")
        for ext in all_external_sources():
            rb = RadioButton(ext.display_name(lang))
            f.addRow(rb)
            self._ext_radios[ext.source_id] = rb
            if ext.source_id == current_src:
                rb.setChecked(True)

        self._cat_section = QWidget()
        cat_sec_lay = QVBoxLayout(self._cat_section)
        cat_sec_lay.setContentsMargins(0, 0, 0, 0)
        cat_sec_lay.setSpacing(4)
        cat_sec_lay.addWidget(StrongBodyLabel("一言分类（可多选，留空 = 全部）"))

        cat_grid_w = QWidget()
        cat_grid = QGridLayout(cat_grid_w)
        cat_grid.setHorizontalSpacing(16)
        cat_grid.setVerticalSpacing(4)
        cat_grid.setContentsMargins(0, 0, 0, 0)

        self._cat_checks: dict[str, CheckBox] = {}
        selected_cats: list[str] = self._props.get("hitokoto_categories", [])
        for idx, (key, label) in enumerate(HITOKOTO_CATEGORIES):
            cb = CheckBox(label)
            cb.setChecked(key in selected_cats)
            self._cat_checks[key] = cb
            cat_grid.addWidget(cb, idx // 3, idx % 3)

        cat_sec_lay.addWidget(cat_grid_w)
        f.addRow(self._cat_section)

        self._zhaoyu_section = QWidget()
        zhaoyu_sec_lay = QVBoxLayout(self._zhaoyu_section)
        zhaoyu_sec_lay.setContentsMargins(0, 0, 0, 0)
        zhaoyu_sec_lay.setSpacing(4)
        zhaoyu_sec_lay.addWidget(StrongBodyLabel("诏预接口设置"))

        zhaoyu_sub = QWidget()
        zhaoyu_form = QFormLayout(zhaoyu_sub)
        zhaoyu_form.setContentsMargins(0, 0, 0, 0)
        zhaoyu_form.setVerticalSpacing(6)

        self._zhaoyu_theme_combo = ComboBox()
        self._zhaoyu_theme_combo.addItem("全部主题", userData="")
        for theme_pinyin, theme_name in ZHAOYU_THEMES:
            self._zhaoyu_theme_combo.addItem(theme_name, userData=theme_pinyin)

        current_theme = self._props.get("zhaoyu_theme", "")
        theme_idx = next(
            (
                i
                for i in range(self._zhaoyu_theme_combo.count())
                if self._zhaoyu_theme_combo.itemData(i) == current_theme
            ),
            0,
        )
        self._zhaoyu_theme_combo.setCurrentIndex(theme_idx)
        zhaoyu_form.addRow("主题:", self._zhaoyu_theme_combo)

        self._zhaoyu_catalog_combo = ComboBox()
        self._zhaoyu_catalog_combo.addItem("全部分类", userData="")
        zhaoyu_form.addRow("分类:", self._zhaoyu_catalog_combo)

        self._zhaoyu_theme_combo.currentIndexChanged.connect(self._update_zhaoyu_catalogs)
        self._update_zhaoyu_catalogs()

        zhaoyu_sec_lay.addWidget(zhaoyu_sub)
        f.addRow(self._zhaoyu_section)

        self._api_section = QWidget()
        api_sec_lay = QVBoxLayout(self._api_section)
        api_sec_lay.setContentsMargins(0, 0, 0, 0)
        api_sec_lay.setSpacing(4)
        api_sec_lay.addWidget(StrongBodyLabel("自定义 API 设置"))

        api_sub = QWidget()
        api_form = QFormLayout(api_sub)
        api_form.setContentsMargins(0, 0, 0, 0)
        api_form.setVerticalSpacing(6)

        self._api_url = LineEdit()
        self._api_url.setText(self._props.get("custom_api_url", ""))
        self._api_url.setPlaceholderText("https://api.example.com/random_quote")
        api_form.addRow("API 地址:", self._api_url)

        self._api_path = LineEdit()
        self._api_path.setText(self._props.get("custom_api_json_path", ""))
        self._api_path.setPlaceholderText("JSON 路径，如 data.content（留空自动探测）")
        api_form.addRow("JSON 路径:", self._api_path)

        api_sec_lay.addWidget(api_sub)
        f.addRow(self._api_section)

        self._file_section = QWidget()
        file_sec_lay = QVBoxLayout(self._file_section)
        file_sec_lay.setContentsMargins(0, 0, 0, 0)
        file_sec_lay.setSpacing(4)
        file_sec_lay.addWidget(StrongBodyLabel("本地文件设置"))

        file_row = QWidget()
        file_hl = QHBoxLayout(file_row)
        file_hl.setContentsMargins(0, 0, 0, 0)

        self._file_path = LineEdit()
        self._file_path.setText(self._props.get("local_file_path", ""))
        self._file_path.setPlaceholderText("每行一条语录的 .txt 文件")
        browse_btn = PushButton("浏览…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._browse_file)

        file_hl.addWidget(self._file_path)
        file_hl.addWidget(browse_btn)

        file_sub = QWidget()
        file_sub_form = QFormLayout(file_sub)
        file_sub_form.setContentsMargins(0, 0, 0, 0)
        file_sub_form.addRow("文件路径:", file_row)
        file_sec_lay.addWidget(file_sub)
        f.addRow(self._file_section)

        # 其配置区与内置来源的设置区并列（在全部单选项之后）。
        for ext in all_external_sources():
            section = QWidget()
            sec_lay = QVBoxLayout(section)
            sec_lay.setContentsMargins(0, 0, 0, 0)
            sec_lay.setSpacing(4)
            sec_lay.addWidget(StrongBodyLabel(f"{ext.display_name(lang)} 设置"))

            sub = QWidget()
            sub_form = QFormLayout(sub)
            sub_form.setContentsMargins(0, 0, 0, 0)
            sub_form.setVerticalSpacing(6)

            saved = read_ext_options(self._props, ext.source_id)
            controls: dict[str, QWidget] = {}
            for opt in ext.options:
                label_text = ext.option_label(opt, lang)
                if opt.type == "bool":
                    cb = CheckBox()
                    cb.setChecked(bool(saved.get(opt.key, opt.default)))
                    sub_form.addRow(f"{label_text}:", cb)
                    controls[opt.key] = cb
                else:
                    combo = ComboBox()
                    current_value = str(saved.get(opt.key, opt.default))
                    value_index = 0
                    for idx, (value, text) in enumerate(opt.choices):
                        combo.addItem(text, userData=value)
                        if value == current_value:
                            value_index = idx
                    combo.setCurrentIndex(value_index)
                    sub_form.addRow(f"{label_text}:", combo)
                    controls[opt.key] = combo

            if not controls:
                hint = QLabel("该数据源没有可配置项")
                hint.setStyleSheet("color:#888888; background:transparent;")
                sub_form.addRow(hint)

            sec_lay.addWidget(sub)
            f.addRow(section)
            self._ext_sections[ext.source_id] = section
            self._ext_controls[ext.source_id] = controls

        self._show_author = CheckBox()
        self._show_author.setChecked(self._props.get("show_author", True))
        f.addRow("显示出处 / 作者:", self._show_author)

        self._font_spin = SpinBox()
        self._font_spin.setRange(8, 120)
        self._font_spin.setValue(self._props.get("font_size", 20))
        self._font_spin.setSuffix(" px")
        f.addRow("字体大小:", self._font_spin)

        self._font_picker = FluentFontPicker()
        self._font_picker.setCurrentFontFamily(str(self._props.get("font_family", "") or ""))
        f.addRow("字体:", self._font_picker)

        self._color_btn = ColorPickerButton(QColor(self._props.get("color", "#ffffff")), "文字颜色")
        f.addRow("文字颜色:", self._color_btn)

        self._align_combo = ComboBox()
        for lbl, val in [("居中", "center"), ("左对齐", "left"), ("右对齐", "right")]:
            self._align_combo.addItem(lbl, userData=val)
        cur_align = self._props.get("align", "center")
        idx_align = next((i for i in range(self._align_combo.count()) if self._align_combo.itemData(i) == cur_align), 0)
        self._align_combo.setCurrentIndex(idx_align)
        f.addRow("对齐方式:", self._align_combo)

        self._refresh_spin = SpinBox()
        self._refresh_spin.setRange(0, 1440)
        self._refresh_spin.setValue(self._props.get("refresh_interval", 30))
        self._refresh_spin.setSuffix(" 分钟")
        self._refresh_spin.setSpecialValueText("手动刷新")
        f.addRow("自动刷新间隔:", self._refresh_spin)

        self._source_gap_spin = SpinBox()
        self._source_gap_spin.setRange(0, 20)
        self._source_gap_spin.setValue(int(self._props.get("source_gap_lines", 0) or 0))
        self._source_gap_spin.setSuffix(" 行")
        f.addRow("句子与来源间距:", self._source_gap_spin)

        self._w_spin = SpinBox()
        self._w_spin.setRange(2, 20)
        self._w_spin.setValue(self._props.get("grid_w", 4))
        f.addRow("横向格数:", self._w_spin)

        self._h_spin = SpinBox()
        self._h_spin.setRange(1, 20)
        self._h_spin.setValue(self._props.get("grid_h", 3))
        f.addRow("纵向格数:", self._h_spin)

        for rb in (self._rb_hitokoto, self._rb_zhaoyu, self._rb_custom, self._rb_local):
            rb.toggled.connect(self._update_visibility)
        for rb in self._ext_radios.values():
            rb.toggled.connect(self._update_visibility)
        self._update_visibility()

    def _update_visibility(self) -> None:
        self._cat_section.setVisible(self._rb_hitokoto.isChecked())
        self._zhaoyu_section.setVisible(self._rb_zhaoyu.isChecked())
        self._api_section.setVisible(self._rb_custom.isChecked())
        self._file_section.setVisible(self._rb_local.isChecked())
        for sid, section in self._ext_sections.items():
            rb = self._ext_radios.get(sid)
            section.setVisible(bool(rb is not None and rb.isChecked()))

    def _update_zhaoyu_catalogs(self) -> None:
        theme = self._zhaoyu_theme_combo.currentData()

        current_catalog = self._props.get("zhaoyu_catalog", "")

        self._zhaoyu_catalog_combo.clear()
        self._zhaoyu_catalog_combo.addItem("全部分类", userData="")

        if theme and theme in ZHAOYU_CATALOGS:
            for catalog_pinyin, catalog_name in ZHAOYU_CATALOGS[theme]:
                self._zhaoyu_catalog_combo.addItem(catalog_name, userData=catalog_pinyin)

        catalog_idx = next(
            (
                i
                for i in range(self._zhaoyu_catalog_combo.count())
                if self._zhaoyu_catalog_combo.itemData(i) == current_catalog
            ),
            0,
        )
        self._zhaoyu_catalog_combo.setCurrentIndex(catalog_idx)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择一言文本文件", "", "文本文件 (*.txt);;所有文件 (*)")
        if path:
            self._file_path.setText(path)

    def collect_props(self) -> dict:
        if self._rb_hitokoto.isChecked():
            source = "hitokoto"
        elif self._rb_zhaoyu.isChecked():
            source = "zhaoyu"
        elif self._rb_custom.isChecked():
            source = "custom_api"
        elif any(rb.isChecked() for rb in self._ext_radios.values()):
            source = next(sid for sid, rb in self._ext_radios.items() if rb.isChecked())
        else:
            source = "local_file"

        cats = [k for k, cb in self._cat_checks.items() if cb.isChecked()]

        # 外部数据源选项：当前已注册的读取控件值，
        # 已卸载数据源的旧值原样保留，便于恢复。
        ext_options: dict[str, dict] = {}
        saved_ext = self._props.get("ext_options")
        if isinstance(saved_ext, dict):
            for sid, values in saved_ext.items():
                if isinstance(values, dict) and sid not in self._ext_controls:
                    ext_options[sid] = dict(values)
        for sid, controls in self._ext_controls.items():
            values: dict = {}
            for key, widget in controls.items():
                if isinstance(widget, CheckBox):
                    values[key] = bool(widget.isChecked())
                else:
                    values[key] = str(widget.currentData() or "")
            ext_options[sid] = values

        return {
            "source": source,
            "hitokoto_categories": cats,
            "zhaoyu_theme": self._zhaoyu_theme_combo.currentData(),
            "zhaoyu_catalog": self._zhaoyu_catalog_combo.currentData(),
            "custom_api_url": self._api_url.text().strip(),
            "custom_api_json_path": self._api_path.text().strip(),
            "local_file_path": self._file_path.text().strip(),
            "ext_options": ext_options,
            "show_author": self._show_author.isChecked(),
            "font_size": self._font_spin.value(),
            "font_family": self._font_picker.currentFontFamily(),
            "color": self._color_btn.color.name(),
            "align": self._align_combo.currentData(),
            "refresh_interval": self._refresh_spin.value(),
            "source_gap_lines": self._source_gap_spin.value(),
            "grid_w": self._w_spin.value(),
            "grid_h": self._h_spin.value(),
        }


class HitokotoWidget(WidgetBase):
    WIDGET_TYPE = "hitokoto"
    WIDGET_NAME = "随机一言"
    DELETABLE = True
    MIN_W = 2
    MIN_H = 1
    DEFAULT_W = 4
    DEFAULT_H = 3

    def __init__(self, config: WidgetConfig, services, parent=None):
        super().__init__(config, services, parent)

        self._current_text: str = ""
        self._current_source: str = ""
        self._current_extras: list[tuple[str, str]] = []
        self._is_fetching: bool = False
        self._last_fetch: float = 0.0
        self._need_fetch: bool = True

        self._signals = _FetchSignals()
        self._signals.done.connect(self._on_fetch_done)
        self._signals.error.connect(self._on_fetch_error)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(0)
        self._root_layout = root

        self._quote_lbl = QLabel()
        self._quote_lbl.setWordWrap(True)
        self._quote_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._quote_lbl.setStyleSheet("background:transparent;")
        root.addWidget(self._quote_lbl)

        self._source_gap = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        root.addItem(self._source_gap)

        self._source_lbl = QLabel()
        self._source_lbl.setStyleSheet("background:transparent;")
        root.addWidget(self._source_lbl)

        # 扩展行容器：数据源通过 fetch 返回 extras 新建显示行（如教材标注），
        # 渲染为出处下方的徽章样式行
        self._extra_container = QWidget()
        self._extra_container.setStyleSheet("background:transparent;")
        self._extras_layout = QVBoxLayout(self._extra_container)
        self._extras_layout.setContentsMargins(0, 4, 0, 0)
        self._extras_layout.setSpacing(4)
        self._extra_labels: list[QLabel] = []
        root.addWidget(self._extra_container)

        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet("font-size:12px; background:transparent;")
        root.addWidget(self._status_lbl)
        root.addStretch(1)

        self.refresh()

    def refresh(self) -> None:
        p = self.config.props
        interval = p.get("refresh_interval", 30)  # 分钟
        now = time.time()

        should_fetch = self._need_fetch or (interval > 0 and (now - self._last_fetch) >= interval * 60)

        if should_fetch and not self._is_fetching:
            self._start_fetch()

        self._redraw()

    def get_edit_widget(self) -> QWidget:
        props = dict(self.config.props)
        props["grid_w"] = self.config.grid_w
        props["grid_h"] = self.config.grid_h
        return _EditPanel(props)

    def apply_props(self, props: dict) -> None:
        self.config.props.update(props)
        self.config.grid_w = max(self.MIN_W, int(props.get("grid_w", self.DEFAULT_W)))
        self.config.grid_h = max(self.MIN_H, int(props.get("grid_h", self.DEFAULT_H)))
        self._need_fetch = True
        self.refresh()

    def get_context_menu_actions(self):
        return [
            ("刷新", FIF.SYNC, self._force_refresh),
        ]

    def _force_refresh(self) -> None:
        """强制刷新一言内容（重置自动刷新计时）"""
        self._last_fetch = 0.0
        self._need_fetch = True
        self.refresh()

    def _start_fetch(self) -> None:
        if bool(_CENTRAL_CONFIG.get("disable_fetch", False)):
            self._status_lbl.setText("已被集控禁用：当前策略不允许刷新内容")
            return

        source = str(self.config.props.get("source", "hitokoto") or "hitokoto")
        blocked_sources = {
            str(item).strip() for item in _CENTRAL_CONFIG.get("blocked_sources", []) if str(item).strip()
        }
        if source in blocked_sources:
            self._status_lbl.setText(f"已被集控禁用：来源 {source} 不可用")
            return

        if not self._ensure_feature_access(
            "plugin.hitokoto_widget.fetch_quote",
            reason="获取随机一言内容",
        ):
            self._status_lbl.setText("访问受限：当前权限策略不允许获取内容")
            return

        self._is_fetching = True
        self._need_fetch = False
        self._status_lbl.setText("正在获取…")

        worker = _FetchWorker(self._signals, dict(self.config.props))
        thread = threading.Thread(target=worker.run, daemon=True)
        thread.start()

    def _on_fetch_done(self, text: str, source_info: str, extras: list) -> None:
        self._current_text = text
        self._current_source = source_info
        self._current_extras = list(extras or [])
        self._last_fetch = time.time()
        self._is_fetching = False
        self._status_lbl.setText("")
        self._rebuild_extra_labels()
        self._redraw()

    def _rebuild_extra_labels(self) -> None:
        """按最近一次抓取的扩展行重建徽章标签（在主线程调用）。"""
        while self._extra_labels:
            lbl = self._extra_labels.pop()
            self._extras_layout.removeWidget(lbl)
            lbl.deleteLater()
        for label_text, value_text in self._current_extras:
            lbl = QLabel()
            lbl.setText(f"{label_text}：{value_text}" if label_text else value_text)
            lbl.setStyleSheet("background:transparent;")
            self._extras_layout.addWidget(lbl, 0, Qt.AlignmentFlag.AlignLeft)
            self._extra_labels.append(lbl)
        self._extra_container.setVisible(bool(self._extra_labels))

    def _on_fetch_error(self, error: str) -> None:
        self._is_fetching = False
        self._status_lbl.setText(f"获取失败：{error}")
        if not self._current_text:
            self._quote_lbl.setText("暂无内容")

    def _redraw(self) -> None:
        p = self.config.props
        wc = self._wc()
        font_size = int(p.get("font_size", 20) or 20)
        color = p.get("color", "#ffffff")
        if color in ("", "#ffffff") and not self._is_dark():
            color = wc["primary"]
        align = p.get("align", "center")
        show_src = p.get("show_author", True)
        gap_lines = max(0, int(p.get("source_gap_lines", 0) or 0))
        align_flag = _ALIGN_MAP.get(align, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        compact_mode = self.config.grid_h <= 1
        self._root_layout.setContentsMargins(
            10 if compact_mode else 12, 6 if compact_mode else 10, 10 if compact_mode else 12, 6 if compact_mode else 10
        )

        quote_font = QFont(self._quote_lbl.font())
        font_family = p.get("font_family", "")
        if font_family:
            quote_font.setFamily(font_family)
        quote_font.setPixelSize(max(8, font_size))
        self._quote_lbl.setFont(quote_font)
        quote_line_height = QFontMetrics(quote_font).lineSpacing()

        if self._current_text:
            self._quote_lbl.setText(self._current_text)
            self._quote_lbl.setAlignment(align_flag)
            self._quote_lbl.setStyleSheet(f"color:{color}; background:transparent;")
        else:
            hint_font = QFont(self._quote_lbl.font())
            hint_font.setPixelSize(14)
            self._quote_lbl.setFont(hint_font)
            self._quote_lbl.setText("右键 → 编辑 以配置并获取一言")
            self._quote_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            self._quote_lbl.setStyleSheet(f"color:{wc['empty_hint']}; background:transparent;")

        if show_src and self._current_source:
            src_size = max(11, font_size - 5)
            src_font = QFont(self._source_lbl.font())
            if font_family:
                src_font.setFamily(font_family)
            src_font.setPixelSize(src_size)
            self._source_lbl.setFont(src_font)
            self._source_lbl.setText(self._current_source)
            self._source_lbl.setAlignment(align_flag)
            if self._is_dark():
                qc = QColor(color)
                self._source_lbl.setStyleSheet(
                    f"color:rgba({qc.red()},{qc.green()},{qc.blue()},187); background:transparent;"
                )
            else:
                self._source_lbl.setStyleSheet(f"color:{wc['secondary']}; background:transparent;")
            self._source_gap.changeSize(
                0, gap_lines * quote_line_height, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
            )
            self._source_lbl.setVisible(True)
        else:
            self._source_gap.changeSize(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            self._source_lbl.setVisible(False)

        # 扩展行（教材等）：小号徽章，跟随出处行的显示开关与对齐方式
        if show_src and self._extra_labels:
            extra_size = max(10, font_size - 7)
            extra_font = QFont(self._extra_labels[0].font())
            if font_family:
                extra_font.setFamily(font_family)
            extra_font.setPixelSize(extra_size)
            extra_align = _EXTRA_ALIGN_MAP.get(align, Qt.AlignmentFlag.AlignHCenter)
            for lbl in self._extra_labels:
                lbl.setFont(extra_font)
                lbl.setStyleSheet(
                    f"color:{wc['secondary']}; border:1px solid {wc['tertiary']};"
                    f"border-radius:10px; padding:1px 8px; background:transparent;"
                )
                self._extras_layout.setAlignment(lbl, extra_align)
            self._extra_container.setVisible(True)
        else:
            self._extra_container.setVisible(False)

        self._status_lbl.setStyleSheet(f"color:{wc['tertiary']}; font-size:12px; background:transparent;")
        self._root_layout.invalidate()

    def _ensure_feature_access(self, feature_key: str, *, reason: str) -> bool:
        permission_service = self.services.get("permission_service")
        if permission_service is None:
            # 与 PluginAPI.ensure_access 一致：服务缺失时按拒绝处理
            return False
        try:
            return bool(permission_service.ensure_access(feature_key, parent=self.window(), reason=reason))
        except Exception:
            return False
