from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Literal

from ccflow.base import BaseModel
from pydantic import ConfigDict, Field, ValidationError, field_serializer, field_validator, model_validator

__all__ = (
    "ArtlinkError",
    "ManifestError",
    "Digest",
    "Capability",
    "ArtifactInferenceIssue",
    "Reference",
    "Artifact",
    "artifact_inference_issues",
    "capability_from_value",
    "has_capability",
)


class ArtlinkError(ValueError):
    """Base error for artlink model and workflow failures."""


class ManifestError(ArtlinkError):
    """Raised when manifest or artifact data is structurally invalid."""


class _ArtlinkModel(BaseModel):
    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("exclude_computed_fields", True)
        return super().model_dump(*args, **kwargs)


class _ManifestModel(_ArtlinkModel):
    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            raise ManifestError(str(exc)) from exc


class Digest(_ManifestModel):
    model_config = ConfigDict(frozen=True)

    algorithm: str
    value: str

    @field_validator("algorithm", "value")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("digest fields must not be empty")
        return value


class Capability(_ManifestModel):
    """A named capability that an artifact provides or requires."""

    model_config = ConfigDict(frozen=True)

    kind: str = ""
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _from_shorthand(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"name": data}
        return data

    @field_validator("kind", "name", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> Any:
        if value is None:
            return ""
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("capability name must not be empty")
        return value

    @property
    def key(self) -> str:
        if self.kind:
            return f"{self.kind}:{self.name}"
        return self.name


CapabilityValue = Capability | str | dict[str, Any]


class ArtifactInferenceIssue(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    field: Literal["format", "media_type"]
    declared_value: str
    inferred_value: str
    severity: Literal["warning"] = "warning"
    message: str


class Reference(_ManifestModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["artifact", "manifest", "template", "package", "registry"]
    target: str
    version: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target")
    @classmethod
    def _validate_target(cls, value: str) -> str:
        if not value:
            raise ValueError("reference target must not be empty")
        return value


class Artifact(_ManifestModel):
    """A packageable or consumable unit of content."""

    model_config = ConfigDict(frozen=True)

    id: str = ""
    name: str = ""
    path: Path | None = None
    uri: str = ""
    kind: str = ""
    role: str
    format: str = ""
    media_type: str = ""
    language: str = ""
    provides: tuple[CapabilityValue, ...] = Field(default_factory=tuple)
    requires: tuple[CapabilityValue, ...] = Field(default_factory=tuple)
    digest: Digest | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _infer_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        inferred = dict(data)
        location = inferred.get("path") or inferred.get("uri")
        if location and not inferred.get("format"):
            inferred_format = _infer_format(location)
            if inferred_format:
                inferred["format"] = inferred_format
        if location and not inferred.get("media_type"):
            media_type = _infer_media_type(location)
            if media_type:
                inferred["media_type"] = media_type
        return inferred

    @field_validator("path", mode="before")
    @classmethod
    def _normalize_empty_path(cls, value: Any) -> Any:
        if value == "":
            return None
        return value

    @field_validator("uri", "kind", "role", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> Any:
        if value is None:
            return ""
        return value

    @field_validator("role")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        if not value:
            raise ValueError("artifact role must not be empty")
        return value

    @field_validator("provides", "requires", mode="before")
    @classmethod
    def _normalize_capabilities(cls, value: Any) -> tuple[CapabilityValue, ...]:
        if value is None:
            return ()
        if isinstance(value, str | dict | Capability):
            return (capability_from_value(value),)
        return tuple(capability_from_value(item) for item in value)

    @field_serializer("provides", "requires")
    def _serialize_capabilities(self, value: tuple[CapabilityValue, ...]) -> list[str | dict[str, Any]]:
        return [_dump_capability(capability_from_value(capability)) for capability in value]

    @field_validator("provides", "requires")
    @classmethod
    def _validate_capabilities(cls, value: tuple[CapabilityValue, ...]) -> tuple[CapabilityValue, ...]:
        return tuple(value)

    @model_validator(mode="after")
    def _validate_location(self) -> "Artifact":
        if self.path is None and not self.uri:
            raise ValueError("artifact must declare a path or uri")
        return self

    @property
    def location(self) -> str:
        if self.path is not None:
            return self.path.as_posix()
        return self.uri

    @property
    def display_id(self) -> str:
        return self.id or self.name or self.location

    @property
    def inference_issues(self) -> tuple[ArtifactInferenceIssue, ...]:
        return artifact_inference_issues(self)


def _infer_format(location: Any) -> str:
    text = str(location).lower()
    suffix_mappings = (
        (".tar.gz", "tar.gz"),
        (".tar.bz2", "tar.bz2"),
        (".tar.xz", "tar.xz"),
        (".whl", "wheel"),
    )
    for suffix, artifact_format in suffix_mappings:
        if text.endswith(suffix):
            return artifact_format
    suffix = Path(text).suffix
    if not suffix:
        return ""
    return suffix.removeprefix(".")


def _infer_media_type(location: Any) -> str:
    media_type, _ = mimetypes.guess_type(str(location))
    return media_type or ""


def artifact_inference_issues(artifact: Artifact) -> tuple[ArtifactInferenceIssue, ...]:
    location = artifact.path or artifact.uri
    if not location:
        return ()

    issues: list[ArtifactInferenceIssue] = []
    inferred_format = _infer_format(location)
    if artifact.format and inferred_format and artifact.format != inferred_format:
        issues.append(
            ArtifactInferenceIssue(
                field="format",
                declared_value=artifact.format,
                inferred_value=inferred_format,
                message=f"artifact {artifact.display_id} declares format {artifact.format!r}, but {inferred_format!r} was inferred from its location",
            )
        )

    inferred_media_type = _infer_media_type(location)
    if artifact.media_type and inferred_media_type and artifact.media_type != inferred_media_type:
        issues.append(
            ArtifactInferenceIssue(
                field="media_type",
                declared_value=artifact.media_type,
                inferred_value=inferred_media_type,
                message=(
                    f"artifact {artifact.display_id} declares media_type {artifact.media_type!r}, "
                    f"but {inferred_media_type!r} was inferred from its location"
                ),
            )
        )

    return tuple(issues)


def capability_from_value(value: Any) -> Capability:
    if isinstance(value, Capability):
        return value
    if isinstance(value, str):
        return Capability(name=value)
    if isinstance(value, dict):
        return Capability(**value)
    return Capability.model_validate(value)


def has_capability(capabilities: tuple[CapabilityValue, ...], query: Any) -> bool:
    if query is None or query == "":
        return True
    query_capability = capability_from_value(query)
    return any(_capability_matches(capability_from_value(capability), query_capability) for capability in capabilities)


def _capability_matches(capability: Capability, query: Capability) -> bool:
    return capability.name == query.name and (not query.kind or capability.kind == query.kind)


def _dump_capability(capability: Capability) -> str | dict[str, Any]:
    if not capability.kind and not capability.metadata:
        return capability.name
    return capability.model_dump(mode="json", exclude_defaults=True)
