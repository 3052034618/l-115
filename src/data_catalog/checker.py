"""数据校验模块"""
import json
import csv
import io
from typing import List
from datetime import datetime
from .models import Resource, Catalog, CheckResult, CheckIssue, SENSITIVE_KEYWORDS, UPDATE_FREQUENCIES, AUTHORIZATION_SCOPES


REQUIRED_FIELDS = [
    ("name", "资源名称"),
    ("source", "数据来源"),
    ("update_frequency", "更新频率"),
    ("authorization_scope", "授权范围"),
    ("contact_name", "联系人"),
    ("contact_email", "联系邮箱"),
]


def check_resource(resource: Resource) -> CheckResult:
    """检查单个资源的完整性和合规性"""
    display_name = resource.name or resource.file_name
    result = CheckResult(
        resource_id=resource.id,
        resource_name=display_name,
    )

    for field_name, field_label in REQUIRED_FIELDS:
        value = getattr(resource, field_name, None)
        if value is None or (isinstance(value, str) and not value.strip()):
            result.missing_fields.append(field_name)
            result.issues.append(CheckIssue(
                level="error",
                category="missing_field",
                message=f"缺失必填字段: {field_label} ({field_name})",
            ))

    texts_to_check = []
    if resource.description:
        texts_to_check.append(("描述", resource.description))
    if resource.name:
        texts_to_check.append(("名称", resource.name))
    if resource.custom_fields:
        for k, v in resource.custom_fields.items():
            if isinstance(v, str):
                texts_to_check.append((f"自定义字段.{k}", v))

    for source_label, text in texts_to_check:
        for keyword in SENSITIVE_KEYWORDS:
            if keyword in text:
                result.sensitive_hits.append(keyword)
                result.issues.append(CheckIssue(
                    level="warning",
                    category="sensitive_content",
                    message=f"[{source_label}] 包含敏感关键词: {keyword}",
                ))

    if resource.update_frequency and resource.update_frequency not in UPDATE_FREQUENCIES:
        msg = f"更新频率 '{resource.update_frequency}' 不在建议值列表中: {UPDATE_FREQUENCIES}"
        result.warnings.append(msg)
        result.issues.append(CheckIssue(
            level="info",
            category="invalid_enum",
            message=msg,
        ))

    if resource.authorization_scope and resource.authorization_scope not in AUTHORIZATION_SCOPES:
        msg = f"授权范围 '{resource.authorization_scope}' 不在建议值列表中: {AUTHORIZATION_SCOPES}"
        result.warnings.append(msg)
        result.issues.append(CheckIssue(
            level="info",
            category="invalid_enum",
            message=msg,
        ))

    if resource.contact_email and "@" not in resource.contact_email:
        msg = f"联系人邮箱格式可能不正确: {resource.contact_email}"
        result.warnings.append(msg)
        result.issues.append(CheckIssue(
            level="warning",
            category="format_error",
            message=msg,
        ))

    if not resource.contact_email and resource.contact_name:
        result.issues.append(CheckIssue(
            level="info",
            category="incomplete_contact",
            message="有联系人姓名但缺少邮箱",
        ))

    if resource.tags and len(resource.tags) > 20:
        msg = f"标签数量过多 ({len(resource.tags)})，建议不超过 20 个"
        result.warnings.append(msg)
        result.issues.append(CheckIssue(
            level="info",
            category="tag_limit",
            message=msg,
        ))

    if not resource.description:
        result.issues.append(CheckIssue(
            level="info",
            category="missing_field",
            message="建议补充资源描述",
        ))

    return result


def check_catalog(catalog: Catalog) -> List[CheckResult]:
    """检查整个目录中的所有资源"""
    return [check_resource(r) for r in catalog.resources]


def has_errors(results: List[CheckResult]) -> bool:
    """判断检查结果中是否存在错误"""
    return any(r.has_errors for r in results)


def export_check_report_json(results: List[CheckResult], catalog: Catalog) -> str:
    """导出审核报告为 JSON"""
    report = {
        "generated_at": datetime.now().isoformat(),
        "total_resources": len(results),
        "summary": _compute_summary(results),
        "results": [r.to_dict() for r in results],
    }
    return json.dumps(report, ensure_ascii=False, indent=2)


def export_check_report_csv(results: List[CheckResult]) -> str:
    """导出审核报告为 CSV"""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "resource_id", "resource_name", "severity",
        "level", "category", "message",
    ])
    writer.writeheader()
    for r in results:
        if not r.issues:
            writer.writerow({
                "resource_id": r.resource_id,
                "resource_name": r.resource_name,
                "severity": "ok",
                "level": "ok",
                "category": "-",
                "message": "通过审核",
            })
        else:
            for issue in r.issues:
                writer.writerow({
                    "resource_id": r.resource_id,
                    "resource_name": r.resource_name,
                    "severity": r.severity,
                    "level": issue.level,
                    "category": issue.category,
                    "message": issue.message,
                })
    return output.getvalue()


def _compute_summary(results: List[CheckResult]) -> Dict:
    total = len(results)
    by_severity = {"critical": 0, "error": 0, "warning": 0, "info": 0, "ok": 0}
    by_category: Dict[str, int] = {}
    for r in results:
        by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
        for issue in r.issues:
            by_category[issue.category] = by_category.get(issue.category, 0) + 1
    return {
        "total": total,
        "by_severity": by_severity,
        "by_category": by_category,
    }
