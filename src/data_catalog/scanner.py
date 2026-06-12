"""目录扫描模块"""
import os
from pathlib import Path
from typing import List, Optional, Set
from .models import Resource, Catalog


DEFAULT_EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".idea", ".vscode", "dist", "build", ".DS_Store",
}

DEFAULT_INCLUDE_EXT = {
    ".csv", ".xlsx", ".xls", ".json", ".xml", ".parquet",
    ".txt", ".tsv", ".db", ".sqlite", ".sql", ".yaml", ".yml",
    ".pdf", ".doc", ".docx", ".shp", ".geojson",
}


def scan_directory(
    root_path: str,
    include_ext: Optional[Set[str]] = None,
    exclude_dirs: Optional[Set[str]] = None,
    recursive: bool = True,
) -> Catalog:
    """扫描本地目录，生成资源清单"""
    include_ext = include_ext or DEFAULT_INCLUDE_EXT
    exclude_dirs = exclude_dirs or DEFAULT_EXCLUDE_DIRS
    catalog = Catalog()

    root = Path(root_path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"目录不存在: {root_path}")
    if not root.is_dir():
        raise NotADirectoryError(f"路径不是目录: {root_path}")

    iterator = root.rglob("*") if recursive else root.glob("*")

    for path in iterator:
        if not path.is_file():
            continue

        if any(part in exclude_dirs for part in path.parts):
            continue

        ext = path.suffix.lower()
        if ext and ext not in include_ext:
            continue

        try:
            file_size = path.stat().st_size
        except (OSError, PermissionError):
            continue

        rel_path = str(path.relative_to(root))
        resource = Resource.from_file_info(
            file_path=rel_path,
            file_name=path.name,
            file_size=file_size,
            file_type=ext.lstrip(".") or "unknown",
        )
        catalog.add_resource(resource)

    return catalog
