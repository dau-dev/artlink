from pathlib import Path

import pytest
from ccflow.base import BaseModel

from artlink import Artifact, ArtifactRegistry, Capability, Manifest, Reference, ResolutionError, Template, resolve_manifest


def test_core_objects_are_ccflow_models_and_registry_can_be_configured() -> None:
    artifact = Artifact(path=Path("rtl/filter.sv"), kind="source", role="hdl-source")
    manifest = Manifest(name="source-package", artifacts=(artifact,))
    registry = ArtifactRegistry.model_validate({"_target_": "artlink.registry.ArtifactRegistry", "allow_manifest_versions": True})

    assert isinstance(artifact, BaseModel)
    assert isinstance(manifest, BaseModel)
    assert isinstance(registry, ArtifactRegistry)
    assert registry.allow_manifest_versions
    assert "_target_" not in manifest.model_dump(mode="json", by_alias=True)
    assert "_target_" not in manifest.model_dump(mode="json", by_alias=True)["artifacts"][0]


def test_resolver_builds_recursive_manifest_graph() -> None:
    source = Manifest(name="source", artifacts=(Artifact(id="rtl", path=Path("rtl/filter.sv"), kind="source", role="hdl-source"),))
    constraints = Manifest(
        name="constraints", artifacts=(Artifact(id="xdc", path=Path("constraints/demo.xdc"), kind="metadata", role="constraints"),)
    )
    board = Manifest(name="board", references=(Reference(kind="manifest", target="constraints"),))
    project = Manifest(name="project", references=(Reference(kind="manifest", target="source"), Reference(kind="manifest", target="board")))
    registry = ArtifactRegistry.from_manifests((source, constraints, board))

    plan = resolve_manifest(project, registry)

    assert [node.key for node in plan.nodes] == ["project", "source", "board", "constraints"]
    assert [(edge.from_key, edge.to_key, edge.reference.target) for edge in plan.edges] == [
        ("project", "source", "source"),
        ("project", "board", "board"),
        ("board", "constraints", "constraints"),
    ]
    assert [manifest.name for manifest in plan.resolved_manifests] == ["source", "board", "constraints"]
    assert [artifact.display_id for artifact in plan.resolved_artifacts] == ["rtl", "xdc"]
    assert plan.issues == ()


def test_resolver_rejects_duplicate_capability_providers_by_default() -> None:
    source_a = Manifest(
        name="source-a",
        artifacts=(Artifact(id="rtl-a", path=Path("a/filter.sv"), role="hdl-source", provides=(Capability(kind="hdl-module", name="filter"),)),),
    )
    source_b = Manifest(
        name="source-b",
        artifacts=(Artifact(id="rtl-b", path=Path("b/filter.sv"), role="hdl-source", provides=(Capability(kind="hdl-module", name="filter"),)),),
    )
    project = Manifest(
        name="project",
        references=(Reference(kind="manifest", target="source-a"), Reference(kind="manifest", target="source-b")),
    )
    registry = ArtifactRegistry.from_manifests((source_a, source_b))

    with pytest.raises(ResolutionError, match="duplicate provider.*hdl-module:filter.*source-a.*source-b"):
        resolve_manifest(project, registry)


def test_resolver_can_warn_or_ignore_duplicate_capability_providers() -> None:
    source_a = Manifest(
        name="source-a",
        artifacts=(Artifact(id="rtl-a", path=Path("a/filter.sv"), role="hdl-source", provides=("filter",)),),
    )
    source_b = Manifest(
        name="source-b",
        artifacts=(Artifact(id="rtl-b", path=Path("b/filter.sv"), role="hdl-source", provides=("filter",)),),
    )
    project = Manifest(
        name="project",
        references=(Reference(kind="manifest", target="source-a"), Reference(kind="manifest", target="source-b")),
    )
    registry = ArtifactRegistry.from_manifests((source_a, source_b))

    warning_plan = resolve_manifest(project, registry, provider_conflict_policy="warning")
    ignored_plan = resolve_manifest(project, registry, provider_conflict_policy="ignore")

    assert len(warning_plan.issues) == 1
    issue = warning_plan.issues[0]
    assert issue.kind == "duplicate-provider"
    assert issue.severity == "warning"
    assert issue.capability.key == "filter"
    assert [(provider.manifest_key, provider.artifact_id) for provider in issue.providers] == [("source-a", "rtl-a"), ("source-b", "rtl-b")]
    assert ignored_plan.issues == ()


def test_resolver_can_prefer_explicit_duplicate_capability_providers() -> None:
    installed_source = Manifest(
        name="installed-source",
        artifacts=(Artifact(id="installed-rtl", path=Path("installed/filter.sv"), role="hdl-source", provides=("filter",)),),
    )
    explicit_source = Manifest(
        name="explicit-source",
        artifacts=(Artifact(id="explicit-rtl", path=Path("explicit/filter.sv"), role="hdl-source", provides=("filter",)),),
    )
    project = Manifest(
        name="project",
        references=(Reference(kind="manifest", target="installed-source"), Reference(kind="manifest", target="explicit-source")),
    )
    registry = ArtifactRegistry()
    registry.register_manifest(installed_source, source="installed")
    registry.register_manifest(explicit_source, source="explicit:user")

    plan = resolve_manifest(project, registry, provider_conflict_policy="prefer-explicit")

    assert len(plan.issues) == 1
    assert plan.issues[0].severity == "info"
    assert plan.issues[0].selected_provider is not None
    assert plan.issues[0].selected_provider.manifest_key == "explicit-source"
    assert [(provider.capability.key, provider.manifest_key) for provider in plan.provider_selections] == [("filter", "explicit-source")]


def test_resolver_can_select_highest_manifest_version_for_unversioned_references() -> None:
    v1 = Manifest(name="source", version="1.0.0", artifacts=(Artifact(id="v1", path=Path("v1/filter.sv"), role="hdl-source"),))
    v2 = Manifest(name="source", version="2.0.0", artifacts=(Artifact(id="v2", path=Path("v2/filter.sv"), role="hdl-source"),))
    project = Manifest(name="project", references=(Reference(kind="manifest", target="source"),))
    registry = ArtifactRegistry.from_manifests((v1, v2), allow_manifest_versions=True)

    plan = resolve_manifest(project, registry, manifest_version_policy="highest")

    assert [node.key for node in plan.nodes] == ["project", "source@2.0.0"]
    assert [manifest.version for manifest in plan.resolved_manifests] == ["2.0.0"]


def test_resolver_includes_template_references_in_graph() -> None:
    template = Template(name="hardware-build-inputs")
    source = Manifest(name="source", artifacts=(Artifact(id="rtl", path=Path("rtl/filter.sv"), role="hdl-source"),))
    project = Manifest(
        name="project",
        references=(Reference(kind="template", target="hardware-build-inputs"), Reference(kind="manifest", target="source")),
    )
    registry = ArtifactRegistry.from_manifests((source,))
    registry.register_template(template, source="explicit:template")

    plan = resolve_manifest(project, registry)

    assert [node.key for node in plan.nodes] == ["project", "template:hardware-build-inputs", "source"]
    assert [node.kind for node in plan.nodes] == ["manifest", "template", "manifest"]
    assert [(edge.from_key, edge.to_key, edge.reference.kind) for edge in plan.edges] == [
        ("project", "template:hardware-build-inputs", "template"),
        ("project", "source", "manifest"),
    ]
    assert plan.resolved_templates == (template,)


def test_resolver_follows_template_to_template_references() -> None:
    base_template = Template(name="base-inputs")
    project_template = Template(name="project-inputs", references=(Reference(kind="template", target="base-inputs"),))
    project = Manifest(name="project", references=(Reference(kind="template", target="project-inputs"),))
    registry = ArtifactRegistry()
    registry.register_template(project_template)
    registry.register_template(base_template)

    plan = resolve_manifest(project, registry)

    assert [node.key for node in plan.nodes] == ["project", "template:project-inputs", "template:base-inputs"]
    assert [(edge.from_key, edge.to_key, edge.reference.kind) for edge in plan.edges] == [
        ("project", "template:project-inputs", "template"),
        ("template:project-inputs", "template:base-inputs", "template"),
    ]
    assert plan.resolved_templates == (project_template, base_template)


def test_resolver_reports_missing_ambiguous_and_cyclic_manifest_references() -> None:
    missing_project = Manifest(name="missing-project", references=(Reference(kind="manifest", target="missing"),))
    with pytest.raises(ResolutionError, match="missing-project -> missing"):
        resolve_manifest(missing_project, ArtifactRegistry())

    versioned_registry = ArtifactRegistry(allow_manifest_versions=True)
    versioned_registry.register_manifest(
        Manifest(name="source", version="1", artifacts=(Artifact(path=Path("v1.sv"), kind="source", role="hdl-source"),))
    )
    versioned_registry.register_manifest(
        Manifest(name="source", version="2", artifacts=(Artifact(path=Path("v2.sv"), kind="source", role="hdl-source"),))
    )
    with pytest.raises(ResolutionError, match="ambiguous manifest reference: project -> source"):
        resolve_manifest(Manifest(name="project", references=(Reference(kind="manifest", target="source"),)), versioned_registry)

    registry = ArtifactRegistry.from_manifests(
        (
            Manifest(name="a", references=(Reference(kind="manifest", target="b"),)),
            Manifest(name="b", references=(Reference(kind="manifest", target="a"),)),
        )
    )
    with pytest.raises(ResolutionError, match="cyclic manifest reference: a -> b -> a"):
        resolve_manifest(registry.get_manifest("a"), registry)
