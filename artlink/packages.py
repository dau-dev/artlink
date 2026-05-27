from __future__ import annotations

import io
import re
import shutil
import tarfile
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from .artifact import ArtlinkError, _ArtlinkModel
from .manifest import Manifest
from .registry import ArtifactRegistry

__all__ = (
    "PackageError",
    "PackageSummary",
    "build_package_archive",
    "discover_packages",
    "install_package_archive",
    "normalize_package_type",
    "package_archive_name",
)

PACKAGE_TYPE_ALIASES = {
    "documentation": "docs",
    "documentation-site": "docs",
    "doc": "docs",
    "docs": "docs",
    "hdl": "hdl",
    "hardware": "hdl",
    "hardware-project": "hdl",
    "ml": "ml",
    "model": "ml",
    "model-release": "ml",
    "py": "python",
    "python": "python",
    "python-package": "python",
}


class PackageError(ArtlinkError):
    """Raised when an artlink package archive cannot be built or installed."""


class PackageSummary(_ArtlinkModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    package_type: str = Field(alias="type")
    name: str
    version: str = ""
    source: str = ""
    artifact_count: int = 0

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)


def build_package_archive(
    manifest: Manifest,
    *,
    artifact_root: Path,
    output_dir: Path,
    package_type: str,
) -> Path:
    normalized_type = normalize_package_type(package_type)
    if not manifest.version:
        raise PackageError("package archives require a manifest version")

    archive_path = Path(output_dir) / package_archive_name(manifest.name, manifest.version)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    package_root = Path("share") / "artlink" / normalized_type / _safe_component(manifest.name) / _safe_component(manifest.version)
    packaged_manifest = _packaged_manifest(manifest, package_type=normalized_type)

    with tarfile.open(archive_path, "w:gz") as archive:
        _add_manifest(archive, package_root / "manifest.yaml", packaged_manifest)
        for artifact in packaged_manifest.artifacts:
            if artifact.path is None:
                continue
            source = artifact.path if artifact.path.is_absolute() else Path(artifact_root) / artifact.path
            if not source.exists():
                raise PackageError(f"missing artifact path: {source}")
            archive.add(source, arcname=(package_root / _archive_artifact_path(artifact.path)).as_posix(), recursive=source.is_dir())
    return archive_path


def install_package_archive(archive_path: Path, *, target_dir: Path) -> Path:
    destination = Path(target_dir)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.unpack_archive(str(archive_path), str(destination))
    return destination


def discover_packages(root: Path, *, package_type: str = "") -> tuple[PackageSummary, ...]:
    normalized_type = normalize_package_type(package_type) if package_type else ""
    registry = ArtifactRegistry.from_install_path(Path(root), allow_manifest_versions=True)
    summaries: list[PackageSummary] = []
    for entry in registry.manifests():
        entry_type = _manifest_package_type(entry.manifest)
        if normalized_type and entry_type != normalized_type:
            continue
        summaries.append(
            PackageSummary(
                package_type=entry_type,
                name=entry.manifest.name,
                version=entry.manifest.version,
                source=entry.source,
                artifact_count=sum(1 for artifact in entry.manifest.artifacts if artifact.path is not None),
            )
        )
    return tuple(sorted(summaries, key=lambda package: (package.package_type, package.name, package.version)))


def normalize_package_type(package_type: str) -> str:
    key = package_type.strip().lower().replace("_", "-")
    if not key:
        raise PackageError("package type must not be empty")
    return PACKAGE_TYPE_ALIASES.get(key, key)


def package_archive_name(name: str, version: str) -> str:
    if not name or not version:
        raise PackageError("package archive name requires name and version")
    return f"{_safe_component(name)}-{_safe_component(version)}.tar.gz"


def _packaged_manifest(manifest: Manifest, *, package_type: str) -> Manifest:
    metadata = {**manifest.metadata, "package_type": package_type}
    return manifest.model_copy(update={"metadata": metadata})


def _add_manifest(archive: tarfile.TarFile, archive_path: Path, manifest: Manifest) -> None:
    payload = manifest.to_yaml_text().encode("utf-8")
    info = tarfile.TarInfo(archive_path.as_posix())
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def _archive_artifact_path(path: Path) -> Path:
    if path.is_absolute() or ".." in path.parts:
        return Path(path.name)
    return path


def _manifest_package_type(manifest: Manifest) -> str:
    package_type = manifest.metadata.get("package_type") or manifest.metadata.get("profile") or ""
    if not isinstance(package_type, str) or not package_type:
        return "unknown"
    return normalize_package_type(package_type)


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    if not cleaned:
        raise PackageError(f"invalid package path component: {value!r}")
    return cleaned
