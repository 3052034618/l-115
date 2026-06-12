"""批量元信息导入模块"""
import csv
import io
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from .models import Catalog, Resource


IMPORT_FIELD_MAP = {
    "resource_id": "resource_id",
    "id": "resource_id",
    "file_path": "file_path",
    "path": "file_path",
    "filepath": "file_path",
    "name": "name",
    "resource_name": "name",
    "source": "source",
    "data_source": "source",
    "update_frequency": "update_frequency",
    "frequency": "update_frequency",
    "authorization_scope": "authorization_scope",
    "scope": "authorization_scope",
    "auth_scope": "authorization_scope",
    "contact_name": "contact_name",
    "contact": "contact_name",
    "contact_email": "contact_email",
    "email": "contact_email",
    "description": "description",
    "desc": "description",
}


UPDATABLE_FIELDS = {
    "name", "source", "update_frequency", "authorization_scope",
    "contact_name", "contact_email", "description",
}


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "_")


def _read_csv_rows(file_path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    rows = []
    warnings = []
    path = Path(file_path)
    content = path.read_text(encoding="utf-8-sig")

    reader = csv.DictReader(io.StringIO(content))
    raw_headers = reader.fieldnames or []
    headers = [_normalize_header(h) for h in raw_headers]

    unknown = [h for h in headers if h not in IMPORT_FIELD_MAP]
    if unknown:
        warnings.append(f"忽略无法识别的列: {', '.join(unknown)}")

    for row in reader:
        mapped = {}
        for raw_key, value in row.items():
            norm_key = _normalize_header(raw_key)
            target = IMPORT_FIELD_MAP.get(norm_key)
            if target and value and value.strip():
                mapped[target] = value.strip()
        rows.append(mapped)

    return rows, warnings


def _read_xlsx_rows(file_path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    try:
        import openpyxl
    except ImportError:
        raise ImportError(
            "读取 Excel 文件需要 openpyxl 库，请运行: pip install openpyxl"
        )

    rows = []
    warnings = []
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    ws = wb.active

    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        return rows, ["Excel 文件为空"]

    raw_headers = [str(h) if h else "" for h in all_rows[0]]
    headers = [_normalize_header(h) for h in raw_headers]

    unknown = [h for h in headers if h not in IMPORT_FIELD_MAP]
    if unknown:
        warnings.append(f"忽略无法识别的列: {', '.join(unknown)}")

    for row_data in all_rows[1:]:
        mapped = {}
        for i, value in enumerate(row_data):
            if i < len(headers) and value is not None:
                target = IMPORT_FIELD_MAP.get(headers[i])
                val = str(value).strip()
                if target and val:
                    mapped[target] = val
        rows.append(mapped)

    wb.close()
    return rows, warnings


def read_import_file(file_path: str) -> Tuple[List[Dict[str, str]], List[str]]:
    """读取导入文件，返回 (行数据列表, 警告列表)"""
    ext = Path(file_path).suffix.lower()
    if ext == ".csv":
        return _read_csv_rows(file_path)
    elif ext in (".xlsx", ".xls"):
        return _read_xlsx_rows(file_path)
    else:
        raise ValueError(f"不支持的导入文件格式: {ext}，仅支持 .csv / .xlsx / .xls")


def apply_import(
    catalog: Catalog,
    rows: List[Dict[str, str]],
    match_by: str = "file_path",
) -> Dict[str, Any]:
    """将导入数据应用到目录，返回统计信息

    Args:
        catalog: 数据目录
        rows: 从导入文件读取的行数据
        match_by: 匹配方式，"file_path" 或 "id"
    """
    matched = 0
    unmatched = 0
    updated_fields: Dict[str, int] = {}
    unmatched_rows: List[Dict[str, str]] = []

    if match_by == "id":
        index = {r.id: r for r in catalog.resources}
    else:
        index = {}
        for r in catalog.resources:
            norm = r.file_path.replace("\\", "/")
            index[norm] = r
            index[r.file_path] = r
            index[r.file_name] = r

    for row in rows:
        if match_by == "id":
            key = row.get("resource_id", "")
        else:
            key = row.get("file_path", "")

        resource = index.get(key)

        if resource is None:
            unmatched += 1
            unmatched_rows.append(row)
            continue

        matched += 1
        for field_name, value in row.items():
            if field_name in ("resource_id", "file_path"):
                continue
            if field_name in UPDATABLE_FIELDS:
                setattr(resource, field_name, value)
                updated_fields[field_name] = updated_fields.get(field_name, 0) + 1

        resource.touch()

    if matched > 0:
        catalog._touch()

    return {
        "matched": matched,
        "unmatched": unmatched,
        "updated_fields": updated_fields,
        "unmatched_rows": unmatched_rows,
    }
