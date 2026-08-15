"""
首页智能推荐服务

算法概述
--------
综合分 = active_boost × [
    recency_weight    × 近期使用分（指数衰减，半衰期 7 天）
    + frequency_weight  × 使用频率分（指数衰减的有效访问数，半衰期 30 天，对数化）
    + tod_weight        × 时段偏好分（当前时段历史占比 × 样本量置信度收缩）
    + novelty_weight    × 探索新奇分（从未使用过的功能小加成）
    + session_weight    × 会话质量分（平均会话时长 × 会话数置信度）
]

运行中的功能乘以 ACTIVE_MULTIPLIER（默认 10），确保卡片置顶显示。

针对早期版本的三点校正：
1. 频率不再用终身累计次数，改用带 30 天半衰期的有效访问质量，
   避免“半年前常用、之后弃用”的功能长期霸榜；
2. 时段偏好加入样本量收缩（share × n/(n+K)），仅几次访问
   不再虚高到满分；
3. 会话质量加入置信度因子（min(1, n/K)），单次偶发长会话
   不再与稳定长会话同分。

探索噪声按“特征 + 日期”确定性生成：同一天内排序稳定
（避免每次刷新卡片抖动），跨天自动轮换保证多样性。

数据存储：config/recommendations.json
每次访问功能页面 / 主动启动功能时自动记录，数据持久化到磁盘。
"""
from __future__ import annotations

import math
import random
import time
from datetime import datetime
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal, QTimer

from app.constants import RECOMMENDATIONS_CONFIG
from app.utils.time_utils import load_json, save_json
from app.utils.logger import logger

# ─────────────────────────────────────────────────────────────────────────── #
# 常量
# ─────────────────────────────────────────────────────────────────────────── #

_TOD_SLOTS = 8                # 将 24h 划为 8 个 3h 段
_HALF_LIFE_DAYS = 7.0         # 近期分半衰期（天）
_VISIT_HALF_LIFE_DAYS = 30.0  # 频率分有效访问数半衰期（天）
_ACTIVE_MULTIPLIER = 10.0     # 活跃功能的分数倍增系数
_EXPLORE_NOISE = 0.04         # 探索噪声幅度，避免推荐固化

_TOD_SMOOTH     = 8.0   # 时段分平滑先验（等效样本量，越大越保守）
_FREQ_SATURATE  = 40.0  # 频率分饱和点：有效访问数达到该值 ≈ 满分
_SESSION_CONF   = 5.0   # 会话质量置信度饱和点：会话数达到该值 ≈ 全信

# 各维度权重（和为 1）
_W_RECENCY    = 0.35
_W_FREQUENCY  = 0.25
_W_TOD        = 0.20
_W_NOVELTY    = 0.10
_W_SESSION    = 0.10      # 会话质量（平均使用时长）

# 预计算衰减/归一化常量，避免评分热路径重复计算
_LN2            = math.log(2.0)
_RECENCY_DECAY  = _LN2 / _HALF_LIFE_DAYS       # 每日衰减系数
_VISIT_DECAY    = _LN2 / _VISIT_HALF_LIFE_DAYS
_LOG10_31       = math.log10(31.0)             # 会话时长 30min 的归一化分母
_LOG10_FREQ_SAT = math.log10(1.0 + _FREQ_SATURATE)

# 功能 ID（与导航 key 对齐）
FEATURE_WORLD_TIME  = "world_time"
FEATURE_ALARM       = "alarm"
FEATURE_TIMER       = "timer"
FEATURE_STOPWATCH   = "stopwatch"
FEATURE_FOCUS       = "focus"
FEATURE_PLUGIN      = "plugin"
FEATURE_AUTOMATION  = "automation"
FEATURE_FULLSCREEN_CLOCK_PREFIX = "world_time.fullscreen:"

ALL_FEATURES: tuple[str, ...] = (
    FEATURE_WORLD_TIME, FEATURE_ALARM, FEATURE_TIMER,
    FEATURE_STOPWATCH,  FEATURE_FOCUS, FEATURE_PLUGIN,
    FEATURE_AUTOMATION,
)

_BUILTIN_FEATURE_SET: set[str] = set(ALL_FEATURES)

# 可显示的功能名称
FEATURE_LABELS: dict[str, str] = {
    FEATURE_WORLD_TIME: "世界时间",
    FEATURE_ALARM:      "闹钟",
    FEATURE_TIMER:      "计时器",
    FEATURE_STOPWATCH:  "秒表",
    FEATURE_FOCUS:      "专注模式",
    FEATURE_PLUGIN:     "插件",
    FEATURE_AUTOMATION: "自动化",
}


def build_fullscreen_clock_feature(zone_id: str) -> str:
    """返回指定世界时钟全屏画布的推荐特征 ID。"""
    zid = str(zone_id or "").strip()
    return f"{FEATURE_FULLSCREEN_CLOCK_PREFIX}{zid}" if zid else FEATURE_WORLD_TIME


def parse_fullscreen_clock_feature(feature: str) -> str:
    """从推荐特征 ID 中解析全屏时钟的 zone_id，不匹配时返回空字符串。"""
    fid = str(feature or "").strip()
    if not fid.startswith(FEATURE_FULLSCREEN_CLOCK_PREFIX):
        return ""
    return fid[len(FEATURE_FULLSCREEN_CLOCK_PREFIX):].strip()


def fullscreen_clock_feature_label(zone_name: str) -> str:
    """生成全屏时钟推荐特征的展示名称。"""
    name = str(zone_name or "").strip()
    return f"{name} 全屏时钟" if name else "全屏时钟"


# ─────────────────────────────────────────────────────────────────────────── #
# 单功能统计
# ─────────────────────────────────────────────────────────────────────────── #

class FeatureStats:
    """单个功能的历史使用统计"""

    __slots__ = (
        "visit_count", "last_visit", "total_session_ms",
        "session_count", "tod_slots", "freq_mass", "freq_ts",
    )

    def __init__(self, data: dict | None = None) -> None:
        d = data or {}
        self.visit_count:      int        = int(d.get("visit_count", 0))
        self.last_visit:       float      = float(d.get("last_visit", 0.0))
        self.total_session_ms: int        = int(d.get("total_session_ms", 0))
        self.session_count:    int        = int(d.get("session_count", 0))
        self.freq_mass:        float      = float(d.get("freq_mass", 0.0))
        self.freq_ts:          float      = float(d.get("freq_ts", 0.0))
        raw_slots = d.get("tod_slots", [])
        self.tod_slots: list[int] = (
            list(raw_slots)[:_TOD_SLOTS]
            if isinstance(raw_slots, list) and len(raw_slots) >= _TOD_SLOTS
            else [0] * _TOD_SLOTS
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "visit_count":      self.visit_count,
            "last_visit":       self.last_visit,
            "total_session_ms": self.total_session_ms,
            "session_count":    self.session_count,
            "tod_slots":        self.tod_slots,
            "freq_mass":        self.freq_mass,
            "freq_ts":          self.freq_ts,
        }

    # ── 记录事件 ──────────────────────────────────────────────────────── #

    def record_visit(self) -> None:
        """导航到此功能页面时调用"""
        now = time.time()
        # 先把旧质量衰减到当前时刻，再 +1，保证半衰期语义连续
        self.freq_mass = self.effective_visits(now) + 1.0
        self.freq_ts   = now
        self.visit_count += 1
        self.last_visit   = now
        slot = datetime.now().hour * _TOD_SLOTS // 24
        self.tod_slots[slot] += 1

    def record_session_start(self) -> None:
        """主动启动功能（开始计时、开始专注等）时调用"""
        self.session_count += 1
        self.record_visit()

    def add_session_ms(self, ms: int) -> None:
        self.total_session_ms += max(0, ms)

    # ── 有效访问数（频率分的底层信号） ──────────────────────────────── #

    def effective_visits(self, now: float | None = None) -> float:
        """带 30 天半衰期指数衰减的有效访问质量。

        旧版本数据无 ``freq_mass`` 字段时，以终身 ``visit_count``
        从 ``last_visit`` 起衰减回退，首次记录后自动切换为增量口径。
        """
        now = time.time() if now is None else now
        if self.freq_ts <= 0.0:
            if self.last_visit <= 0.0:
                return float(self.visit_count)
            age_days = max(0.0, (now - self.last_visit) / 86_400)
            return float(self.visit_count) * math.exp(-_VISIT_DECAY * age_days)
        age_days = max(0.0, (now - self.freq_ts) / 86_400)
        return self.freq_mass * math.exp(-_VISIT_DECAY * age_days)

    # ── 各维度评分 ────────────────────────────────────────────────────── #

    def recency_score(self, now: float | None = None) -> float:
        """近期使用分 [0, 1]，按指数衰减"""
        if self.last_visit == 0:
            return 0.0
        now = time.time() if now is None else now
        age_days = max(0.0, (now - self.last_visit) / 86_400)
        return math.exp(-_RECENCY_DECAY * age_days)

    def frequency_score(self, now: float | None = None) -> float:
        """使用频率分 [0, 1]，对有效访问数对数化，防止高频功能过度主导"""
        eff = self.effective_visits(now)
        if eff <= 0.0:
            return 0.0
        return min(1.0, math.log10(1.0 + eff) / _LOG10_FREQ_SAT)

    def tod_share(self, now: float | None = None) -> tuple[float, int]:
        """返回 (当前时段历史占比, 历史总访问数)，供评分与推荐理由共用。"""
        if now is None:
            slot = datetime.now().hour * _TOD_SLOTS // 24
        else:
            slot = datetime.fromtimestamp(now).hour * _TOD_SLOTS // 24
        total = sum(self.tod_slots)
        if total <= 0:
            return 0.0, 0
        return self.tod_slots[slot] / total, total

    def tod_score(self, now: float | None = None) -> float:
        """时段偏好分 [0, 1]：当前时段历史占比 × 样本量置信度收缩

        ``share × n/(n+K)`` 保证只有足够多的历史样本才能撑起高时段分，
        避免“只在该时段用过 1 次”的功能得分虚高。
        """
        share, total = self.tod_share(now)
        if total <= 0:
            return 0.0
        return share * (total / (total + _TOD_SMOOTH))

    def novelty_score(self) -> float:
        """探索新奇分：从未使用过时为 1.0，否则 0"""
        return 1.0 if self.visit_count == 0 else 0.0

    def session_quality_score(self) -> float:
        """会话质量分 [0, 1]：平均会话时长 × 会话数置信度

        平均会话时长 ≥ 30 分钟时接近 1.0；再乘以 ``min(1, n/K)``，
        避免偶发单次长会话与稳定多次长会话同分。
        从未启动过会话则得 0。
        """
        if self.session_count == 0:
            return 0.0
        avg_min = (self.total_session_ms / self.session_count) / 60_000
        quality = min(1.0, math.log10(1.0 + avg_min) / _LOG10_31)
        confidence = min(1.0, self.session_count / _SESSION_CONF)
        return quality * confidence

    # ── 综合分 ────────────────────────────────────────────────────────── #

    def composite(
        self,
        is_active: bool = False,
        now: float | None = None,
    ) -> float:
        base = (
            _W_RECENCY   * self.recency_score(now)
            + _W_FREQUENCY * self.frequency_score(now)
            + _W_TOD       * self.tod_score(now)
            + _W_NOVELTY   * self.novelty_score()
            + _W_SESSION   * self.session_quality_score()
        )
        return base * (_ACTIVE_MULTIPLIER if is_active else 1.0)


# ─────────────────────────────────────────────────────────────────────────── #
# 推荐服务（单例）
# ─────────────────────────────────────────────────────────────────────────── #

class RecommendationService(QObject):
    """
    首页推荐引擎单例。

    信号
    ----
    updated()  — 统计数据变更时发出，首页视图可连接此信号刷新卡片。
    """

    updated = Signal()

    _instance: Optional["RecommendationService"] = None

    @classmethod
    def instance(cls) -> "RecommendationService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._stats: dict[str, FeatureStats] = {}
        self._feature_labels: dict[str, str] = dict(FEATURE_LABELS)
        self._session_starts: dict[str, float] = {}   # feature -> monotonic start
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(1200)
        self._save_timer.timeout.connect(self._save)
        self._load()

    def _ensure_feature(self, feature: str, *, label: str = "") -> FeatureStats | None:
        fid = str(feature or "").strip()
        if not fid:
            return None

        st = self._stats.get(fid)
        if st is None:
            st = FeatureStats()
            self._stats[fid] = st
        if label:
            self._feature_labels[fid] = str(label).strip()
        elif fid not in self._feature_labels:
            self._feature_labels[fid] = fid
        return st

    @staticmethod
    def _dedupe_features(features: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in features:
            fid = str(item or "").strip()
            if not fid or fid in seen:
                continue
            seen.add(fid)
            result.append(fid)
        return result

    def register_feature(self, feature: str, label: str = "") -> bool:
        """注册一个可参与推荐评分的特征。"""
        st = self._ensure_feature(feature, label=label)
        if st is None:
            logger.warning("[推荐] 注册特征失败：feature='{}'", feature)
            return False
        self._save()
        self.updated.emit()
        logger.info("[推荐] 注册特征：feature='{}', label='{}'", feature, self.feature_label(feature))
        return True

    def unregister_feature(self, feature: str, *, remove_stats: bool = False) -> bool:
        """注销自定义特征（内置特征不可注销）。"""
        fid = str(feature or "").strip()
        if not fid or fid in _BUILTIN_FEATURE_SET:
            logger.warning("[推荐] 注销特征失败：feature='{}' 不可注销", feature)
            return False
        existed = fid in self._stats or fid in self._feature_labels
        self._session_starts.pop(fid, None)
        self._feature_labels.pop(fid, None)
        if remove_stats:
            self._stats.pop(fid, None)
        self._save()
        self.updated.emit()
        logger.info("[推荐] 注销特征：feature='{}', remove_stats={}", fid, remove_stats)
        return existed

    def feature_label(self, feature: str) -> str:
        fid = str(feature or "").strip()
        return self._feature_labels.get(fid, fid)

    # ── 数据收集 API ───────────────────────────────────────────────────── #

    def on_view_shown(self, feature: str, *, label: str = "") -> None:
        """导航切换到某功能页面时调用（在 window.py 中钩入）"""
        st = self._ensure_feature(feature, label=label)
        if st is None:
            logger.warning("[推荐] 记录浏览失败：feature='{}' 无效", feature)
            return
        st.record_visit()
        self._save_debounced()
        self.updated.emit()
        logger.debug("[推荐] 记录浏览：feature='{}', visit_count={}", feature, st.visit_count)

    def on_session_start(self, feature: str, *, label: str = "") -> None:
        """用户主动执行操作（启动计时器、开始专注等）时调用"""
        st = self._ensure_feature(feature, label=label)
        if st is None:
            logger.warning("[推荐] 记录会话开始失败：feature='{}' 无效", feature)
            return
        st.record_session_start()
        self._session_starts[feature] = time.monotonic()
        self._save_debounced()
        self.updated.emit()
        logger.info("[推荐] 会话开始：feature='{}', session_count={}", feature, st.session_count)

    def on_session_end(self, feature: str) -> None:
        """功能会话结束时调用，自动累计本次使用时长"""
        t0 = self._session_starts.pop(feature, None)
        st = self._stats.get(feature)
        if t0 is not None and st is not None:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            st.add_session_ms(elapsed_ms)
            self._save_debounced()
            logger.info("[推荐] 会话结束：feature='{}', elapsed_ms={}, total_session_ms={}", feature, elapsed_ms, st.total_session_ms)
        else:
            logger.debug("[推荐] 会话结束跳过：feature='{}', has_start={}, has_stats={}", feature, t0 is not None, st is not None)

    # ── 推荐 API ───────────────────────────────────────────────────────── #

    def score(self, feature: str, is_active: bool = False) -> float:
        st = self._stats.get(feature)
        return st.composite(is_active) if st else 0.0

    def get_reason(self, feature: str) -> str:
        """
        根据使用统计智能生成推荐原因文字（返回空字符串表示无原因）。

        策略（按优先级）
        ---------------
        1. 从未使用 → 引导探索
        2. 当前时段历史占比高（> 35%）→ 时段习惯
        3. 高频使用（visit_count >= 10）→ 常用功能
        4. 近期使用（半衰期内 < 2 天）→ 最近用过
        5. 有会话时长记录 → 累计时长
        6. 默认兜底文案
        """
        st = self._stats.get(feature)
        name = self.feature_label(feature)
        if st is None:
            return ""

        # 1. 从未使用
        if st.visit_count == 0:
            return f"还没试过{name}？来探索一下吧 ✨"

        # 2. 时段偏好明显（占比高且样本量足够）
        share, total = st.tod_share()
        if share > 0.30 and total >= 4:
            _TOD_NAMES = ["深夜", "凌晨", "凌晨", "凌晨", "凌晨", "清晨", "清晨", "清晨",
                          "上午", "上午", "上午", "上午", "中午", "下午", "下午", "下午",
                          "下午", "傍晚", "傍晚", "晚上", "晚上", "晚上", "深夜", "深夜"]
            period = _TOD_NAMES[datetime.now().hour]
            return f"你通常在{period}使用{name}"

        # 3. 高频使用
        if st.visit_count >= 10:
            return f"{name}是你最常使用的功能之一"

        # 4. 近期使用（近 2 天活跃）
        recency = st.recency_score()
        if recency > 0.86:  # ≈ 剩余衰减 > 86% ≈ 1天以内
            return f"你最近刚使用过{name}"
        if recency > 0.71:  # ≈ 2 天以内
            return f"你近期频繁使用{name}"

        # 5. 有累计使用时长
        total_min = st.total_session_ms / 60_000
        if total_min >= 60:
            return f"累计使用 {total_min:.0f} 分钟，高效用户 🏆"
        if total_min >= 5:
            return "基于你的使用习惯推荐"

        # 6. 兜底
        return ""

    @staticmethod
    def _explore_noise(fid: str) -> float:
        """按“特征 + 日期”确定性生成探索噪声。

        同一天内多次调用结果一致（首页刷新不抖动、结果可复现），
        跨天自动轮换，保持推荐的多样化。
        """
        seed = f"{fid}|{datetime.now().strftime('%Y-%m-%d')}"
        return random.Random(seed).uniform(0.0, _EXPLORE_NOISE)

    def _rank_features(
        self,
        feature_ids: list[str],
        active_features: set[str] | None = None,
        exclude: set[str] | None = None,
        explore: bool = True,
    ) -> list[tuple[str, float]]:
        active = active_features or set()
        excluded = exclude or set()
        now = time.time()

        ids = self._dedupe_features(feature_ids)
        results = [
            (fid, self._stats[fid].composite(fid in active, now=now))
            for fid in ids
            if fid not in excluded and fid in self._stats
        ]
        # ε-探索：对非活跃功能加入确定性小扰动，让推荐多样化。
        # 活跃功能分数极高，扰动不影响其排名。
        if explore:
            results = [
                (
                    fid,
                    score + self._explore_noise(fid)
                    if fid not in active else score,
                )
                for fid, score in results
            ]
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def ranked(
        self,
        active_features: set[str] | None = None,
        exclude: set[str] | None = None,
        explore: bool = True,
        include_custom: bool = False,
    ) -> list[tuple[str, float]]:
        """
        返回按综合分降序的 ``[(feature_id, score), ...]``。

        Parameters
        ----------
        active_features : 当前处于活跃状态的功能集（用于加分）
        exclude         : 不参与排名的功能集
        explore         : 是否加入 ε-探索噪声，防止推荐结果固化（默认开启）
        """
        feature_ids = list(ALL_FEATURES)
        if include_custom:
            feature_ids.extend(fid for fid in self._stats if fid not in _BUILTIN_FEATURE_SET)
        result = self._rank_features(
            feature_ids,
            active_features=active_features,
            exclude=exclude,
            explore=explore,
        )
        logger.trace(
            "[推荐] 生成排序：total_features={}, active={}, exclude={}, include_custom={}, explore={}, result={}",
            len(feature_ids),
            len(active_features or set()),
            len(exclude or set()),
            include_custom,
            explore,
            len(result),
        )
        return result

    def ranked_for(
        self,
        feature_ids: list[str],
        *,
        active_features: set[str] | None = None,
        exclude: set[str] | None = None,
        explore: bool = True,
    ) -> list[tuple[str, float]]:
        """按指定特征列表返回推荐排序。"""
        return self._rank_features(
            feature_ids,
            active_features=active_features,
            exclude=exclude,
            explore=explore,
        )

    # ── 统计查询 ───────────────────────────────────────────────────────── #

    def get_stats(self, feature: str) -> FeatureStats | None:
        return self._stats.get(feature)

    def all_stats(self) -> dict[str, FeatureStats]:
        return dict(self._stats)

    def debug_rows(self) -> list[tuple[str, str]]:
        """适合调试面板 KV 表格展示的摘要行"""
        rows: list[tuple[str, str]] = []
        feature_ids = list(ALL_FEATURES)
        feature_ids.extend(fid for fid in self._stats if fid not in _BUILTIN_FEATURE_SET)
        for fid in feature_ids:
            st = self._stats.get(fid)
            if st is None:
                rows.append((self.feature_label(fid), "—"))
                continue
            last_str = (
                "从未" if st.last_visit == 0
                else datetime.fromtimestamp(st.last_visit).strftime("%m-%d %H:%M")
            )
            total_min = st.total_session_ms / 60_000
            rows.append((
                self.feature_label(fid),
                (
                    f"浏览 {st.visit_count} 次 | "
                    f"会话 {st.session_count} 次 | "
                    f"累计 {total_min:.1f} 分钟 | "
                    f"最近 {last_str} | "
                    f"综合分 {st.composite():.4f} "
                    f"(近期={st.recency_score():.2f} "
                    f"频率={st.frequency_score():.2f} "
                    f"有效 {st.effective_visits():.1f} "
                    f"时段={st.tod_score():.2f} "
                    f"质量={st.session_quality_score():.2f})"
                ),
            ))
        return rows

    def reset(self) -> None:
        """清空所有统计数据"""
        for st in self._stats.values():
            st.__init__()
        self._session_starts.clear()
        self._save()
        self.updated.emit()
        logger.info("[推荐] 使用统计已重置")

    # ── 持久化 ─────────────────────────────────────────────────────────── #

    def _save_debounced(self) -> None:
        # 高频埋点（浏览/会话）采用短延迟批量落盘，减少频繁 I/O。
        self._save_timer.start()

    def flush_pending_save(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save()

    def _load(self) -> None:
        data  = load_json(RECOMMENDATIONS_CONFIG, {})
        saved = data.get("stats", {})
        saved_labels = data.get("feature_labels", {})

        for fid in ALL_FEATURES:
            raw = saved.get(fid)
            self._stats[fid] = FeatureStats(raw if isinstance(raw, dict) else None)

        # 兼容旧数据：保留历史中的自定义特征
        if isinstance(saved, dict):
            for fid, raw in saved.items():
                if fid in self._stats:
                    continue
                self._stats[fid] = FeatureStats(raw if isinstance(raw, dict) else None)
                self._feature_labels.setdefault(fid, fid)

        if isinstance(saved_labels, dict):
            for fid, label in saved_labels.items():
                if fid in self._stats and isinstance(label, str) and label.strip():
                    self._feature_labels[fid] = label.strip()
        logger.debug("[推荐] 统计数据已加载")

    def _save(self) -> None:
        data = {
            "stats": {fid: st.to_dict() for fid, st in self._stats.items()},
            "feature_labels": {
                fid: label
                for fid, label in self._feature_labels.items()
                if fid in self._stats and label
            },
        }
        save_json(RECOMMENDATIONS_CONFIG, data)
        logger.debug("[推荐] 统计数据已保存：features={}, labels={}", len(self._stats), len(data["feature_labels"]))
