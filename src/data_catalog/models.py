"""数据模型定义"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any
import uuid
import json
import copy


UPDATE_FREQUENCIES = ["实时", "每日", "每周", "每月", "每季度", "每年", "不定期"]
AUTHORIZATION_SCOPES = ["公开", "内部", "授权可见", "特定机构", "脱敏可用"]
SENSITIVE_KEYWORDS = [
    "身份证", "手机号", "姓名", "住址", "银行卡", "密码",
    "身份证号", "电话号码", "家庭地址", "邮箱", "个人信息",
    "医疗记录", "病历", "生物识别", "指纹", "人脸",
]


@dataclass
class Resource:
    """数据资源元信息"""
    id: str
    file_path: str
    file_name: str
    file_size: int
    file_type: str
    created_at: str
    updated_at: str

    name: Optional[str] = None
    source: Optional[str] = None
    update_frequency: Optional[str] = None
    authorization_scope: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    description: Optional[str] = None

    tags: List[str] = field(default_factory=list)
    status: str = "draft"
    published: bool = False
    custom_fields: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_file_info(cls, file_path: str, file_name: str, file_size: int, file_type: str) -> "Resource":
        now = datetime.now().isoformat()
        return cls(
            id=str(uuid.uuid4()),
            file_path=file_path,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Resource":
        return cls(**data)

    def summary(self) -> str:
        lines = [
            f"资源 ID: {self.id}",
            f"文件路径: {self.file_path}",
            f"文件名称: {self.file_name}",
            f"文件类型: {self.file_type}",
            f"文件大小: {self._format_size(self.file_size)}",
            f"状态: {self.status}",
            f"是否发布: {'是' if self.published else '否'}",
        ]
        if self.name:
            lines.append(f"资源名称: {self.name}")
        if self.source:
            lines.append(f"数据来源: {self.source}")
        if self.update_frequency:
            lines.append(f"更新频率: {self.update_frequency}")
        if self.authorization_scope:
            lines.append(f"授权范围: {self.authorization_scope}")
        if self.contact_name:
            contact = self.contact_name
            if self.contact_email:
                contact += f" <{self.contact_email}>"
            lines.append(f"联系人: {contact}")
        if self.description:
            lines.append(f"描述: {self.description}")
        if self.tags:
            lines.append(f"标签: {', '.join(self.tags)}")
        if self.custom_fields:
            lines.append("自定义字段:")
            for k, v in self.custom_fields.items():
                lines.append(f"  {k}: {v}")
        lines.append(f"创建时间: {self.created_at}")
        lines.append(f"更新时间: {self.updated_at}")
        return "\n".join(lines)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat()


@dataclass
class Catalog:
    """数据资源目录"""
    resources: List[Resource] = field(default_factory=list)
    version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_resource(self, resource: Resource) -> None:
        self.resources.append(resource)
        self._touch()

    def get_resource(self, resource_id: str) -> Optional[Resource]:
        for r in self.resources:
            if r.id == resource_id:
                return r
        return None

    def filter(self, **kwargs) -> List[Resource]:
        results = []
        for r in self.resources:
            match = True
            for key, value in kwargs.items():
                if value is None:
                    continue
                attr = getattr(r, key, None)
                if isinstance(attr, list):
                    if value not in attr:
                        match = False
                        break
                elif attr != value:
                    match = False
                    break
            if match:
                results.append(r)
        return results

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resources": [r.to_dict() for r in self.resources],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Catalog":
        resources = [Resource.from_dict(r) for r in data.get("resources", [])]
        return cls(
            resources=resources,
            version=data.get("version", "1.0"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, content: str) -> "Catalog":
        return cls.from_dict(json.loads(content))

    def _touch(self) -> None:
        self.updated_at = datetime.now().isoformat()

    def diff(self, other: "Catalog") -> Dict[str, Any]:
        """与另一个目录对比，返回变更情况"""
        self_ids = {r.id for r in self.resources}
        other_ids = {r.id for r in other.resources}

        added = [r for r in self.resources if r.id not in other_ids]
        removed = [r for r in other.resources if r.id not in self_ids]

        changed = []
        for r in self.resources:
            if r.id in other_ids:
                other_r = other.get_resource(r.id)
                if other_r and r.to_dict() != other_r.to_dict():
                    changed.append({
                        "resource": r,
                        "previous": other_r,
                    })

        return {
            "added": added,
            "removed": removed,
            "changed": changed,
        }


@dataclass
class CheckResult:
    """检查结果"""
    resource_id: str
    resource_name: str
    missing_fields: List[str] = field(default_factory=list)
    sensitive_hits: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.missing_fields) > 0 or len(self.sensitive_hits) > 0

    @property
    def severity(self) -> str:
        if self.missing_fields:
            return "error"
        if self.sensitive_hits:
            return "warning"
        if self.warnings:
            return "info"
        return "ok"
