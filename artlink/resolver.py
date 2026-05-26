from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from .artifact import Artifact, ArtlinkError, Capability, Reference, _ArtlinkModel, capability_from_value
from .manifest import Manifest
from .registry import ArtifactRegistry, ManifestRegistryEntry, RegistryError, TemplateRegistryEntry
from .template import Template

__all__ = (
    "ResolutionError",
    "ProviderConflictPolicy",
    "CapabilityProvider",
    "ResolutionIssue",
    "ResolutionNode",
    "ResolutionEdge",
    "ResolutionPlan",
    "resolve_manifest",
)

ProviderConflictPolicy = Literal["error", "warning", "ignore", "prefer-explicit"]
ManifestVersionPolicy = Literal["error", "highest"]
ResolutionSeverity = Literal["error", "warning", "info"]


class ResolutionError(ArtlinkError):
    """Raised when manifest references cannot be resolved into a graph."""


class CapabilityProvider(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    capability: Capability
    manifest_key: str
    artifact_id: str
    source: str = ""


class ResolutionIssue(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    severity: ResolutionSeverity
    message: str
    capability: Capability
    providers: tuple[CapabilityProvider, ...] = Field(default_factory=tuple)
    selected_provider: CapabilityProvider | None = None


class ResolutionNode(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    key: str
    kind: Literal["manifest", "template"] = "manifest"
    name: str
    version: str = ""
    source: str = "root"
    root: Path | None = None


class ResolutionEdge(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    from_key: str
    to_key: str
    reference: Reference


class ResolutionPlan(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    root_manifest: Manifest
    nodes: tuple[ResolutionNode, ...] = Field(default_factory=tuple)
    edges: tuple[ResolutionEdge, ...] = Field(default_factory=tuple)
    resolved_manifests: tuple[Manifest, ...] = Field(default_factory=tuple)
    resolved_templates: tuple[Template, ...] = Field(default_factory=tuple)
    issues: tuple[ResolutionIssue, ...] = Field(default_factory=tuple)
    provider_selections: tuple[CapabilityProvider, ...] = Field(default_factory=tuple)

    @property
    def resolved_artifacts(self) -> tuple[Artifact, ...]:
        return tuple(artifact for manifest in self.resolved_manifests for artifact in manifest.artifacts)


def resolve_manifest(
    manifest: Manifest,
    registry: ArtifactRegistry,
    *,
    provider_conflict_policy: ProviderConflictPolicy = "error",
    manifest_version_policy: ManifestVersionPolicy = "error",
) -> ResolutionPlan:
    if provider_conflict_policy not in ("error", "warning", "ignore", "prefer-explicit"):
        raise ResolutionError(f"unsupported provider conflict policy: {provider_conflict_policy}")
    if manifest_version_policy not in ("error", "highest"):
        raise ResolutionError(f"unsupported manifest version policy: {manifest_version_policy}")

    nodes: list[ResolutionNode] = []
    edges: list[ResolutionEdge] = []
    resolved_entries: list[ManifestRegistryEntry] = []
    resolved_template_entries: list[TemplateRegistryEntry] = []
    visited: set[str] = set()
    visited_templates: set[str] = set()

    def visit(current_manifest: Manifest, *, entry: ManifestRegistryEntry | None, active_path: tuple[str, ...]) -> None:
        current_key = _manifest_key(current_manifest)
        if current_key in active_path:
            raise ResolutionError(f"cyclic manifest reference: {' -> '.join((*active_path, current_key))}")
        if current_key in visited:
            return

        visited.add(current_key)
        nodes.append(_node_for_manifest(current_manifest, entry=entry))
        if entry is not None:
            resolved_entries.append(entry)

        next_path = (*active_path, current_key)
        for reference in current_manifest.references:
            if reference.kind == "template":
                resolved_template_entry = _resolve_template_reference(registry, reference, from_key=current_key)
                resolved_template_key = _template_key(resolved_template_entry.template)
                edges.append(ResolutionEdge(from_key=current_key, to_key=resolved_template_key, reference=reference))
                visit_template(resolved_template_entry, active_path=(current_key,))
                continue
            if reference.kind != "manifest":
                continue
            reference_label = _reference_key(reference)
            try:
                resolved_entry = _resolve_manifest_reference(registry, reference, manifest_version_policy=manifest_version_policy)
            except RegistryError as exc:
                message = str(exc)
                if "ambiguous manifest reference" in message:
                    raise ResolutionError(f"ambiguous manifest reference: {current_key} -> {reference_label}: {message}") from exc
                raise ResolutionError(f"unresolved manifest reference: {current_key} -> {reference_label}: {message}") from exc

            resolved_key = _manifest_key(resolved_entry.manifest)
            if resolved_key in next_path:
                raise ResolutionError(f"cyclic manifest reference: {' -> '.join((*next_path, resolved_key))}")
            edges.append(ResolutionEdge(from_key=current_key, to_key=resolved_key, reference=reference))
            visit(resolved_entry.manifest, entry=resolved_entry, active_path=next_path)

    def visit_template(entry: TemplateRegistryEntry, *, active_path: tuple[str, ...]) -> None:
        template = entry.template
        current_key = _template_key(template)
        if current_key in active_path:
            raise ResolutionError(f"cyclic template reference: {' -> '.join((*active_path, current_key))}")
        if current_key in visited_templates:
            return

        visited_templates.add(current_key)
        nodes.append(_node_for_template(template, entry=entry))
        resolved_template_entries.append(entry)

        next_path = (*active_path, current_key)
        for reference in template.references:
            if reference.kind != "template":
                continue
            resolved_entry = _resolve_template_reference(registry, reference, from_key=current_key)
            resolved_key = _template_key(resolved_entry.template)
            if resolved_key in next_path:
                raise ResolutionError(f"cyclic template reference: {' -> '.join((*next_path, resolved_key))}")
            edges.append(ResolutionEdge(from_key=current_key, to_key=resolved_key, reference=reference))
            visit_template(resolved_entry, active_path=next_path)

    visit(manifest, entry=None, active_path=())
    issues, provider_selections = _provider_conflict_diagnostics(resolved_entries, policy=provider_conflict_policy)
    if provider_conflict_policy == "error" and issues:
        raise ResolutionError("; ".join(issue.message for issue in issues))

    return ResolutionPlan(
        root_manifest=manifest,
        nodes=tuple(nodes),
        edges=tuple(edges),
        resolved_manifests=tuple(entry.manifest for entry in resolved_entries),
        resolved_templates=tuple(entry.template for entry in resolved_template_entries),
        issues=issues,
        provider_selections=provider_selections,
    )


def _node_for_manifest(manifest: Manifest, *, entry: ManifestRegistryEntry | None) -> ResolutionNode:
    return ResolutionNode(
        key=_manifest_key(manifest),
        kind="manifest",
        name=manifest.name,
        version=manifest.version,
        source="root" if entry is None else entry.source,
        root=None if entry is None else entry.root,
    )


def _node_for_template(template: Template, *, entry: TemplateRegistryEntry) -> ResolutionNode:
    return ResolutionNode(
        key=_template_key(template),
        kind="template",
        name=template.name,
        version=template.version,
        source=entry.source,
        root=entry.root,
    )


def _manifest_key(manifest: Manifest) -> str:
    if manifest.version:
        return f"{manifest.name}@{manifest.version}"
    return manifest.name


def _template_key(template: Template) -> str:
    if template.version:
        return f"template:{template.name}@{template.version}"
    return f"template:{template.name}"


def _reference_key(reference: Reference) -> str:
    if reference.version:
        return f"{reference.target}@{reference.version}"
    return reference.target


def _resolve_manifest_reference(
    registry: ArtifactRegistry,
    reference: Reference,
    *,
    manifest_version_policy: ManifestVersionPolicy,
) -> ManifestRegistryEntry:
    try:
        return registry.get_manifest_entry(reference.target, version=reference.version)
    except RegistryError as exc:
        if manifest_version_policy != "highest" or reference.version or "ambiguous manifest reference" not in str(exc):
            raise
        matching_entries = tuple(entry for entry in registry.manifests() if entry.manifest.name == reference.target)
        if not matching_entries:
            raise
        return max(matching_entries, key=lambda entry: _version_sort_key(entry.manifest.version))


def _resolve_template_reference(registry: ArtifactRegistry, reference: Reference, *, from_key: str) -> TemplateRegistryEntry:
    reference_label = _reference_key(reference)
    try:
        return registry.get_template_entry(reference.target, version=reference.version)
    except RegistryError as exc:
        message = str(exc)
        if "ambiguous template reference" in message:
            raise ResolutionError(f"ambiguous template reference: {from_key} -> {reference_label}: {message}") from exc
        raise ResolutionError(f"unresolved template reference: {from_key} -> {reference_label}: {message}") from exc


def _provider_conflict_diagnostics(
    entries: list[ManifestRegistryEntry], *, policy: ProviderConflictPolicy
) -> tuple[tuple[ResolutionIssue, ...], tuple[CapabilityProvider, ...]]:
    if policy == "ignore":
        return (), ()
    severity: ResolutionSeverity = "info" if policy == "prefer-explicit" else policy
    selected_providers: list[CapabilityProvider] = []
    providers_by_key: dict[str, list[CapabilityProvider]] = {}
    for entry in entries:
        manifest_key = _manifest_key(entry.manifest)
        for artifact in entry.manifest.artifacts:
            for capability_value in artifact.provides:
                capability = capability_from_value(capability_value)
                providers_by_key.setdefault(capability.key, []).append(
                    CapabilityProvider(
                        capability=capability,
                        manifest_key=manifest_key,
                        artifact_id=artifact.display_id,
                        source=entry.source,
                    )
                )

    issues: list[ResolutionIssue] = []
    for capability_key, providers in sorted(providers_by_key.items()):
        if len(providers) < 2:
            continue
        selected_provider = _select_provider(providers, policy=policy)
        if selected_provider is not None:
            selected_providers.append(selected_provider)
        provider_text = ", ".join(f"{provider.manifest_key}/{provider.artifact_id}" for provider in providers)
        selection_text = "" if selected_provider is None else f"; selected {selected_provider.manifest_key}/{selected_provider.artifact_id}"
        issues.append(
            ResolutionIssue(
                kind="duplicate-provider",
                severity=severity,
                message=f"duplicate provider for capability {capability_key}: {provider_text}{selection_text}",
                capability=providers[0].capability,
                providers=tuple(providers),
                selected_provider=selected_provider,
            )
        )
    return tuple(issues), tuple(selected_providers)


def _select_provider(providers: list[CapabilityProvider], *, policy: ProviderConflictPolicy) -> CapabilityProvider | None:
    if policy != "prefer-explicit":
        return None
    explicit_providers = tuple(provider for provider in providers if provider.source.startswith("explicit"))
    if explicit_providers:
        return explicit_providers[0]
    return providers[0]


def _version_sort_key(version: str) -> tuple[tuple[int, int | str], ...]:
    if not version:
        return ()
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in re.split(r"([0-9]+)", version) if part)
