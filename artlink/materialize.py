from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import ConfigDict, Field

from .artifact import Artifact, ArtlinkError, _ArtlinkModel
from .registry import ArtifactRegistry, ArtifactRegistryEntry, RegistryError
from .resolver import ResolutionPlan

__all__ = (
    "MaterializationAction",
    "MaterializationError",
    "MaterializationMethod",
    "MaterializationPlan",
    "MaterializationResult",
    "build_materialization_plan",
    "execute_materialization_plan",
)

MaterializationMethod = Literal["copy", "symlink", "archive-extract", "package-resource", "reference"]
PathMaterializationMethod = Literal["copy", "symlink"]
_ARCHIVE_FORMATS = {"zip", "tar", "tar.gz", "tar.bz2", "tar.xz"}


class MaterializationError(ArtlinkError):
    """Raised when a materialization plan cannot be constructed."""


class MaterializationAction(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    artifact: Artifact
    manifest_key: str
    artifact_id: str
    method: MaterializationMethod
    source: str
    destination: Path | None = None


class MaterializationPlan(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    target_dir: Path
    actions: tuple[MaterializationAction, ...] = Field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return not self.actions


class MaterializationResult(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    actions: tuple[MaterializationAction, ...] = Field(default_factory=tuple)


def build_materialization_plan(
    resolution: ResolutionPlan,
    registry: ArtifactRegistry,
    *,
    target_dir: Path,
    path_method: PathMaterializationMethod = "copy",
) -> MaterializationPlan:
    resolved_manifest_keys = {_manifest_key(manifest.name, manifest.version) for manifest in resolution.resolved_manifests}
    actions = tuple(
        _action_for_entry(entry, registry=registry, target_dir=target_dir, path_method=path_method)
        for entry in registry.artifacts()
        if _manifest_key(entry.manifest_name, entry.manifest_version) in resolved_manifest_keys
    )
    return MaterializationPlan(target_dir=target_dir, actions=actions)


def execute_materialization_plan(plan: MaterializationPlan) -> MaterializationResult:
    for action in plan.actions:
        _execute_action(action)
    return MaterializationResult(actions=plan.actions)


def _action_for_entry(
    entry: ArtifactRegistryEntry,
    *,
    registry: ArtifactRegistry,
    target_dir: Path,
    path_method: PathMaterializationMethod,
) -> MaterializationAction:
    artifact = entry.artifact
    manifest_key = _manifest_key(entry.manifest_name, entry.manifest_version)
    if artifact.path is not None:
        try:
            source = registry.artifact_file_path(entry).as_posix()
        except RegistryError as exc:
            raise MaterializationError(str(exc)) from exc
        if artifact.format in _ARCHIVE_FORMATS:
            return MaterializationAction(
                artifact=artifact,
                manifest_key=manifest_key,
                artifact_id=artifact.display_id,
                method="archive-extract",
                source=source,
                destination=_archive_destination_for_path(target_dir, artifact.path),
            )
        return MaterializationAction(
            artifact=artifact,
            manifest_key=manifest_key,
            artifact_id=artifact.display_id,
            method=path_method,
            source=source,
            destination=_destination_for_path(target_dir, artifact.path),
        )

    if artifact.uri.startswith("package://"):
        return MaterializationAction(
            artifact=artifact,
            manifest_key=manifest_key,
            artifact_id=artifact.display_id,
            method="package-resource",
            source=artifact.uri,
            destination=_destination_for_package_uri(target_dir, artifact.uri),
        )

    return MaterializationAction(
        artifact=artifact,
        manifest_key=manifest_key,
        artifact_id=artifact.display_id,
        method="reference",
        source=artifact.uri,
        destination=None,
    )


def _destination_for_path(target_dir: Path, artifact_path: Path) -> Path:
    if artifact_path.is_absolute() or ".." in artifact_path.parts:
        return target_dir / artifact_path.name
    return target_dir / artifact_path


def _archive_destination_for_path(target_dir: Path, artifact_path: Path) -> Path:
    archive_name = artifact_path.name
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if archive_name.endswith(suffix):
            return target_dir / archive_name.removesuffix(suffix)
    return target_dir / artifact_path.stem


def _destination_for_package_uri(target_dir: Path, uri: str) -> Path:
    parsed = urlparse(uri)
    resource_path = Path(parsed.path.lstrip("/"))
    if not parsed.netloc or not resource_path.parts:
        raise MaterializationError(f"invalid package resource uri: {uri}")
    return target_dir / resource_path.name


def _execute_action(action: MaterializationAction) -> None:
    if action.method == "reference":
        return
    if action.destination is None:
        raise MaterializationError(f"materialization action requires a destination: {action.artifact_id}")
    if action.method == "copy":
        _copy_path(Path(action.source), action.destination)
        return
    if action.method == "symlink":
        _symlink_path(Path(action.source), action.destination)
        return
    if action.method == "archive-extract":
        action.destination.mkdir(parents=True, exist_ok=True)
        shutil.unpack_archive(action.source, action.destination)
        return
    if action.method == "package-resource":
        _copy_package_resource(action.source, action.destination)
        return
    raise MaterializationError(f"unsupported materialization method: {action.method}")


def _copy_path(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
        return
    shutil.copy2(source, destination)


def _symlink_path(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    destination.symlink_to(source, target_is_directory=source.is_dir())


def _copy_package_resource(uri: str, destination: Path) -> None:
    parsed = urlparse(uri)
    package = parsed.netloc
    resource_path = parsed.path.lstrip("/")
    if not package or not resource_path:
        raise MaterializationError(f"invalid package resource uri: {uri}")
    resource = resources.files(package).joinpath(resource_path)
    with resources.as_file(resource) as source:
        _copy_path(source, destination)


def _manifest_key(name: str, version: str) -> str:
    if version:
        return f"{name}@{version}"
    return name
