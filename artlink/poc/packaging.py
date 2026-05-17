from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

__all__ = (
    "ARTIFACT_MANIFEST_SCHEMA",
    "SUPPORTED_ARTIFACT_KINDS",
    "ArtifactManifestError",
    "Artifact",
    "ArtifactManifest",
    "load_artifact_manifest",
    "artifact_manifest_from_mapping",
    "validate_artifact_files",
    "artifact_path",
)

ARTIFACT_MANIFEST_SCHEMA = "artlink.artifact-manifest/v0"
SUPPORTED_ARTIFACT_KINDS = frozenset(("source", "metadata", "binary"))


class ArtifactManifestError(ValueError):
    pass


class _ArtifactModel(BaseModel):
    def __init__(self, **data: Any) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            raise ArtifactManifestError(str(exc)) from exc


class Artifact(_ArtifactModel):
    model_config = ConfigDict(frozen=True)

    path: Path
    kind: str
    role: str
    language: str = ""
    format: str = ""
    modules: tuple[str, ...] = Field(default_factory=tuple)
    media_type: str = ""
    sha256: str = ""

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: Path) -> Path:
        if not value.as_posix():
            raise ArtifactManifestError("artifact path must not be empty")
        return value

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value: str) -> str:
        if value not in SUPPORTED_ARTIFACT_KINDS:
            raise ArtifactManifestError(f"unsupported artifact kind: {value}")
        return value

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str) -> str:
        if not value:
            raise ArtifactManifestError("artifact role must not be empty")
        return value

    @field_validator("modules")
    @classmethod
    def _validate_modules(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not all(isinstance(module, str) and module for module in value):
            raise ArtifactManifestError("artifact modules must be non-empty strings")
        return tuple(value)


class ArtifactManifest(_ArtifactModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    schema_id: str = Field(default=ARTIFACT_MANIFEST_SCHEMA, alias="schema")
    name: str
    artifacts: tuple[Artifact, ...] = Field(default_factory=tuple)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)

    @field_validator("schema_id")
    @classmethod
    def _validate_schema(cls, value: str) -> str:
        if value != ARTIFACT_MANIFEST_SCHEMA:
            raise ArtifactManifestError(f"unsupported artifact manifest schema: {value}")
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not value:
            raise ArtifactManifestError("artifact manifest name must not be empty")
        return value

    @model_validator(mode="after")
    def _validate_unique_paths(self) -> "ArtifactManifest":
        duplicate_paths = _duplicate_paths(self.artifacts)
        if duplicate_paths:
            raise ArtifactManifestError(f"duplicate artifact path(s): {', '.join(duplicate_paths)}")
        return self

    def to_yaml_text(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False)


def load_artifact_manifest(path: Path, *, validate_paths: bool = False, root: Path | None = None) -> ArtifactManifest:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ArtifactManifestError("artifact manifest must be a YAML mapping")
    manifest = artifact_manifest_from_mapping(raw)
    if validate_paths:
        validate_artifact_files(manifest, root=path.parent if root is None else root)
    return manifest


def artifact_manifest_from_mapping(raw: dict[str, Any]) -> ArtifactManifest:
    raw_artifacts = raw.get("artifacts", [])
    if not isinstance(raw_artifacts, list):
        raise ArtifactManifestError("artifact manifest artifacts must be a list")
    try:
        return ArtifactManifest(schema=_required_mapping_str(raw, "schema"), name=_required_mapping_str(raw, "name"), artifacts=tuple(raw_artifacts))
    except ValidationError as exc:
        raise ArtifactManifestError(str(exc)) from exc


def validate_artifact_files(manifest: ArtifactManifest, *, root: Path) -> None:
    missing_paths = tuple(artifact_path(root, artifact) for artifact in manifest.artifacts if not artifact_path(root, artifact).is_file())
    if missing_paths:
        missing_text = ", ".join(path.as_posix() for path in missing_paths)
        raise ArtifactManifestError(f"missing artifact file(s): {missing_text}")


def artifact_path(root: Path, artifact: Artifact) -> Path:
    if artifact.path.is_absolute():
        return artifact.path
    return root / artifact.path


def _required_mapping_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ArtifactManifestError(f"artifact manifest missing required string field: {key}")
    return value


def _duplicate_paths(artifacts: tuple[Artifact, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for artifact in artifacts:
        artifact_path_text = artifact.path.as_posix()
        if artifact_path_text in seen:
            duplicates.append(artifact_path_text)
        seen.add(artifact_path_text)
    return tuple(duplicates)
