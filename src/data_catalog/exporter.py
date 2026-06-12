"""导出模块 - 生成平台导入文件和变更对比"""
import json
import csv
import io
from typing import List, Optional, Dict, Any
from pathlib import Path

from .models import Resource, Catalog


EXPORT_PLATFORM_SCHEMA = [
    "resource_id",
    "name",
    "file_path",
    "file_type",
    "file_size",
    "source",
    "update_frequency",
    "authorization_scope",
    "contact_name",
    "contact_email",
    "description",
    "tags",
    "status",
    "published",
    "created_at",
    "updated_at",
]


def to_platform_json(catalog: Catalog, resources: Optional[List[Resource]] = None) -> str:
    """生成平台导入 JSON 文件"""
    target_resources = resources or catalog.resources
    items = []
    for r in target_resources:
        item = {
            "resource_id": r.id,
            "name": r.name or r.file_name,
            "file_path": r.file_path,
            "file_type": r.file_type,
            "file_size": r.file_size,
            "source": r.source or "",
            "update_frequency": r.update_frequency or "",
            "authorization_scope": r.authorization_scope or "",
            "contact_name": r.contact_name or "",
            "contact_email": r.contact_email or "",
            "description": r.description or "",
            "tags": r.tags,
            "status": r.status,
            "published": r.published,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        if r.custom_fields:
            item["custom_fields"] = r.custom_fields
        items.append(item)

    payload = {
        "version": catalog.version,
        "exported_at": catalog.updated_at,
        "total": len(items),
        "resources": items,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def to_platform_csv(catalog: Catalog, resources: Optional[List[Resource]] = None) -> str:
    """生成平台导入 CSV 文件"""
    target_resources = resources or catalog.resources
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_PLATFORM_SCHEMA, extrasaction="ignore")
    writer.writeheader()
    for r in target_resources:
        writer.writerow({
            "resource_id": r.id,
            "name": r.name or r.file_name,
            "file_path": r.file_path,
            "file_type": r.file_type,
            "file_size": r.file_size,
            "source": r.source or "",
            "update_frequency": r.update_frequency or "",
            "authorization_scope": r.authorization_scope or "",
            "contact_name": r.contact_name or "",
            "contact_email": r.contact_email or "",
            "description": r.description or "",
            "tags": ",".join(r.tags),
            "status": r.status,
            "published": "true" if r.published else "false",
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        })
    return output.getvalue()


def generate_diff_report(current: Catalog, previous: Catalog) -> str:
    """生成变更对比报告（可读文本格式）"""
    diff = current.diff(previous)
    lines = []

    lines.append("=" * 60)
    lines.append("数据资源目录变更对比报告")
    lines.append("=" * 60)
    lines.append(f"原目录版本: {previous.version} (更新于 {previous.updated_at})")
    lines.append(f"新目录版本: {current.version} (更新于 {current.updated_at})")
    lines.append("")

    added = diff["added"]
    removed = diff["removed"]
    changed = diff["changed"]

    lines.append(f"总计新增: {len(added)} 个资源")
    lines.append(f"总计删除: {len(removed)} 个资源")
    lines.append(f"总计修改: {len(changed)} 个资源")
    lines.append("")

    if added:
        lines.append("-" * 40)
        lines.append("【新增资源】")
        lines.append("-" * 40)
        for r in added:
            lines.append(f"  + {r.file_name} ({r.id[:8]}...)")
            if r.name:
                lines.append(f"      名称: {r.name}")
        lines.append("")

    if removed:
        lines.append("-" * 40)
        lines.append("【删除资源】")
        lines.append("-" * 40)
        for r in removed:
            lines.append(f"  - {r.file_name} ({r.id[:8]}...)")
        lines.append("")

    if changed:
        lines.append("-" * 40)
        lines.append("【修改资源】")
        lines.append("-" * 40)
        for change in changed:
            r = change["resource"]
            prev = change["previous"]
            lines.append(f"  ~ {r.file_name} ({r.id[:8]}...)")
            changed_fields = _diff_fields(r, prev)
            for field, old, new in changed_fields:
                lines.append(f"      {field}: {old} → {new}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def _diff_fields(current: Resource, previous: Resource) -> List[tuple]:
    """对比两个资源的差异字段"""
    current_dict = current.to_dict()
    previous_dict = previous.to_dict()
    diffs = []
    for key in current_dict.keys():
        if key in ("updated_at",):
            continue
        old_val = previous_dict.get(key)
        new_val = current_dict.get(key)
        if old_val != new_val:
            diffs.append((key, repr(old_val), repr(new_val)))
    return diffs


def save_export(content: str, output_path: str) -> None:
    """保存导出内容到文件"""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
