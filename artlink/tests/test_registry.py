from pathlib import Path
from typing import Any

import pytest

from artlink import (
    ARTLINK_INSTALL_SUBDIR,
    ARTLINK_MANIFEST_ENTRY_POINT_GROUP,
    ARTLINK_REGISTRY_SCHEMA,
    MANIFEST_INSTALL_SUBDIR,
    Artifact,
    ArtifactRegistry,
    ArtifactSelector,
    Capability,
    Manifest,
    Reference,
    RegistryError,
    Template,
    TemplateRule,
    artlink_install_dir,
    load_registry,
    manifest_install_dir,
)


def test_registry_registers_explicit_manifest_and_artifacts() -> None:
    registry = ArtifactRegistry()
    manifest = Manifest(
        name="source-package",
        artifacts=(Artifact(id="filter-rtl", path=Path("rtl/filter.sv"), kind="source", role="hdl-source", provides=("filter",)),),
    )
    extra_artifact = Artifact(id="driver-wheel", uri="https://example.invalid/driver.whl", kind="binary", role="driver")

    registry.register_manifest(manifest, source="explicit:test")
    registry.register_artifact(extra_artifact, source="explicit:test")

    assert registry.get_manifest("source-package") == manifest
    assert [entry.manifest.name for entry in registry.manifests()] == ["source-package"]
    assert [entry.artifact.display_id for entry in registry.artifacts()] == ["filter-rtl", "driver-wheel"]
    assert registry.find_artifacts(role="hdl-source", provides="filter")[0].source == "explicit:test"
    assert registry.find_artifacts(role="driver")[0].manifest_name == ""


def test_registry_finds_artifacts_by_typed_capability() -> None:
    registry = ArtifactRegistry()
    registry.register_artifact(
        Artifact(path=Path("rtl/filter.sv"), role="hdl-source", provides=(Capability(kind="hdl-module", name="filter"),)),
        source="explicit:test",
    )

    assert registry.find_artifacts(provides="filter")
    assert registry.find_artifacts(provides=Capability(kind="hdl-module", name="filter"))
    assert not registry.find_artifacts(provides=Capability(kind="python-import", name="filter"))


def test_registry_rejects_duplicate_manifest_names() -> None:
    registry = ArtifactRegistry()
    manifest = Manifest(name="same", artifacts=(Artifact(path=Path("a.txt"), kind="metadata", role="note"),))

    registry.register_manifest(manifest)

    with pytest.raises(RegistryError, match="duplicate manifest"):
        registry.register_manifest(manifest)


def test_registry_resolves_manifest_references() -> None:
    registry = ArtifactRegistry()
    dependency = Manifest(name="source-package", artifacts=(Artifact(path=Path("rtl/filter.sv"), kind="source", role="hdl-source"),))
    project = Manifest(
        name="project",
        artifacts=(Artifact(path=Path("project.yaml"), kind="metadata", role="project"),),
        references=(Reference(kind="manifest", target="source-package"),),
    )

    registry.register_manifest(dependency, source="explicit:dependency")

    assert registry.resolve_reference(project.references[0]).manifest == dependency
    assert [entry.manifest.name for entry in registry.resolve_manifest_references(project)] == ["source-package"]


def test_registry_resolves_template_references_and_configured_template_files(tmp_path: Path) -> None:
    explicit_template = Template(name="explicit-template")
    file_template = Template(name="file-template", rules=(TemplateRule(name="requires-data", selector=ArtifactSelector(role="data")),))
    template_path = tmp_path / "templates" / "file-template.yaml"
    template_path.parent.mkdir()
    template_path.write_text(file_template.to_yaml_text(), encoding="utf-8")
    config_path = tmp_path / "registry.yaml"
    config_path.write_text(
        f"""
schema: {ARTLINK_REGISTRY_SCHEMA}
template_files:
  - templates/file-template.yaml
registered_templates:
  - schema: artlink.template/v0
    name: explicit-template
""".lstrip(),
        encoding="utf-8",
    )

    registry = load_registry(config_path)

    assert registry.resolve_reference(Reference(kind="template", target="explicit-template")).template == explicit_template
    assert registry.resolve_reference(Reference(kind="template", target="file-template")).template == file_template
    assert [
        entry.template.name
        for entry in registry.resolve_template_references(Manifest(name="project", references=(Reference(kind="template", target="file-template"),)))
    ] == ["file-template"]


def test_registry_allows_or_denies_multiple_manifest_versions() -> None:
    v1 = Manifest(name="hdl-filter", version="1.0.0", artifacts=(Artifact(path=Path("v1/filter.sv"), kind="source", role="hdl-source"),))
    v2 = Manifest(name="hdl-filter", version="2.0.0", artifacts=(Artifact(path=Path("v2/filter.sv"), kind="source", role="hdl-source"),))

    strict_registry = ArtifactRegistry()
    strict_registry.register_manifest(v1)
    with pytest.raises(RegistryError, match="duplicate manifest"):
        strict_registry.register_manifest(v2)

    versioned_registry = ArtifactRegistry(allow_manifest_versions=True)
    versioned_registry.register_manifest(v1)
    versioned_registry.register_manifest(v2)

    assert versioned_registry.resolve_reference(Reference(kind="manifest", target="hdl-filter", version="2.0.0")).manifest == v2
    with pytest.raises(RegistryError, match="ambiguous manifest reference"):
        versioned_registry.resolve_reference(Reference(kind="manifest", target="hdl-filter"))


def test_registry_discovers_manifests_from_install_path(tmp_path: Path) -> None:
    install_dir = manifest_install_dir(tmp_path)
    install_dir.mkdir(parents=True)
    artifact_path = install_dir / "installed-package" / "data.txt"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("payload\n", encoding="utf-8")
    manifest = Manifest(
        name="installed-package",
        artifacts=(Artifact(id="installed-artifact", path=Path("installed-package/data.txt"), kind="metadata", role="data"),),
    )
    (install_dir / "installed.yaml").write_text(manifest.to_yaml_text(), encoding="utf-8")

    registry = ArtifactRegistry.from_install_path(tmp_path)

    assert install_dir == tmp_path / MANIFEST_INSTALL_SUBDIR
    assert registry.get_manifest("installed-package") == manifest
    entry = registry.find_artifacts(role="data")[0]
    assert entry.source.endswith("installed.yaml")
    assert entry.root == install_dir
    assert registry.artifact_file_path(entry) == artifact_path


def test_registry_discovers_manifests_from_share_artlink_subdirectories(tmp_path: Path) -> None:
    package_dir = artlink_install_dir(tmp_path) / "hdl-filter" / "2.0.0"
    package_dir.mkdir(parents=True)
    (package_dir / "filter.sv").write_text("module filter; endmodule\n", encoding="utf-8")
    manifest = Manifest(
        name="hdl-filter",
        version="2.0.0",
        artifacts=(Artifact(id="filter-rtl", path=Path("filter.sv"), kind="source", role="hdl-source"),),
    )
    (package_dir / "manifest.yaml").write_text(manifest.to_yaml_text(), encoding="utf-8")

    registry = ArtifactRegistry.from_install_path(tmp_path, allow_manifest_versions=True)

    assert artlink_install_dir(tmp_path) == tmp_path / ARTLINK_INSTALL_SUBDIR
    assert registry.get_manifest("hdl-filter", version="2.0.0") == manifest
    assert registry.artifact_file_path(registry.find_artifacts(role="hdl-source")[0]) == package_dir / "filter.sv"


def test_registry_discovers_manifests_from_entry_points(tmp_path: Path) -> None:
    manifest_from_path = Manifest(
        name="entry-point-file",
        artifacts=(Artifact(id="file-artifact", path=Path("file.txt"), kind="metadata", role="data"),),
    )
    manifest_path = tmp_path / "entry-point-file.yaml"
    manifest_path.write_text(manifest_from_path.to_yaml_text(), encoding="utf-8")
    manifest_from_callable = Manifest(
        name="entry-point-callable",
        artifacts=(Artifact(id="callable-artifact", path=Path("callable.txt"), kind="metadata", role="data"),),
    )

    entry_points = (
        FakeEntryPoint("file-provider", ARTLINK_MANIFEST_ENTRY_POINT_GROUP, manifest_path),
        FakeEntryPoint("callable-provider", ARTLINK_MANIFEST_ENTRY_POINT_GROUP, lambda: (manifest_from_callable,)),
        FakeEntryPoint(
            "other-provider", "other.group", Manifest(name="ignored", artifacts=(Artifact(path=Path("ignored.txt"), kind="metadata", role="data"),))
        ),
    )

    registry = ArtifactRegistry().discover_entry_points(entry_points=entry_points)

    assert sorted(entry.manifest.name for entry in registry.manifests()) == ["entry-point-callable", "entry-point-file"]
    assert sorted(entry.artifact.display_id for entry in registry.artifacts()) == ["callable-artifact", "file-artifact"]
    assert registry.get_manifest_entry("entry-point-file").source == "entry-point:file-provider"


def test_registry_entry_point_manifest_file_uses_manifest_directory_root(tmp_path: Path) -> None:
    install_dir = manifest_install_dir(tmp_path)
    package_dir = artlink_install_dir(tmp_path) / "entry-point-package"
    install_dir.mkdir(parents=True)
    package_dir.mkdir(parents=True)
    artifact_path = package_dir / "payload.txt"
    artifact_path.write_text("payload\n", encoding="utf-8")
    manifest = Manifest(
        name="entry-point-installed-file",
        artifacts=(Artifact(id="payload", path=Path("../entry-point-package/payload.txt"), kind="metadata", role="data"),),
    )
    manifest_path = install_dir / "entry-point-installed-file.yaml"
    manifest_path.write_text(manifest.to_yaml_text(), encoding="utf-8")

    registry = ArtifactRegistry().discover_entry_points(
        entry_points=(FakeEntryPoint("installed-file-provider", ARTLINK_MANIFEST_ENTRY_POINT_GROUP, manifest_path),)
    )

    entry = registry.find_artifacts(role="data")[0]
    assert entry.root == install_dir
    assert registry.artifact_file_path(entry) == artifact_path


def test_registry_loads_configured_sources_from_yaml(tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifests"
    data_dir = manifest_dir / "payload"
    docs_dir = tmp_path / "docs"
    data_dir.mkdir(parents=True)
    docs_dir.mkdir()
    (data_dir / "data.txt").write_text("payload\n", encoding="utf-8")
    (docs_dir / "readme.txt").write_text("docs\n", encoding="utf-8")
    manifest = Manifest(
        name="configured-source-package",
        artifacts=(Artifact(id="data", path=Path("payload/data.txt"), kind="metadata", role="data"),),
    )
    manifest_path = manifest_dir / "source.yaml"
    manifest_path.write_text(manifest.to_yaml_text(), encoding="utf-8")
    config_path = tmp_path / "registry.yaml"
    config_path.write_text(
        f"""
    schema: {ARTLINK_REGISTRY_SCHEMA}
manifest_files:
  - manifests/source.yaml
registered_artifacts:
  - id: local-doc
    path: docs/readme.txt
    kind: metadata
    role: docs
""".lstrip(),
        encoding="utf-8",
    )

    registry = load_registry(config_path)

    assert registry.get_manifest("configured-source-package") == manifest
    assert registry.artifact_file_path(registry.find_artifacts(role="data")[0]) == data_dir / "data.txt"
    assert registry.artifact_file_path(registry.find_artifacts(role="docs")[0]) == docs_dir / "readme.txt"


def test_registry_rejects_unknown_config_schema(tmp_path: Path) -> None:
    config_path = tmp_path / "registry.yaml"
    config_path.write_text(
        """
schema: artlink.registry/v99
install_roots: []
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(RegistryError, match="unsupported registry schema"):
        load_registry(config_path)


def test_registry_accepts_ccflow_target_config() -> None:
    registry = ArtifactRegistry.model_validate({"_target_": "artlink.registry.ArtifactRegistry", "allow_manifest_versions": True})

    assert registry.allow_manifest_versions


class FakeEntryPoint:
    def __init__(self, name: str, group: str, value: Any) -> None:
        self.name = name
        self.group = group
        self._value = value

    def load(self) -> Any:
        return self._value
