from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from ..artifact import Artifact, Capability, _ArtlinkModel
from ..materialize import MaterializationPlan
from ..registry import ArtifactRegistry
from ..resolver import ResolutionPlan

__all__ = (
    "ToolRequirement",
    "artifact_id",
    "first_path_for_role",
    "matching_paths",
    "path_artifacts",
    "paths_for_role",
    "resolved_artifact_locations",
    "tool_artifact",
    "tools_from_artifacts",
    "unique_parent_dirs",
)

ProvidesFactory = Callable[[Path, Path], tuple[Capability, ...]]


class ToolRequirement(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str = "any"
    packages: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("name", "version")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        if not value:
            raise ValueError("tool requirement fields must not be empty")
        return value


def path_artifacts(
    root: Path,
    globs: tuple[str, ...],
    *,
    role: str,
    kind: str,
    language: str = "",
    metadata: dict[str, Any] | None = None,
    provides: ProvidesFactory | None = None,
) -> tuple[Artifact, ...]:
    artifacts: list[Artifact] = []
    project_root = Path(root)
    for path in matching_paths(project_root, globs):
        relative_path = path.relative_to(project_root)
        artifacts.append(
            Artifact(
                id=artifact_id(role, relative_path),
                path=relative_path,
                kind=kind,
                role=role,
                language=language,
                provides=() if provides is None else provides(path, relative_path),
                metadata=dict(metadata or {}),
            )
        )
    return tuple(artifacts)


def tool_artifact(tool: ToolRequirement) -> Artifact:
    metadata: dict[str, Any] = {"name": tool.name, "version": tool.version, "packages": list(tool.packages)}
    provides = [Capability(kind="tool", name=tool.name)]
    provides.extend(Capability(kind="python-package", name=package) for package in tool.packages)
    return Artifact(
        id=f"tool-{tool.name}",
        uri=f"tool:{tool.name}",
        kind="tool",
        role="tool",
        provides=tuple(provides),
        metadata=metadata,
    )


def matching_paths(root: Path, globs: tuple[str, ...]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    paths: list[Path] = []
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                paths.append(path)
    return tuple(paths)


def artifact_id(role: str, path: Path) -> str:
    return f"{role}-{re.sub(r'[^A-Za-z0-9]+', '-', path.as_posix()).strip('-')}"


def resolved_artifact_locations(
    resolution: ResolutionPlan,
    registry: ArtifactRegistry,
    *,
    materialization_plan: MaterializationPlan | None,
) -> Iterable[tuple[Artifact, Path | None]]:
    resolved_manifest_keys = {_manifest_key(manifest.name, manifest.version) for manifest in resolution.resolved_manifests}
    materialized_paths = {
        (action.manifest_key, action.artifact_id): action.destination
        for action in (() if materialization_plan is None else materialization_plan.actions)
        if action.destination is not None
    }
    for entry in registry.artifacts():
        manifest_key = _manifest_key(entry.manifest_name, entry.manifest_version)
        if manifest_key not in resolved_manifest_keys:
            continue
        materialized_path = materialized_paths.get((manifest_key, entry.artifact.display_id))
        if materialized_path is not None:
            yield entry.artifact, materialized_path
        elif entry.artifact.path is not None:
            yield entry.artifact, registry.artifact_file_path(entry)
        else:
            yield entry.artifact, None


def paths_for_role(artifacts: tuple[tuple[Artifact, Path | None], ...], role: str) -> tuple[Path, ...]:
    return tuple(sorted(path for artifact, path in artifacts if artifact.role == role and path is not None))


def first_path_for_role(artifacts: tuple[tuple[Artifact, Path | None], ...], role: str) -> Path | None:
    paths = paths_for_role(artifacts, role)
    if not paths:
        return None
    return paths[0]


def unique_parent_dirs(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    return tuple(sorted({path.parent for path in paths}))


def tools_from_artifacts(artifacts: tuple[tuple[Artifact, Path | None], ...]) -> dict[str, ToolRequirement]:
    return {str(artifact.metadata["name"]): tool_requirement_from_artifact(artifact) for artifact, _ in artifacts if artifact.role == "tool"}


def tool_requirement_from_artifact(artifact: Artifact) -> ToolRequirement:
    return ToolRequirement(
        name=str(artifact.metadata["name"]),
        version=str(artifact.metadata.get("version", "any")),
        packages=tuple(str(package) for package in artifact.metadata.get("packages", ())),
    )


def _manifest_key(name: str, version: str) -> str:
    if version:
        return f"{name}@{version}"
    return name
