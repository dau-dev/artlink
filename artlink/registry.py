from __future__ import annotations

import sysconfig
from collections.abc import Iterable
from importlib import metadata
from os import PathLike
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import Field, PrivateAttr, ValidationError, model_validator

from .artifact import Artifact, ArtlinkError, CapabilityValue, Reference, _ArtlinkModel, has_capability
from .manifest import ARTLINK_MANIFEST_SCHEMA, Manifest, load_manifest
from .template import Template, load_template

__all__ = (
    "ARTLINK_REGISTRY_SCHEMA",
    "ARTLINK_INSTALL_SUBDIR",
    "ARTLINK_MANIFEST_ENTRY_POINT_GROUP",
    "MANIFEST_INSTALL_SUBDIR",
    "RegistryError",
    "ManifestRegistryEntry",
    "TemplateRegistryEntry",
    "ArtifactRegistryEntry",
    "ArtifactRegistry",
    "artlink_install_dir",
    "load_registry",
    "manifest_install_dir",
    "registry_from_mapping",
)


ARTLINK_REGISTRY_SCHEMA = "artlink.registry/v0"
ARTLINK_INSTALL_SUBDIR = Path("share") / "artlink"
ARTLINK_MANIFEST_ENTRY_POINT_GROUP = "artlink.manifests"
MANIFEST_INSTALL_SUBDIR = ARTLINK_INSTALL_SUBDIR / "manifests"
_MANIFEST_FILE_PATTERNS = ("*.yaml", "*.yml")


class RegistryError(ArtlinkError):
    """Raised when registry discovery or registration fails."""


class ManifestRegistryEntry(_ArtlinkModel):
    manifest: Manifest
    source: str
    root: Path | None = None


class TemplateRegistryEntry(_ArtlinkModel):
    template: Template
    source: str
    root: Path | None = None


class ArtifactRegistryEntry(_ArtlinkModel):
    artifact: Artifact
    source: str
    manifest_name: str = ""
    manifest_version: str = ""
    root: Path | None = None


class ArtifactRegistry(_ArtlinkModel):
    """Registry of available manifests and artifacts."""

    allow_manifest_versions: bool = False
    allow_template_versions: bool = False
    install_roots: tuple[Path, ...] = Field(default_factory=tuple)
    manifest_files: tuple[Path, ...] = Field(default_factory=tuple)
    template_files: tuple[Path, ...] = Field(default_factory=tuple)
    registered_manifests: tuple[Manifest, ...] = Field(default_factory=tuple)
    registered_templates: tuple[Template, ...] = Field(default_factory=tuple)
    registered_artifacts: tuple[Artifact, ...] = Field(default_factory=tuple)
    artifact_root: Path | None = None
    _manifests: dict[tuple[str, str], ManifestRegistryEntry] = PrivateAttr(default_factory=dict)
    _templates: dict[tuple[str, str], TemplateRegistryEntry] = PrivateAttr(default_factory=dict)
    _artifacts: list[ArtifactRegistryEntry] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _load_configured_sources(self) -> Self:
        for manifest in self.registered_manifests:
            self.register_manifest(manifest, source="configured")
        for template in self.registered_templates:
            self.register_template(template, source="configured")
        for artifact in self.registered_artifacts:
            self.register_artifact(artifact, source="configured", root=self.artifact_root)
        for manifest_file in self.manifest_files:
            self.register_manifest_file(manifest_file)
        for template_file in self.template_files:
            self.register_template_file(template_file)
        for install_root in self.install_roots:
            self.discover_install_path(install_root)
        return self

    @classmethod
    def from_manifests(
        cls,
        manifests: Iterable[Manifest],
        *,
        source: str = "explicit",
        root: Path | None = None,
        allow_manifest_versions: bool = False,
    ) -> "ArtifactRegistry":
        registry = cls(allow_manifest_versions=allow_manifest_versions)
        for manifest in manifests:
            registry.register_manifest(manifest, source=source, root=root)
        return registry

    @classmethod
    def from_manifest_files(
        cls,
        paths: Iterable[Path],
        *,
        source: str | None = None,
        root: Path | None = None,
        allow_manifest_versions: bool = False,
    ) -> "ArtifactRegistry":
        registry = cls(allow_manifest_versions=allow_manifest_versions)
        for path in paths:
            registry.register_manifest_file(path, source=source, root=root)
        return registry

    @classmethod
    def from_install_path(cls, root: Path | None = None, *, allow_manifest_versions: bool = False) -> "ArtifactRegistry":
        return cls(allow_manifest_versions=allow_manifest_versions).discover_install_path(root)

    def register_manifest(self, manifest: Manifest, *, source: str = "explicit", root: Path | None = None) -> "ArtifactRegistry":
        manifest_key = (manifest.name, manifest.version)
        registration_root = Path(root) if root is not None else None
        if manifest_key in self._manifests or (not self.allow_manifest_versions and self._entries_for_name(manifest.name)):
            raise RegistryError(f"duplicate manifest registration: {manifest.name}")
        self._manifests[manifest_key] = ManifestRegistryEntry(manifest=manifest, source=source, root=registration_root)
        for artifact in manifest.artifacts:
            self.register_artifact(artifact, source=source, manifest_name=manifest.name, manifest_version=manifest.version, root=registration_root)
        return self

    def register_manifest_file(self, path: Path, *, source: str | None = None, root: Path | None = None) -> "ArtifactRegistry":
        manifest_path = Path(path)
        manifest_source = source or manifest_path.as_posix()
        registration_root = manifest_path.parent if root is None else Path(root)
        return self.register_manifest(load_manifest(manifest_path), source=manifest_source, root=registration_root)

    def register_template(self, template: Template, *, source: str = "explicit", root: Path | None = None) -> "ArtifactRegistry":
        template_key = (template.name, template.version)
        registration_root = Path(root) if root is not None else None
        if template_key in self._templates or (not self.allow_template_versions and self._template_entries_for_name(template.name)):
            raise RegistryError(f"duplicate template registration: {template.name}")
        self._templates[template_key] = TemplateRegistryEntry(template=template, source=source, root=registration_root)
        return self

    def register_template_file(self, path: Path, *, source: str | None = None, root: Path | None = None) -> "ArtifactRegistry":
        template_path = Path(path)
        template_source = source or template_path.as_posix()
        registration_root = template_path.parent if root is None else Path(root)
        return self.register_template(load_template(template_path), source=template_source, root=registration_root)

    def register_artifact(
        self,
        artifact: Artifact,
        *,
        source: str = "explicit",
        manifest_name: str = "",
        manifest_version: str = "",
        root: Path | None = None,
    ) -> "ArtifactRegistry":
        registration_root = Path(root) if root is not None else None
        self._artifacts.append(
            ArtifactRegistryEntry(
                artifact=artifact,
                source=source,
                manifest_name=manifest_name,
                manifest_version=manifest_version,
                root=registration_root,
            )
        )
        return self

    def discover_install_path(self, root: Path | None = None) -> "ArtifactRegistry":
        install_prefix = _install_prefix(root)
        return self.discover_manifest_files(artlink_install_dir(install_prefix))

    def discover_manifest_files(
        self,
        directory: Path,
        *,
        patterns: tuple[str, ...] = _MANIFEST_FILE_PATTERNS,
        root: Path | None = None,
    ) -> "ArtifactRegistry":
        manifest_dir = Path(directory)
        if not manifest_dir.exists():
            return self
        discovered: set[Path] = set()
        for pattern in patterns:
            for path in sorted(manifest_dir.rglob(pattern)):
                if path in discovered or not path.is_file():
                    continue
                if not _is_artlink_manifest_file(path):
                    continue
                discovered.add(path)
                self.register_manifest_file(path, root=None if root is None else Path(root))
        return self

    def discover_entry_points(
        self,
        *,
        group: str = ARTLINK_MANIFEST_ENTRY_POINT_GROUP,
        entry_points: Any | None = None,
    ) -> "ArtifactRegistry":
        for entry_point in _select_entry_points(group=group, entry_points=entry_points):
            source = f"entry-point:{entry_point.name}"
            value = entry_point.load()
            self._register_discovered_value(value, source=source)
        return self

    def manifests(self) -> tuple[ManifestRegistryEntry, ...]:
        return tuple(self._manifests.values())

    def templates(self) -> tuple[TemplateRegistryEntry, ...]:
        return tuple(self._templates.values())

    def artifacts(self) -> tuple[ArtifactRegistryEntry, ...]:
        return tuple(self._artifacts)

    def get_manifest_entry(self, name: str, *, version: str = "") -> ManifestRegistryEntry:
        if version:
            try:
                return self._manifests[(name, version)]
            except KeyError as exc:
                raise RegistryError(f"unknown manifest: {name} {version}") from exc

        matching_entries = self._entries_for_name(name)
        if not matching_entries:
            raise RegistryError(f"unknown manifest: {name}")
        if len(matching_entries) > 1:
            versions = ", ".join(entry.manifest.version or "<unversioned>" for entry in matching_entries)
            raise RegistryError(f"ambiguous manifest reference: {name} has versions {versions}")
        return matching_entries[0]

    def get_manifest(self, name: str, *, version: str = "") -> Manifest:
        return self.get_manifest_entry(name, version=version).manifest

    def get_template_entry(self, name: str, *, version: str = "") -> TemplateRegistryEntry:
        if version:
            try:
                return self._templates[(name, version)]
            except KeyError as exc:
                raise RegistryError(f"unknown template: {name} {version}") from exc

        matching_entries = self._template_entries_for_name(name)
        if not matching_entries:
            raise RegistryError(f"unknown template: {name}")
        if len(matching_entries) > 1:
            versions = ", ".join(entry.template.version or "<unversioned>" for entry in matching_entries)
            raise RegistryError(f"ambiguous template reference: {name} has versions {versions}")
        return matching_entries[0]

    def get_template(self, name: str, *, version: str = "") -> Template:
        return self.get_template_entry(name, version=version).template

    def find_artifacts(
        self,
        *,
        kind: str = "",
        role: str = "",
        provides: CapabilityValue = "",
        requires: CapabilityValue = "",
    ) -> tuple[ArtifactRegistryEntry, ...]:
        return tuple(
            entry
            for entry in self._artifacts
            if (not kind or entry.artifact.kind == kind)
            and (not role or entry.artifact.role == role)
            and (not provides or has_capability(entry.artifact.provides, provides))
            and (not requires or has_capability(entry.artifact.requires, requires))
        )

    def resolve_reference(self, reference: Reference) -> Any:
        if reference.kind == "manifest":
            return self.get_manifest_entry(reference.target, version=reference.version)
        if reference.kind == "template":
            return self.get_template_entry(reference.target, version=reference.version)
        raise RegistryError(f"unsupported reference kind: {reference.kind}")

    def resolve_manifest_references(self, manifest: Manifest) -> tuple[ManifestRegistryEntry, ...]:
        return tuple(
            self.get_manifest_entry(reference.target, version=reference.version) for reference in manifest.references if reference.kind == "manifest"
        )

    def resolve_template_references(self, manifest: Manifest) -> tuple[TemplateRegistryEntry, ...]:
        return tuple(
            self.get_template_entry(reference.target, version=reference.version) for reference in manifest.references if reference.kind == "template"
        )

    def artifact_file_path(self, entry: ArtifactRegistryEntry) -> Path:
        artifact_path = entry.artifact.path
        if artifact_path is None:
            raise RegistryError(f"artifact has no filesystem path: {entry.artifact.display_id}")
        if artifact_path.is_absolute():
            return artifact_path
        if entry.root is None:
            return artifact_path
        return (entry.root / artifact_path).resolve(strict=False)

    def _entries_for_name(self, name: str) -> tuple[ManifestRegistryEntry, ...]:
        return tuple(entry for (manifest_name, _), entry in self._manifests.items() if manifest_name == name)

    def _template_entries_for_name(self, name: str) -> tuple[TemplateRegistryEntry, ...]:
        return tuple(entry for (template_name, _), entry in self._templates.items() if template_name == name)

    def _register_discovered_value(self, value: Any, *, source: str) -> None:
        if callable(value) and not isinstance(value, Manifest):
            value = value()
        if isinstance(value, Manifest):
            self.register_manifest(value, source=source)
            return
        if isinstance(value, Template):
            self.register_template(value, source=source)
            return
        if isinstance(value, str | PathLike):
            self.register_manifest_file(Path(value), source=source)
            return
        if isinstance(value, Iterable):
            for item in value:
                self._register_discovered_value(item, source=source)
            return
        raise RegistryError(f"unsupported registry discovery value from {source}: {value!r}")


def artlink_install_dir(root: Path | None = None) -> Path:
    return _install_prefix(root) / ARTLINK_INSTALL_SUBDIR


def manifest_install_dir(root: Path | None = None) -> Path:
    return _install_prefix(root) / MANIFEST_INSTALL_SUBDIR


def load_registry(path: Path) -> ArtifactRegistry:
    registry_path = Path(path)
    raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RegistryError("registry config must be a YAML mapping")
    return registry_from_mapping(_resolve_registry_config_paths(raw, base_dir=registry_path.parent))


def registry_from_mapping(raw: dict[str, Any]) -> ArtifactRegistry:
    normalized = _validate_registry_schema(raw)
    try:
        return ArtifactRegistry.model_validate(normalized)
    except ValidationError as exc:
        raise RegistryError(str(exc)) from exc


def _validate_registry_schema(raw: dict[str, Any]) -> dict[str, Any]:
    schema = raw.get("schema")
    if schema is None:
        return raw
    if schema != ARTLINK_REGISTRY_SCHEMA:
        raise RegistryError(f"unsupported registry schema: {schema}")
    normalized = dict(raw)
    normalized.pop("schema")
    return normalized


def _is_artlink_manifest_file(path: Path) -> bool:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return False
    return isinstance(raw, dict) and raw.get("schema") == ARTLINK_MANIFEST_SCHEMA


def _install_prefix(root: Path | None = None) -> Path:
    return Path(sysconfig.get_path("data")) if root is None else Path(root)


def _resolve_registry_config_paths(raw: dict[str, Any], *, base_dir: Path) -> dict[str, Any]:
    resolved = dict(raw)
    for key in ("install_roots", "manifest_files", "template_files"):
        if key in resolved:
            resolved[key] = tuple(_resolve_config_path(base_dir, path) for path in _path_values(resolved[key]))
    if "artifact_root" in resolved and resolved["artifact_root"] is not None:
        resolved["artifact_root"] = _resolve_config_path(base_dir, resolved["artifact_root"])
    elif "registered_artifacts" in resolved:
        resolved["artifact_root"] = base_dir
    return resolved


def _path_values(value: Any) -> tuple[Any, ...]:
    if isinstance(value, str | PathLike):
        return (value,)
    return tuple(value)


def _resolve_config_path(base_dir: Path, value: Any) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return base_dir / path


def _select_entry_points(*, group: str, entry_points: Any | None) -> tuple[Any, ...]:
    discovered = metadata.entry_points() if entry_points is None else entry_points
    if hasattr(discovered, "select"):
        return tuple(discovered.select(group=group))
    if isinstance(discovered, dict):
        return tuple(discovered.get(group, ()))
    return tuple(entry_point for entry_point in discovered if getattr(entry_point, "group", group) == group)
