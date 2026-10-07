from __future__ import annotations

import io
import re
import tarfile
import zipfile
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
    "extract_archive",
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
            source = Path(artifact_root) / artifact.path
            if not source.exists():
                raise PackageError(f"missing artifact path: {source}")
            archive.add(source, arcname=(package_root / artifact.path).as_posix(), recursive=source.is_dir())
    return archive_path


def install_package_archive(archive_path: Path, *, target_dir: Path, overwrite: bool = False) -> Path:
    destination = Path(target_dir)
    destination.mkdir(parents=True, exist_ok=True)
    extract_archive(Path(archive_path), destination, overwrite=overwrite)
    return destination


def extract_archive(source: Path, destination: Path, *, overwrite: bool = False) -> tuple[str, ...]:
    """Extract a tar or zip archive into ``destination`` and return the member
    names. Every member is checked before anything is written: one that would
    land outside the destination is refused, and so is one that would replace
    an existing file unless ``overwrite`` is set. Tar members go through the
    stdlib ``data`` filter, which also strips device nodes, setuid bits and
    links that point outside the archive."""
    root = destination.resolve()
    if tarfile.is_tarfile(source):
        with tarfile.open(source) as archive:
            names = tuple(member.name for member in archive.getmembers())
            _check_members(root, names, overwrite=overwrite)
            try:
                archive.extractall(destination, filter="data")
            except tarfile.FilterError as exc:
                raise PackageError(f"archive {source} has an unsafe member: {exc}") from exc
        return names
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            names = tuple(archive.namelist())
            _check_members(root, names, overwrite=overwrite)
            archive.extractall(destination)
        return names
    raise PackageError(f"not a tar or zip archive: {source}")


def _check_members(root: Path, names: tuple[str, ...], *, overwrite: bool) -> None:
    for name in names:
        target = (root / name).resolve()
        if target != root and root not in target.parents:
            raise PackageError(f"archive member escapes the destination: {name}")
        if not overwrite and not name.endswith("/") and (target.is_file() or target.is_symlink()):
            raise PackageError(f"refusing to overwrite {target}; pass overwrite to replace it")


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


_PACKAGE_TYPE = re.compile(r"[a-z0-9][a-z0-9.-]*")


def normalize_package_type(package_type: str) -> str:
    """The package type is one path component of the archive layout, so it is
    held to the characters a component may contain."""
    key = package_type.strip().lower().replace("_", "-")
    if not key:
        raise PackageError("package type must not be empty")
    normalized = PACKAGE_TYPE_ALIASES.get(key, key)
    if not _PACKAGE_TYPE.fullmatch(normalized):
        raise PackageError(f"invalid package type {package_type!r}: expected letters, digits, dots and hyphens")
    return normalized


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
