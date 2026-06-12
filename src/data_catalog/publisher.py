"""发布管理模块"""
from typing import List, Optional
from .models import Resource, Catalog


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


def get_pending_publish(catalog: Catalog) -> List[Resource]:
    """获取待发布资源（草稿状态且字段完整）"""
    from .checker import check_resource
    pending = []
    for r in catalog.resources:
        if r.published:
            continue
        result = check_resource(r)
        if not result.missing_fields:
            pending.append(r)
    return pending
