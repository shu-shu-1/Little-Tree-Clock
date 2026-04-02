"""音量报告读取服务。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from app.utils.fs import mkdir_with_uac, write_text_with_uac
from app.utils.logger import logger


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


@dataclass(slots=True)
class VolumeReportRecord:
    path: Path
    source_plugin: str
    modified_ts: float
    data: dict[str, Any]

    @property
    def item_name(self) -> str:
        metadata = self.data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        return str(
            self.data.get("item_name")
            or self.data.get("item_id")
            or metadata.get("item_name")
            or metadata.get("item_id")
            or "未命名事项"
        )

    @property
    def group_name(self) -> str:
        metadata = self.data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        return str(
            self.data.get("group_name")
            or self.data.get("group_id")
            or metadata.get("group_name")
            or metadata.get("group_id")
            or ""
        )

    @property
    def started_at(self) -> str:
        return str(self.data.get("study_started_at") or self.data.get("started_at") or "")

    @property
    def ended_at(self) -> str:
        return str(self.data.get("study_ended_at") or self.data.get("ended_at") or "")

    @property
    def max_db(self) -> float:
        return _safe_float(self.data.get("max_db"), -80.0)

    @property
    def avg_db(self) -> float:
        return _safe_float(self.data.get("avg_db"), -80.0)

    @property
    def threshold_db(self) -> float:
        return _safe_float(self.data.get("threshold_db"), -20.0)

    @property
    def duration_sec(self) -> float:
        return max(0.0, _safe_float(self.data.get("duration_sec"), 0.0))

    @property
    def exceed_duration_sec(self) -> float:
        return max(0.0, _safe_float(self.data.get("exceed_duration_sec"), 0.0))

    @property
    def exceed_count(self) -> int:
        try:
            return max(0, int(self.data.get("exceed_count", 0)))
        except Exception:
            return 0

    @property
    def device_name(self) -> str:
        return str(self.data.get("device_name") or "")

    @property
    def display_title(self) -> str:
        if self.group_name:
            return f"{self.item_name} · {self.group_name}"
        return self.item_name


class VolumeReportService:
    def __init__(self, *, data_dir: Path, api=None):
        self._data_dir = Path(data_dir)
        self._plugins_root = Path(__file__).resolve().parents[1]
        self._api = api
        self._central_config: dict[str, Any] = {}

    def set_central_config(self, config: Any) -> None:
        self._central_config = dict(config) if isinstance(config, dict) else {}

    def is_action_allowed(self, action_key: str) -> bool:
        key = str(action_key or "").strip()
        if not key:
            return True

        disabled = {
            str(item).strip()
            for item in self._central_config.get("disabled_actions", [])
            if str(item).strip()
        }
        if key in disabled:
            return False

        if bool(self._central_config.get("read_only", False)) and key in {
            "import_report",
            "delete_report",
        }:
            return False

        return True

    def ensure_access(
        self,
        feature_key: str,
        *,
        reason: str = "",
        parent: Optional[object] = None,
    ) -> bool:
        checker = getattr(self._api, "ensure_access", None)
        if not callable(checker):
            return True
        try:
            return bool(checker(feature_key, reason=reason, parent=parent))
        except Exception:
            return False

    def candidate_report_dirs(self) -> list[Path]:
        shared_data_root = self._data_dir.parent
        if shared_data_root.name != "._data":
            shared_data_root = self._plugins_root / "._data"

        candidates = [
            shared_data_root / "study_schedule" / "volume_reports",
            shared_data_root / "volume_detector" / "volume_reports",
            self._plugins_root / "study_schedule" / "volume_reports",
        ]
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)
        return deduped

    def existing_report_dirs(self) -> list[Path]:
        return [path for path in self.candidate_report_dirs() if path.exists() and path.is_dir()]

    def preferred_report_dir(self) -> Path:
        existing = self.existing_report_dirs()
        if existing:
            return existing[0]
        return self.candidate_report_dirs()[0]

    def list_records(self) -> list[VolumeReportRecord]:
        records: list[VolumeReportRecord] = []
        for report_dir in self.existing_report_dirs():
            source_plugin = report_dir.parent.name
            for report_file in self._iter_report_files(report_dir):
                data = self._read_report_file(report_file)
                if data is None:
                    continue
                try:
                    modified_ts = report_file.stat().st_mtime
                except OSError:
                    modified_ts = 0.0
                records.append(
                    VolumeReportRecord(
                        path=report_file,
                        source_plugin=source_plugin,
                        modified_ts=modified_ts,
                        data=data,
                    )
                )
        records.sort(key=lambda record: record.modified_ts, reverse=True)
        return records

    def import_report(self, source_path: str | Path) -> Path:
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"报告文件不存在: {source}")

        data = self._read_report_file(source)
        if data is None:
            raise ValueError("报告文件格式无效，无法导入")

        target_dir = self.preferred_report_dir()
        mkdir_with_uac(target_dir, parents=True, exist_ok=True)

        target = self._build_import_target_path(source, target_dir)
        data["saved_path"] = str(target)
        write_text_with_uac(
            target,
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
            ensure_parent=True,
        )
        return target

    def delete_report(self, report_path: str | Path) -> None:
        path = Path(report_path)
        if not path.exists():
            return
        if path.suffix.lower() != ".json":
            raise ValueError("只能删除 JSON 报告文件")

        resolved = path.resolve()
        allowed_dirs = [candidate.resolve() for candidate in self.candidate_report_dirs()]
        if not any(self._is_relative_to(resolved, root) for root in allowed_dirs):
            raise ValueError("仅允许删除报告目录中的文件")

        try:
            path.unlink()
        except Exception as exc:
            raise PermissionError(f"删除失败: {exc}") from exc

    @staticmethod
    def suggest_export_name(record: VolumeReportRecord) -> str:
        return f"{record.path.stem}.png"

    @staticmethod
    def _build_import_target_path(source: Path, target_dir: Path) -> Path:
        base_name = source.stem.strip() or "volume_report"
        target = target_dir / f"{base_name}.json"

        try:
            if source.resolve() == target.resolve():
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                target = target_dir / f"{base_name}-import-{timestamp}.json"
        except Exception:
            pass

        if not target.exists():
            return target

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        indexed_target = target_dir / f"{base_name}-import-{timestamp}.json"
        if not indexed_target.exists():
            return indexed_target

        counter = 1
        while True:
            candidate = target_dir / f"{base_name}-import-{timestamp}-{counter}.json"
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _is_relative_to(path: Path, base: Path) -> bool:
        try:
            path.relative_to(base)
            return True
        except ValueError:
            return False

    @staticmethod
    def _iter_report_files(report_dir: Path) -> list[Path]:
        files: list[Path] = []
        try:
            for path in report_dir.glob("*.json"):
                if path.is_file():
                    files.append(path)
        except OSError:
            return []

        files.sort(key=lambda item: item.name, reverse=True)
        return files

    @staticmethod
    def _read_report_file(report_file: Path) -> dict[str, Any] | None:
        try:
            raw = json.loads(report_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("[音量报告可视化] 跳过无法解析的报告文件: path={}, err={}", report_file, exc)
            return None

        if not isinstance(raw, dict):
            logger.debug("[音量报告可视化] 跳过非对象报告文件: path={}", report_file)
            return None

        raw.setdefault("saved_path", str(report_file))
        return raw
