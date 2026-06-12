"""数据校验模块"""
from typing import List
from .models import Resource, Catalog, CheckResult, SENSITIVE_KEYWORDS, UPDATE_FREQUENCIES, AUTHORIZATION_SCOPES


REQUIRED_FIELDS = [
    "name",
    "source",
    "update_frequency",
    "authorization_scope",
    "contact_name",
    "contact_email",
]


def check_resource(resource: Resource) -> CheckResult:
    """检查单个资源的完整性和合规性"""
    display_name = resource.name or resource.file_name
    result = CheckResult(
        resource_id=resource.id,
        resource_name=display_name,
    )

    for field in REQUIRED_FIELDS:
        value = getattr(resource, field, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            result.missing_fields.append(field)

    texts_to_check = []
    if resource.description:
        texts_to_check.append(resource.description)
    if resource.name:
        texts_to_check.append(resource.name)
    if resource.custom_fields:
        for v in resource.custom_fields.values():
            if isinstance(v, str):
                texts_to_check.append(v)

    combined_text = "\n".join(texts_to_check)
    for keyword in SENSITIVE_KEYWORDS:
        if keyword in combined_text:
            result.sensitive_hits.append(keyword)

    if resource.update_frequency and resource.update_frequency not in UPDATE_FREQUENCIES:
        result.warnings.append(f"更新频率 '{resource.update_frequency}' 不在建议值列表中: {UPDATE_FREQUENCIES}")

    if resource.authorization_scope and resource.authorization_scope not in AUTHORIZATION_SCOPES:
        result.warnings.append(f"授权范围 '{resource.authorization_scope}' 不在建议值列表中: {AUTHORIZATION_SCOPES}")

    if resource.contact_email and "@" not in resource.contact_email:
        result.warnings.append(f"联系人邮箱格式可能不正确: {resource.contact_email}")

    if resource.tags and len(resource.tags) > 20:
        result.warnings.append(f"标签数量过多 ({len(resource.tags)})，建议不超过 20 个")

    return result


def check_catalog(catalog: Catalog) -> List[CheckResult]:
    """检查整个目录中的所有资源"""
    return [check_resource(r) for r in catalog.resources]


def has_errors(results: List[CheckResult]) -> bool:
    """判断检查结果中是否存在错误"""
    return any(r.has_errors for r in results)
