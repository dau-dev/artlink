from __future__ import annotations

from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator

from .artifact import Artifact, ManifestError, Reference, _ManifestModel

__all__ = (
    "ARTLINK_MANIFEST_SCHEMA",
    "Manifest",
    "artifact_path",
    "manifest_from_mapping",
    "load_manifest",
    "validate_artifact_files",
)


ARTLINK_MANIFEST_SCHEMA = "artlink.manifest/v0"


class Manifest(_ManifestModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    schema_id: str = Field(default=ARTLINK_MANIFEST_SCHEMA, alias="schema")
    name: str
    version: str = ""
    intent: str = ""
    artifacts: tuple[Artifact, ...] = Field(default_factory=tuple)
    references: tuple[Reference, ...] = Field(default_factory=tuple)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)

    @field_validator("schema_id")
    @classmethod
    def _validate_schema(cls, value: str) -> str:
        if value != ARTLINK_MANIFEST_SCHEMA:
            raise ValueError(f"unsupported manifest schema: {value}")
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("manifest name must not be empty")
        return value

    @model_validator(mode="after")
    def _validate_unique_artifacts(self) -> Self:
        duplicate_ids = _duplicates(artifact.id for artifact in self.artifacts if artifact.id)
        if duplicate_ids:
            raise ValueError(f"duplicate artifact id(s): {', '.join(duplicate_ids)}")
        duplicate_locations = _duplicates(_location_key(artifact) for artifact in self.artifacts)
        if duplicate_locations:
            raise ValueError(f"duplicate artifact location(s): {', '.join(duplicate_locations)}")
        return self

    @classmethod
    def compose(cls, *, name: str, manifests: tuple["Manifest", ...], intent: str = "", metadata: dict[str, Any] | None = None) -> "Manifest":
        composed_metadata = dict(metadata or {})
        composed_metadata.setdefault("composed_from", [manifest.name for manifest in manifests])
        artifacts = tuple(artifact for manifest in manifests for artifact in manifest.artifacts)
        references = tuple(reference for manifest in manifests for reference in manifest.references)
        return cls(name=name, intent=intent, artifacts=artifacts, references=references, metadata=composed_metadata)

    def to_yaml_text(self) -> str:
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False)


def load_manifest(path: Path, *, validate_paths: bool = False, root: Path | None = None) -> Manifest:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ManifestError("manifest must be a YAML mapping")
    manifest = manifest_from_mapping(raw)
    if validate_paths:
        validate_artifact_files(manifest, root=path.parent if root is None else root)
    return manifest


def manifest_from_mapping(raw: dict[str, Any]) -> Manifest:
    try:
        return Manifest(**raw)
    except ValidationError as exc:
        raise ManifestError(str(exc)) from exc


def validate_artifact_files(manifest: Manifest, *, root: Path) -> None:
    missing_paths = tuple(
        path for artifact in manifest.artifacts if artifact.path is not None and not (path := artifact_path(root, artifact)).exists()
    )
    if missing_paths:
        missing_text = ", ".join(path.as_posix() for path in missing_paths)
        raise ManifestError(f"missing artifact path(s): {missing_text}")


def artifact_path(root: Path, artifact: Artifact) -> Path:
    if artifact.path is None:
        raise ManifestError(f"artifact has no filesystem path: {artifact.display_id}")
    if artifact.path.is_absolute():
        return artifact.path
    return root / artifact.path


def _location_key(artifact: Artifact) -> str:
    if artifact.path is not None:
        return f"path:{artifact.path.as_posix()}"
    return f"uri:{artifact.uri}"


def _duplicates(values: Any) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)
