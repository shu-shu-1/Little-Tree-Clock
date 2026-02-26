"""
小树时钟 — 打包脚本
---------------------
用法：
    python build.py              # 正常打包
    python build.py --clean      # 清理 build/ dist/ 后再打包
    python build.py --skip-zip   # 不生成 ZIP 压缩包
    python build.py --debug      # 保留控制台窗口，方便排查启动问题

输出目录：
    dist/小树时钟/               ← 可直接运行的程序目录
    dist/小树时钟_v{ver}.zip     ← 压缩包（默认生成，可用 --skip-zip 跳过）
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# ── 常量 ─────────────────────────────────────────────────────────────── #
PROJECT_ROOT = Path(__file__).resolve().parent
SPEC_FILE    = PROJECT_ROOT / "little_tree.spec"
DIST_DIR     = PROJECT_ROOT / "dist"
BUILD_DIR    = PROJECT_ROOT / "build"
APP_NAME     = "小树时钟"

# 随应用分发的目录/文件（从项目根复制到 dist/小树时钟/）
DISTRIBUTE_DIRS  = ["plugins_ext", "config"]
DISTRIBUTE_FILES = ["icon.png"]

# 复制时忽略的模式
IGNORE_PATTERNS = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", "._data", ".git*"
)


# ── 辅助函数 ─────────────────────────────────────────────────────────── #

def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """运行命令，失败时打印错误并退出。"""
    print(f"\n▶ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"✗ 命令失败，退出码 {result.returncode}")
        sys.exit(result.returncode)
    return result


def get_version() -> str:
    """从 pyproject.toml 读取版本号。"""
    toml_file = PROJECT_ROOT / "pyproject.toml"
    if not toml_file.exists():
        return "0.0.0"
    m = re.search(r'^version\s*=\s*"([^"]+)"', toml_file.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0.0.0"


def ensure_pyinstaller() -> None:
    """确保 PyInstaller 已安装。"""
    try:
        import PyInstaller  # noqa: F401
        print(f"✓ PyInstaller 已安装")
    except ImportError:
        print("PyInstaller 未安装，正在安装…")
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])


def clean() -> None:
    """删除 build/ 和 dist/ 目录。"""
    for d in (BUILD_DIR, DIST_DIR):
        if d.exists():
            shutil.rmtree(d)
            print(f"✓ 已清理 {d.name}/")


def copy_runtime_assets(output_dir: Path) -> None:
    """将 plugins_ext/ config/ 等运行时目录复制到打包输出目录中。"""
    print("\n── 复制运行时资产 ──────────────────────────────────────────────")

    for dir_name in DISTRIBUTE_DIRS:
        src = PROJECT_ROOT / dir_name
        dst = output_dir / dir_name
        if src.exists():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=IGNORE_PATTERNS)
            print(f"  ✓ {dir_name}/  →  {dst.relative_to(PROJECT_ROOT)}")
        else:
            print(f"  ! {dir_name}/ 不存在，跳过")

    for file_name in DISTRIBUTE_FILES:
        src = PROJECT_ROOT / file_name
        dst = output_dir / file_name
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  ✓ {file_name}  →  {dst.relative_to(PROJECT_ROOT)}")

    # 确保 logs/ 目录存在
    (output_dir / "logs").mkdir(exist_ok=True)
    print(f"  ✓ logs/（空目录）")

    # 确保 plugins_ext/_lib 存在（插件运行时依赖存放处）
    lib_dir = output_dir / "plugins_ext" / "_lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / ".gitkeep").touch()
    print(f"  ✓ plugins_ext/_lib/（插件依赖目录）")


def make_zip(output_dir: Path, version: str) -> Path:
    """将 output_dir 打包成 ZIP 文件。"""
    zip_path = DIST_DIR / f"{APP_NAME}_v{version}.zip"
    print(f"\n── 生成压缩包 ──────────────────────────────────────────────────")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in sorted(output_dir.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(DIST_DIR))
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"  ✓ {zip_path.name}  ({size_mb:.1f} MB)")
    return zip_path


def print_summary(output_dir: Path, zip_path: Path | None, version: str) -> None:
    """打印打包结果摘要。"""
    total_mb = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file())
    total_mb /= 1024 * 1024
    exe_path = output_dir / f"{APP_NAME}.exe"

    print("\n" + "═" * 60)
    print(f"  打包完成  v{version}")
    print("═" * 60)
    print(f"  程序目录：{output_dir}")
    print(f"  可执行文件：{exe_path.name}  ({'存在' if exe_path.exists() else '✗ 未找到'})")
    print(f"  目录大小：{total_mb:.1f} MB")
    if zip_path:
        zip_mb = zip_path.stat().st_size / 1024 / 1024
        print(f"  压缩包：{zip_path.name}  ({zip_mb:.1f} MB)")
    print("═" * 60)


# ── 主流程 ───────────────────────────────────────────────────────────── #

def main() -> None:
    parser = argparse.ArgumentParser(description="小树时钟打包脚本")
    parser.add_argument("--clean",    action="store_true", help="打包前清理 build/ dist/")
    parser.add_argument("--skip-zip", action="store_true", help="不生成 ZIP 压缩包")
    parser.add_argument("--debug",    action="store_true", help="保留控制台窗口（debug 模式）")
    args = parser.parse_args()

    version = get_version()
    print(f"小树时钟 v{version}  打包脚本")
    print(f"Python: {sys.version}")
    print(f"项目根目录: {PROJECT_ROOT}")

    # 1. 检查 PyInstaller
    ensure_pyinstaller()

    # 2. 清理（可选）
    if args.clean:
        print("\n── 清理旧产物 ──────────────────────────────────────────────────")
        clean()

    # 3. 确保 spec 文件存在
    if not SPEC_FILE.exists():
        print(f"✗ 找不到 spec 文件: {SPEC_FILE}")
        sys.exit(1)

    # 4. 运行 PyInstaller
    print("\n── 运行 PyInstaller ────────────────────────────────────────────")
    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
    ]
    if args.debug:
        # debug 模式：通过环境变量通知 spec 开启控制台窗口
        os.environ["LITTLE_TREE_DEBUG"] = "1"
    pyinstaller_cmd.append(str(SPEC_FILE))
    run(pyinstaller_cmd)

    # 5. 复制运行时资产
    output_dir = DIST_DIR / APP_NAME
    if not output_dir.exists():
        print(f"✗ 打包输出目录不存在: {output_dir}")
        sys.exit(1)
    copy_runtime_assets(output_dir)

    # 6. 生成 ZIP（可选）
    zip_path = None
    if not args.skip_zip:
        zip_path = make_zip(output_dir, version)

    # 7. 摘要
    print_summary(output_dir, zip_path, version)


if __name__ == "__main__":
    main()
