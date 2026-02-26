"""文件系统工具函数"""
from pathlib import Path


def ensure_dirs(*dirs: str) -> None:
    """确保多个目录存在，若不存在则创建"""
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
