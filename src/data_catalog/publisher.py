"""发布管理模块"""
from typing import List, Optional, Dict, Any
from .models import Resource, Catalog
from .checker import check_resource


def filter_resources(
    catalog: Catalog,
    status: Optional[str] = None,
    published: Optional[bool] = None,
    tags: Optional[List[str]] = None,
    authorization_scope: Optional[str] = None,
    update_frequency: Optional[str] = None,
    source: Optional[str] = None,
    has_all_tags: bool = False,
) -> List[Resource]:
    """按条件过滤资源"""
    results = []

    for r in catalog.resources:
        if status is not None and r.status != status:
            continue
        if published is not None and r.published != published:
            continue
        if authorization_scope is not None and r.authorization_scope != authorization_scope:
            continue
        if update_frequency is not None and r.update_frequency != update_frequency:
            continue
        if source is not None and r.source != source:
            continue
        if tags:
            if has_all_tags:
                if not all(t in r.tags for t in tags):
                    continue
            else:
                if not any(t in r.tags for t in tags):
                    continue
        results.append(r)

    return results


def mark_published(
    catalog: Catalog,
    resource_ids: Optional[List[str]] = None,
    resources: Optional[List[Resource]] = None,
) -> Catalog:
    """将资源标记为已发布"""
    target_ids = set()
    if resource_ids:
        target_ids.update(resource_ids)
    if resources:
        target_ids.update(r.id for r in resources)

    for r in catalog.resources:
        if r.id in target_ids:
            r.published = True
            r.status = "published"
            r.touch()

    catalog._touch()
    return catalog


def mark_unpublished(
    catalog: Catalog,
    resource_ids: Optional[List[str]] = None,
    resources: Optional[List[Resource]] = None,
    tags: Optional[List[str]] = None,
) -> Catalog:
    """将已发布资源撤回到草稿状态"""
    target_ids = set()
    if resource_ids:
        target_ids.update(resource_ids)
    if resources:
        target_ids.update(r.id for r in resources)

    if tags:
        for r in catalog.resources:
            if any(t in r.tags for t in tags):
                target_ids.add(r.id)

    for r in catalog.resources:
        if r.id in target_ids:
            r.published = False
            r.status = "draft"
            r.touch()

    catalog._touch()
    return catalog


def get_pending_publish(catalog: Catalog) -> List[Resource]:
    """获取待发布资源（草稿状态且字段完整）"""
    pending = []
    for r in catalog.resources:
        if r.published:
            continue
        result = check_resource(r)
        if not result.missing_fields:
            pending.append(r)
    return pending


def preview_publish(catalog: Catalog) -> List[Dict[str, Any]]:
    """发布预演：返回待发布资源清单及不通过原因

    Returns:
        列表，每项包含:
        - resource: Resource 对象
        - can_publish: 是否可发布
        - block_reasons: 不通过原因列表（空表示可发布）
    """
    preview = []
    for r in catalog.resources:
        if r.published:
            continue

        entry: Dict[str, Any] = {
            "resource": r,
            "can_publish": True,
            "block_reasons": [],
        }

        result = check_resource(r)
        if result.missing_fields:
            entry["can_publish"] = False
            entry["block_reasons"].append(
                f"缺失必填字段: {', '.join(result.missing_fields)}"
            )

        for issue in result.issues:
            if issue.level in ("critical", "error") and issue.category != "missing_field":
                entry["can_publish"] = False
                entry["block_reasons"].append(issue.message)

        if result.sensitive_hits:
            entry["block_reasons"].append(
                f"含敏感关键词: {', '.join(result.sensitive_hits)}（警告，不阻塞发布）"
            )

        preview.append(entry)

    return preview
