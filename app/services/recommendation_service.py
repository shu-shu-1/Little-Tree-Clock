"""
首页智能推荐服务

算法概述
--------
综合分 = active_boost × [
    recency_weight    × 近期使用分（指数衰减，半衰期 7 天）
    + frequency_weight  × 使用频率分（对数化）
    + tod_weight        × 时段偏好分（当前时段历史占比）
    + novelty_weight    × 探索新奇分（从未使用过的功能小加成）
]

运行中的功能乘以 ACTIVE_MULTIPLIER（默认 10），确保卡片置顶显示。

数据存储：config/recommendations.json
每次访问功能页面 / 主动启动功能时自动记录，数据持久化到磁盘。
"""
from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

from app.constants import RECOMMENDATIONS_CONFIG
from app.utils.time_utils import load_json, save_json
from app.utils.logger import logger

# ─────────────────────────────────────────────────────────────────────────── #
# 常量
# ─────────────────────────────────────────────────────────────────────────── #

_TOD_SLOTS = 8            # 将 24h 划为 8 个 3h 段
_HALF_LIFE_DAYS = 7.0     # 近期分半衰期（天）
_ACTIVE_MULTIPLIER = 10.0 # 活跃功能的分数倍增系数
_EXPLORE_NOISE = 0.04     # 探索噪声幅度，避免推荐固化

# 各维度权重（和为 1）
_W_RECENCY    = 0.35
_W_FREQUENCY  = 0.25
_W_TOD        = 0.20
_W_NOVELTY    = 0.10
_W_SESSION    = 0.10      # 会话质量（平均使用时长）

# 功能 ID（与导航 key 对齐）
FEATURE_WORLD_TIME  = "world_time"
FEATURE_ALARM       = "alarm"
FEATURE_TIMER       = "timer"
FEATURE_STOPWATCH   = "stopwatch"
FEATURE_FOCUS       = "focus"
FEATURE_PLUGIN      = "plugin"
FEATURE_AUTOMATION  = "automation"

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


# ─────────────────────────────────────────────────────────────────────────── #
# 单功能统计
# ─────────────────────────────────────────────────────────────────────────── #

class FeatureStats:
    """单个功能的历史使用统计"""

    __slots__ = (
        "visit_count", "last_visit", "total_session_ms",
        "session_count", "tod_slots",
    )

    def __init__(self, data: dict | None = None) -> None:
        d = data or {}
        self.visit_count:      int        = int(d.get("visit_count", 0))
        self.last_visit:       float      = float(d.get("last_visit", 0.0))
        self.total_session_ms: int        = int(d.get("total_session_ms", 0))
        self.session_count:    int        = int(d.get("session_count", 0))
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
        }

    # ── 记录事件 ──────────────────────────────────────────────────────── #

    def record_visit(self) -> None:
        """导航到此功能页面时调用"""
        self.visit_count += 1
        self.last_visit   = time.time()
        slot = datetime.now().hour * _TOD_SLOTS // 24
        self.tod_slots[slot] += 1

    def record_session_start(self) -> None:
        """主动启动功能（开始计时、开始专注等）时调用"""
        self.session_count += 1
        self.record_visit()

    def add_session_ms(self, ms: int) -> None:
        self.total_session_ms += max(0, ms)

    # ── 各维度评分 ────────────────────────────────────────────────────── #

    def recency_score(self) -> float:
        """近期使用分 [0, 1]，按指数衰减"""
        if self.last_visit == 0:
            return 0.0
        age_days = (time.time() - self.last_visit) / 86_400
        return math.exp(-math.log(2) / _HALF_LIFE_DAYS * age_days)

    def frequency_score(self) -> float:
        """使用频率分 [0, 1]，对数化防止高频功能过度主导"""
        if self.visit_count == 0:
            return 0.0
        # visit_count=1000 时达到 1.0
        return min(1.0, math.log10(1 + self.visit_count) / 3.0)

    def tod_score(self) -> float:
        """时段偏好分 [0, 1]：当前时段在历史中的占比"""
        slot  = datetime.now().hour * _TOD_SLOTS // 24
        total = sum(self.tod_slots) or 1
        return self.tod_slots[slot] / total

    def novelty_score(self) -> float:
        """探索新奇分：从未使用过时为 1.0，否则 0"""
        return 1.0 if self.visit_count == 0 else 0.0

    def session_quality_score(self) -> float:
        """会话质量分 [0, 1]：基于平均每次会话时长（对数化）

        平均会话时长 ≥ 30 分钟时接近 1.0，鼓励使用时间较长的功能。
        从未启动过会话则得 0。
        """
        if self.session_count == 0:
            return 0.0
        avg_min = (self.total_session_ms / self.session_count) / 60_000
        # avg_min = 30min 时 → log10(31)/1.49 ≈ 1.0
        return min(1.0, math.log10(1 + avg_min) / math.log10(31))

    # ── 综合分 ────────────────────────────────────────────────────────── #

    def composite(self, is_active: bool = False) -> float:
        base = (
            _W_RECENCY   * self.recency_score()
            + _W_FREQUENCY * self.frequency_score()
            + _W_TOD       * self.tod_score()
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

    def on_view_shown(self, feature: str) -> None:
        """导航切换到某功能页面时调用（在 window.py 中钩入）"""
        st = self._ensure_feature(feature)
        if st is None:
            logger.warning("[推荐] 记录浏览失败：feature='{}' 无效", feature)
            return
        st.record_visit()
        self._save()
        self.updated.emit()
        logger.debug("[推荐] 记录浏览：feature='{}', visit_count={}", feature, st.visit_count)

    def on_session_start(self, feature: str) -> None:
        """用户主动执行操作（启动计时器、开始专注等）时调用"""
        st = self._ensure_feature(feature)
        if st is None:
            logger.warning("[推荐] 记录会话开始失败：feature='{}' 无效", feature)
            return
        st.record_session_start()
        self._session_starts[feature] = time.monotonic()
        self._save()
        self.updated.emit()
        logger.info("[推荐] 会话开始：feature='{}', session_count={}", feature, st.session_count)

    def on_session_end(self, feature: str) -> None:
        """功能会话结束时调用，自动累计本次使用时长"""
        t0 = self._session_starts.pop(feature, None)
        st = self._stats.get(feature)
        if t0 is not None and st is not None:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            st.add_session_ms(elapsed_ms)
            self._save()
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

        # 2. 时段偏好明显
        tod = st.tod_score()
        if tod > 0.35:
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

    def _rank_features(
        self,
        feature_ids: list[str],
        active_features: set[str] | None = None,
        exclude: set[str] | None = None,
        explore: bool = True,
    ) -> list[tuple[str, float]]:
        import random as _random

        active = active_features or set()
        excluded = exclude or set()

        ids = self._dedupe_features(feature_ids)
        results = [
            (fid, self._stats[fid].composite(fid in active))
            for fid in ids
            if fid not in excluded and fid in self._stats
        ]
        # ε-探索：对非活跃功能加入微小随机扰动，让推荐多样化
        # 活跃功能分数极高，扰动不影响其排名
        if explore:
            results = [
                (
                    fid,
                    score + _random.uniform(0, _EXPLORE_NOISE)
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
        logger.debug(
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

    def _load(self) -> None:
        data  = load_json(RECOMMENDATIONS_CONFIG, {})
        saved = data.get("stats", {})
        saved_labels = data.get("feature_labels", {})

        for fid in ALL_FEATURES:
            self._stats[fid] = FeatureStats(saved.get(fid))

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
