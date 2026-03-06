"""铃声播放服务（跨平台：Windows 用 winsound；其他平台用 QMediaPlayer）"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from app.utils.logger import logger

# ── 平台检测 ────────────────────────────────────────────────────────── #
_IS_WIN = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"

if _IS_WIN:
    import winsound  # type: ignore[import]

# 支持的扩展名（QMediaPlayer 可处理更多，这里仅用于 UI 过滤提示）
SUPPORTED_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".aac", ".m4a", ".wma"}

# ── 播放器池（避免重复创建 / 保持引用防止 GC）────────────────────────── #
_players: list[tuple[QMediaPlayer, QAudioOutput]] = []

# ── 循环播放状态 ─────────────────────────────────────────────────────── #
_loop_player: tuple[QMediaPlayer, QAudioOutput] | None = None
_loop_wav_active: bool = False
_loop_beep_event: threading.Event = threading.Event()
_loop_beep_thread: threading.Thread | None = None


def _make_player() -> tuple[QMediaPlayer, QAudioOutput]:
    """创建一对 QMediaPlayer + QAudioOutput"""
    player = QMediaPlayer()
    output = QAudioOutput()
    player.setAudioOutput(output)
    output.setVolume(1.0)
    return player, output


def play_sound(path: str) -> None:
    """
    非阻塞播放铃声文件。
    - path 为空          → play_default()
    - 不存在             → play_default() + 警告
    - Windows + .wav     → winsound 后台线程（可靠）
    - 其他情况           → QMediaPlayer 异步
    """
    logger.warning("[铃声] play_sound 调用：{!r}", path)
    if not path:
        play_default()
        return

    p = Path(path)
    if not p.exists():
        logger.warning("[铃声] 文件不存在：{}", path)
        play_default()
        return

    if _IS_WIN and p.suffix.lower() == ".wav":
        # WAV on Windows：直接用 winsound，100% 可靠
        def _run_wav() -> None:
            try:
                winsound.PlaySound(str(p), winsound.SND_FILENAME)
                logger.debug("[铃声] WAV 播放完成：{}", p.name)
            except Exception as exc:
                logger.warning("[铃声] winsound 失败：{}，回退提示音", exc)
                _beep()
        threading.Thread(target=_run_wav, daemon=True).start()
        logger.debug("[铃声] WAV 线程已启动：{}", p.name)
        return

    # 非 Windows / 非 WAV：QMediaPlayer
    try:
        player, output = _make_player()
        _players.append((player, output))

        def _cleanup() -> None:
            try:
                _players.remove((player, output))
            except ValueError:
                pass

        def _on_status(status: QMediaPlayer.MediaStatus) -> None:
            logger.warning("[铃声] QMP 状态：{} — {}", p.name, status)
            if status == QMediaPlayer.MediaStatus.InvalidMedia:
                logger.warning("[铃声] 不支持的格式：{}，回退提示音", path)
                _beep()
                _cleanup()
            elif status == QMediaPlayer.MediaStatus.EndOfMedia:
                _cleanup()

        def _on_error(error: QMediaPlayer.Error, msg: str) -> None:
            logger.warning("[铃声] QMP 错误 {} — {}，回退提示音", error, msg)
            _beep()
            _cleanup()

        player.mediaStatusChanged.connect(_on_status)
        player.errorOccurred.connect(_on_error)
        player.setSource(QUrl.fromLocalFile(str(p)))
        player.play()
        logger.warning("[铃声] QMP play() 已调用，playbackState={}",
                       player.playbackState())
    except Exception as exc:
        logger.warning("[铃声] QMediaPlayer 异常：{}，回退提示音", exc)
        _beep()


def play_default() -> None:
    """播放系统默认提示音（非阻塞）"""
    logger.warning("[铃声] play_default 调用")
    threading.Thread(target=_beep, daemon=True).start()


# ── 循环播放（用于闹钟提醒）─────────────────────────────────────────── #

def play_sound_loop(path: str) -> None:
    """
    循环播放铃声文件，直到调用 stop_loop() 为止。
    - .wav   → winsound SND_LOOP + SND_ASYNC
    - 其他   → QMediaPlayer setLoops(-1)
    - 空/不存在 → 循环蜂鸣
    """
    global _loop_player, _loop_wav_active, _loop_beep_event, _loop_beep_thread

    stop_loop()   # 先停止之前的循环

    if not path:
        _start_beep_loop()
        return

    p = Path(path)
    if not p.exists():
        logger.warning("[铃声] 循环播放：文件不存在 {}，回退默认", path)
        _start_beep_loop()
        return

    if _IS_WIN and p.suffix.lower() == ".wav":
        try:
            winsound.PlaySound(
                str(p),
                winsound.SND_FILENAME | winsound.SND_LOOP | winsound.SND_ASYNC,
            )
            _loop_wav_active = True
            logger.debug("[铃声] WAV 循环已启动：{}", p.name)
        except Exception as exc:
            logger.warning("[铃声] WAV 循环失败：{}，回退默认", exc)
            _start_beep_loop()
        return

    # 非 WAV：QMediaPlayer 无限循环（需在主线程调用）
    try:
        player, output = _make_player()
        _loop_player = (player, output)
        player.setLoops(-1)   # QMediaPlayer.Loops.Infinite
        player.setSource(QUrl.fromLocalFile(str(p)))
        player.play()
        logger.debug("[铃声] QMP 循环已启动：{}", p.name)
    except Exception as exc:
        logger.warning("[铃声] QMP 循环失败：{}，回退默认", exc)
        _loop_player = None
        _start_beep_loop()


def play_default_loop() -> None:
    """循环播放系统默认提示音"""
    global _loop_beep_event, _loop_beep_thread
    stop_loop()
    _start_beep_loop()


def stop_loop() -> None:
    """停止所有循环播放"""
    global _loop_player, _loop_wav_active, _loop_beep_event, _loop_beep_thread

    # 停止 WAV 循环（仅 Windows）
    if _IS_WIN and _loop_wav_active:
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        _loop_wav_active = False

    # 停止 QMediaPlayer 循环
    if _loop_player is not None:
        try:
            _loop_player[0].stop()
        except Exception:
            pass
        _loop_player = None

    # 停止蜂鸣循环
    _loop_beep_event.set()
    _loop_beep_thread = None


def _start_beep_loop() -> None:
    """在后台线程中循环蜂鸣"""
    global _loop_beep_event, _loop_beep_thread
    _loop_beep_event = threading.Event()

    def _loop() -> None:
        while not _loop_beep_event.is_set():
            _beep()
            _loop_beep_event.wait(2.5)

    _loop_beep_thread = threading.Thread(target=_loop, daemon=True)
    _loop_beep_thread.start()
    logger.debug("[铃声] 蜂鸣循环已启动")


def _beep() -> None:
    """播放一次系统提示音（同步，可在任意线程调用）"""
    if _IS_WIN:
        # Windows：优先走系统音效别名，最后兜底 MessageBeep
        for alias in ("SystemExclamation", "SystemAsterisk", "SystemDefault", ".Default"):
            try:
                winsound.PlaySound(alias, winsound.SND_ALIAS)   # 同步，等播完再返回
                return
            except Exception:
                continue
        try:
            winsound.MessageBeep()
        except Exception:
            pass
    elif _IS_MAC:
        # macOS：afplay 系统声音文件
        _mac_candidates = [
            "/System/Library/Sounds/Ping.aiff",
            "/System/Library/Sounds/Glass.aiff",
            "/System/Library/Sounds/Tink.aiff",
        ]
        for sound_file in _mac_candidates:
            try:
                subprocess.run(
                    ["afplay", sound_file],
                    capture_output=True, timeout=5,
                )
                return
            except Exception:
                continue
        print("\a", end="", flush=True)
    else:
        # Linux / 其他：尝试 paplay / aplay，最后回退终端铃声
        _linux_candidates = [
            ["paplay", "/usr/share/sounds/freedesktop/stereo/bell.oga"],
            ["aplay",  "/usr/share/sounds/freedesktop/stereo/bell.wav"],
            ["aplay",  "/usr/share/sounds/alsa/Front_Center.wav"],
        ]
        for cmd in _linux_candidates:
            try:
                if subprocess.run(cmd, capture_output=True, timeout=5).returncode == 0:
                    return
            except Exception:
                continue
        print("\a", end="", flush=True)


def get_builtin_ringtones() -> list[dict]:
    """
    返回当前平台内置的预设铃声列表。

    - Windows：扫描 C:/Windows/Media/ 中的 Alarm01–Alarm10 和 Ring01–Ring10
    - 其他平台：返回空列表
    """
    result: list[dict] = []
    if _IS_WIN:
        media_dir = Path("C:/Windows/Media")
        for prefix in ("Alarm", "Ring"):
            for i in range(1, 11):
                p = media_dir / f"{prefix}{i:02d}.wav"
                if p.exists():
                    result.append({"name": f"Windows {prefix} {i:02d}", "path": str(p)})
    return result


def make_sound_combo(ringtones: list[dict]) -> object:
    """
    创建铃声 ComboBox。
    第 0 项为"系统默认"（路径=""），其次为平台内置铃声，最后为用户铃声。
    路径列表存在 combo._rs_paths 中，通过 get_combo_sound / set_combo_sound 读写。
    """
    from qfluentwidgets import ComboBox

    paths: list[str] = [""]
    cb = ComboBox()
    cb.addItem("系统默认")

    # 平台内置铃声（Windows: Alarm01–10 / Ring01–10）
    for r in get_builtin_ringtones():
        cb.addItem(r.get("name", r["path"]))
        paths.append(r["path"])

    # 用户自定义铃声
    for r in ringtones:
        cb.addItem(r.get("name", r["path"]))
        paths.append(r["path"])

    cb._rs_paths = paths  # type: ignore[attr-defined]
    return cb


def get_combo_sound(combo) -> str:
    """返回铃声 ComboBox 当前选中项的文件路径（""表示系统默认）。"""
    paths: list[str] = getattr(combo, "_rs_paths", [""])
    idx = combo.currentIndex()
    if 0 <= idx < len(paths):
        return paths[idx]
    return ""


def set_combo_sound(combo, path: str) -> None:
    """设置铃声 ComboBox 选中与 path 匹配的项。找不到则保持第 0 项。"""
    paths: list[str] = getattr(combo, "_rs_paths", [""])
    try:
        idx = paths.index(path)
        combo.setCurrentIndex(idx)
    except ValueError:
        combo.setCurrentIndex(0)


def select_sound_path(parent=None) -> tuple[str, str] | None:
    """
    弹出文件选择对话框让用户选择一个 .wav 铃声文件。

    返回
    ----
    (name, path)  选择成功；None  用户取消
    """
    from PySide6.QtWidgets import QFileDialog, QInputDialog

    path, _ = QFileDialog.getOpenFileName(
        parent,
        "选择铃声文件",
        "",
        "音频文件 (*.wav *.mp3 *.ogg *.flac *.aac *.m4a *.wma);;所有文件 (*.*)",
    )
    if not path:
        return None

    default_name = Path(path).stem
    name, ok = QInputDialog.getText(
        parent,
        "铃声名称",
        "为这个铃声起个名字：",
        text=default_name,
    )
    if not ok or not name.strip():
        name = default_name

    return (name.strip() or default_name, path)
