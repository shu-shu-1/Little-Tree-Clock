"""小树时钟打包脚本。"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import zipfile

# ── 常量 ─────────────────────────────────────────────────────────────── #
PROJECT_ROOT = Path(__file__).resolve().parent
SPEC_FILE = PROJECT_ROOT / "little_tree.spec"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"
APP_NAME = "小树时钟"
CONSTANTS_FILE = PROJECT_ROOT / "app" / "constants.py"

# 随应用分发的目录/文件（从项目根复制到 dist/小树时钟/）
# 注意：config/ 不复制，应用运行时会自动创建默认配置
DISTRIBUTE_DIRS = ["plugins_ext"]
DISTRIBUTE_FILES = ["icon.png"]

IGNORE_PATTERNS = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "._data", ".git*", "*.ltcplugin")


# ── 辅助函数 ─────────────────────────────────────────────────────────── #


def print_banner(title: str, width: int = 60) -> None:
    print(f"\n{'═' * width}")
    print(f"  {title}")
    print("═" * width)


def print_section(title: str, width: int = 58) -> None:
    print(f"\n── {title} {'─' * (width - len(title) - 4)}")


def print_item(label: str, value: str, indent: int = 2) -> None:
    print(f"{' ' * indent}{label}：{value}")


def print_success(msg: str, indent: int = 2) -> None:
    print(f"{' ' * indent}✓ {msg}")


def print_warning(msg: str, indent: int = 2) -> None:
    print(f"{' ' * indent}! {msg}")


def print_error(msg: str, indent: int = 2) -> None:
    print(f"{' ' * indent}✗ {msg}")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"\n▶ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print_error(f"命令失败，退出码 {result.returncode}")
        sys.exit(result.returncode)
    return result


def get_platform_suffix() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        if machine in ("amd64", "x86_64"):
            return "win64"
        elif machine in ("x86", "i686", "i386"):
            return "win32"
        return "win"
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            return "mac-arm"
        return "mac-intel"
    elif system == "linux":
        if machine in ("amd64", "x86_64"):
            return "linux64"
        elif machine in ("arm64", "aarch64"):
            return "linux-arm"
        return "linux"

    return f"{system}-{machine}"


def get_version_info() -> dict[str, str | int]:
    info = {
        "version": "0.0.0",
        "version_type": "Alpha",
        "dev_code_name": "Unknown",
        "build_time": datetime.now().strftime("%Y-%m-%d"),
        "build_number": 1,
    }

    if not CONSTANTS_FILE.exists():
        return info

    content = CONSTANTS_FILE.read_text(encoding="utf-8")

    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', content, re.M)
    if m:
        info["version"] = m.group(1)

    m = re.search(r'^VERSION_TYPE\s*=\s*"([^"]+)"', content, re.M)
    if m:
        info["version_type"] = m.group(1)

    m = re.search(r'^DEV_CODE_NAME\s*=\s*"([^"]+)"', content, re.M)
    if m:
        info["dev_code_name"] = m.group(1)

    m = re.search(r'^BUILD_TIME\s*=\s*"([^"]+)"', content, re.M)
    if m:
        info["build_time"] = m.group(1)

    m = re.search(r"^BUILD_NUMBER\s*=\s*(\d+)", content, re.M)
    if m:
        info["build_number"] = int(m.group(1))

    return info


def update_build_info(version_info: dict[str, str | int]) -> None:
    if not CONSTANTS_FILE.exists():
        return

    content = CONSTANTS_FILE.read_text(encoding="utf-8")
    today = datetime.now().strftime("%Y-%m-%d")
    current_build_number = int(version_info["build_number"])

    # 跨天重置为 1，否则递增
    if version_info["build_time"] != today:
        new_build_number = 1
    else:
        new_build_number = current_build_number + 1

    # 更新 BUILD_TIME（保留原有对齐空格）
    content = re.sub(
        r'^(BUILD_TIME)(\s*=\s*)"[^"]*"', lambda m: m.group(1) + m.group(2) + f'"{today}"', content, flags=re.M
    )

    # 更新 BUILD_NUMBER（保留原有对齐空格）
    content = re.sub(
        r"^(BUILD_NUMBER)(\s*=\s*)\d+", lambda m: m.group(1) + m.group(2) + str(new_build_number), content, flags=re.M
    )

    CONSTANTS_FILE.write_text(content, encoding="utf-8")
    print_success(f"构建时间：{today}")
    print_success(f"构建编号：{new_build_number}")


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401

        print_success("PyInstaller 已安装")
    except ImportError:
        print("PyInstaller 未安装，正在安装…")
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])


def clean() -> None:
    for d in (BUILD_DIR, DIST_DIR):
        if d.exists():
            shutil.rmtree(d)
            print_success(f"已清理 {d.name}/")


def copy_runtime_assets(output_dir: Path) -> None:
    print_section("复制运行时资产")

    for dir_name in DISTRIBUTE_DIRS:
        src = PROJECT_ROOT / dir_name
        dst = output_dir / dir_name
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=IGNORE_PATTERNS)
            print_success(f"{dir_name}/  →  {dst.relative_to(PROJECT_ROOT)}")
        else:
            print_warning(f"{dir_name}/ 不存在，跳过")

    for file_name in DISTRIBUTE_FILES:
        src = PROJECT_ROOT / file_name
        dst = output_dir / file_name
        if src.exists():
            shutil.copy2(src, dst)
            print_success(f"{file_name}  →  {dst.relative_to(PROJECT_ROOT)}")

    (output_dir / "logs").mkdir(exist_ok=True)
    print_success("logs/（空目录）")

    # 复制默认的 i18n.json（国际化翻译文件）
    config_dir = output_dir / "config"
    config_dir.mkdir(exist_ok=True)
    i18n_src = PROJECT_ROOT / "config" / "i18n.json"
    if i18n_src.exists():
        shutil.copy2(i18n_src, config_dir / "i18n.json")
        print_success("config/i18n.json（国际化翻译文件）")
    else:
        print_warning("config/i18n.json 不存在，跳过")

    # 插件运行时依赖存放处
    lib_dir = output_dir / "plugins_ext" / "_lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / ".gitkeep").touch()
    print_success("plugins_ext/_lib/（插件依赖目录）")


def make_zip(output_dir: Path, version: str, platform_suffix: str) -> Path | None:
    zip_name = f"{APP_NAME}_v{version}_{platform_suffix}"
    zip_path = DIST_DIR / f"{zip_name}.zip"

    print_section("生成压缩包")

    counter = 1
    while zip_path.exists():
        zip_path = DIST_DIR / f"{zip_name}_{counter}.zip"
        counter += 1

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in sorted(output_dir.rglob("*")):
            if file.is_file() and file.suffix != ".ltcplugin":
                zf.write(file, file.relative_to(DIST_DIR))

    size_mb = zip_path.stat().st_size / 1024 / 1024
    print_success(f"{zip_path.name}  ({size_mb:.1f} MB)")
    return zip_path


def print_summary(
    output_dir: Path, zip_path: Path | None, version_info: dict[str, str | int], platform_suffix: str
) -> None:
    total_bytes = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file())
    total_mb = total_bytes / 1024 / 1024
    exe_path = output_dir / f"{APP_NAME}.exe"

    version = version_info["version"]
    version_type = version_info["version_type"]
    dev_code_name = version_info["dev_code_name"]
    build_time = version_info["build_time"]
    build_number = version_info["build_number"]

    print_banner("打包完成")

    print_item("版本号", f"v{version}")
    print_item("版本类型", str(version_type))
    print_item("开发代号", str(dev_code_name))
    print_item("构建时间", str(build_time))
    print_item("构建编号", str(build_number))
    print_item("目标平台", platform_suffix)
    print("")
    print_item("程序目录", str(output_dir))
    print_item("可执行文件", f"{exe_path.name}  ({'存在' if exe_path.exists() else '✗ 未找到'})")
    print_item("目录大小", f"{total_mb:.1f} MB")

    if zip_path:
        zip_mb = zip_path.stat().st_size / 1024 / 1024
        print_item("压缩包", f"{zip_path.name}  ({zip_mb:.1f} MB)")

    print("═" * 60)


# ── 主流程 ───────────────────────────────────────────────────────────── #


def main() -> None:
    parser = argparse.ArgumentParser(description="小树时钟打包脚本")
    parser.add_argument("--clean", action="store_true", help="打包前清理 build/ dist/")
    parser.add_argument("--skip-zip", action="store_true", help="不生成 ZIP 压缩包")
    parser.add_argument("--debug", action="store_true", help="保留控制台窗口（debug 模式）")
    parser.add_argument("--no-update-build", action="store_true", help="不更新构建时间和编号")
    args = parser.parse_args()

    version_info = get_version_info()
    platform_suffix = get_platform_suffix()

    print_banner(f"小树时钟 v{version_info['version']}  打包脚本")
    print_item("Python", sys.version.split()[0])
    print_item("项目根目录", str(PROJECT_ROOT))
    print_item("目标平台", platform_suffix)

    print_section("检查环境")
    ensure_pyinstaller()

    if not args.no_update_build:
        print_section("更新构建信息")
        update_build_info(version_info)
        version_info = get_version_info()

    if args.clean:
        print_section("清理旧产物")
        clean()

    if not SPEC_FILE.exists():
        print_error(f"找不到 spec 文件: {SPEC_FILE}")
        sys.exit(1)

    print_section("运行 PyInstaller")
    pyinstaller_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
    ]
    if args.debug:
        # debug 模式：通过环境变量通知 spec 开启控制台窗口
        os.environ["LITTLE_TREE_DEBUG"] = "1"
    pyinstaller_cmd.append(str(SPEC_FILE))
    run(pyinstaller_cmd)

    output_dir = DIST_DIR / APP_NAME
    if not output_dir.exists():
        print_error(f"打包输出目录不存在: {output_dir}")
        sys.exit(1)
    copy_runtime_assets(output_dir)

    zip_path = None
    if not args.skip_zip:
        zip_path = make_zip(output_dir, str(version_info["version"]), platform_suffix)

    print_summary(output_dir, zip_path, version_info, platform_suffix)


if __name__ == "__main__":
    main()
