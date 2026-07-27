from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import ConfigDict, Field, ValidationError, field_serializer, field_validator, model_validator

from .artifact import Artifact, ArtlinkError, CapabilityValue, Reference, _ArtlinkModel, capability_from_value, has_capability
from .manifest import Manifest

__all__ = (
    "ARTLINK_TEMPLATE_SCHEMA",
    "ArtifactSelector",
    "Cardinality",
    "Template",
    "TemplateError",
    "TemplateRule",
    "ValidationIssue",
    "ValidationResult",
    "load_template",
    "template_from_mapping",
)


ARTLINK_TEMPLATE_SCHEMA = "artlink.template/v0"
Severity = Literal["error", "warning", "info", "prune"]


class TemplateError(ArtlinkError):
    """Raised when template data is structurally invalid."""


class _TemplateModel(_ArtlinkModel):
    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            raise TemplateError(str(exc)) from exc


class ArtifactSelector(_TemplateModel):
    model_config = ConfigDict(frozen=True)

    kind: str = ""
    role: str = ""
    language: str = ""
    format: str = ""
    media_type: str = ""
    path_glob: str = ""
    provides: CapabilityValue | None = None
    requires: CapabilityValue | None = None
    metadata_key: str = ""

    @field_validator("provides", "requires", mode="before")
    @classmethod
    def _normalize_capability_query(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        return capability_from_value(value)

    @field_serializer("provides", "requires")
    def _serialize_capability_query(self, value: CapabilityValue | None) -> str | dict[str, Any]:
        if value is None:
            return ""
        capability = capability_from_value(value)
        if not capability.kind and not capability.metadata:
            return capability.name
        return capability.model_dump(mode="json", exclude_defaults=True)

    def matches(self, artifact: Artifact) -> bool:
        checks = (
            not self.kind or artifact.kind == self.kind,
            not self.role or artifact.role == self.role,
            not self.language or artifact.language == self.language,
            not self.format or artifact.format == self.format,
            not self.media_type or artifact.media_type == self.media_type,
            not self.path_glob or (artifact.path is not None and fnmatch(artifact.path.as_posix(), self.path_glob)),
            not self.provides or has_capability(artifact.provides, self.provides),
            not self.requires or has_capability(artifact.requires, self.requires),
            not self.metadata_key or self.metadata_key in artifact.metadata,
        )
        return all(checks)


class Cardinality(_TemplateModel):
    model_config = ConfigDict(frozen=True)

    min: int = 0
    max: int | None = None

    @field_validator("min")
    @classmethod
    def _validate_min(cls, value: int) -> int:
        if value < 0:
            raise ValueError("cardinality min must be non-negative")
        return value

    @field_validator("max")
    @classmethod
    def _validate_max(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("cardinality max must be non-negative")
        return value

    @model_validator(mode="after")
    def _validate_range(self) -> Self:
        if self.max is not None and self.max < self.min:
            raise ValueError("cardinality max must be greater than or equal to min")
        return self

    def allows(self, count: int) -> bool:
        if count < self.min:
            return False
        return not (self.max is not None and count > self.max)

    def describe_failure(self, count: int) -> str:
        if count < self.min:
            return f"expected at least {self.min} {_artifact_word(self.min)}, found {count}"
        if self.max is not None and count > self.max:
            return f"expected at most {self.max} {_artifact_word(self.max)}, found {count}"
        return f"expected matching artifact count between {self.min} and {self.max}, found {count}"


class TemplateRule(_TemplateModel):
    model_config = ConfigDict(frozen=True)

    name: str
    selector: ArtifactSelector
    cardinality: Cardinality = Field(default_factory=Cardinality)
    severity: Severity = "error"
    message: str = ""

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("template rule name must not be empty")
        return value


class ValidationIssue(_TemplateModel):
    model_config = ConfigDict(frozen=True)

    rule: str
    severity: Severity
    message: str
    count: int
    artifacts: tuple[str, ...] = Field(default_factory=tuple)


class ValidationResult(_TemplateModel):
    model_config = ConfigDict(frozen=True)

    issues: tuple[ValidationIssue, ...] = Field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def raise_for_errors(self) -> None:
        errors = tuple(issue for issue in self.issues if issue.severity == "error")
        if errors:
            raise TemplateError("; ".join(issue.message for issue in errors))


class Template(_TemplateModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    schema_id: str = Field(default=ARTLINK_TEMPLATE_SCHEMA, alias="schema")
    name: str
    version: str = ""
    references: tuple[Reference, ...] = Field(default_factory=tuple)
    rules: tuple[TemplateRule, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)

    @field_validator("schema_id")
    @classmethod
    def _validate_schema(cls, value: str) -> str:
        if value != ARTLINK_TEMPLATE_SCHEMA:
            raise ValueError(f"unsupported template schema: {value}")
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("template name must not be empty")
        return value

    def validate_manifest(self, manifest: Manifest) -> ValidationResult:
        issues: list[ValidationIssue] = []
        for rule in self.rules:
            matching_artifacts = tuple(artifact for artifact in manifest.artifacts if rule.selector.matches(artifact))
            count = len(matching_artifacts)
            if rule.cardinality.allows(count):
                continue
            message = rule.message or f"{rule.name}: {rule.cardinality.describe_failure(count)}"
            issues.append(
                ValidationIssue(
                    rule=rule.name,
                    severity=rule.severity,
                    message=message,
                    count=count,
                    artifacts=tuple(artifact.display_id for artifact in matching_artifacts),
                )
            )
        return ValidationResult(issues=tuple(issues))

    def to_yaml_text(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False)

    @classmethod
    def load(cls, path: Path) -> Template:
        return load_template(path)


def load_template(path: Path) -> Template:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TemplateError("template must be a YAML mapping")
    return template_from_mapping(raw)


def template_from_mapping(raw: dict[str, Any]) -> Template:
    try:
        return Template(**raw)
    except ValidationError as exc:
        raise TemplateError(str(exc)) from exc


def _artifact_word(count: int) -> str:
    return "artifact" if count == 1 else "artifacts"
