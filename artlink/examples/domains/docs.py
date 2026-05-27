from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from ...artifact import Reference, _ArtlinkModel
from ...domains.common import ToolRequirement, path_artifacts, paths_for_role, resolved_artifact_locations, tool_artifact, tools_from_artifacts
from ...manifest import Manifest
from ...materialize import MaterializationPlan, PathMaterializationMethod, build_materialization_plan, execute_materialization_plan
from ...registry import ArtifactRegistry
from ...resolver import ResolutionPlan

__all__ = (
    "ToolRequirement",
    "DocumentationSiteCollection",
    "DocumentationSiteScheme",
)


class DocumentationSiteCollection(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    configs: tuple[Path, ...] = Field(default_factory=tuple)
    documents: tuple[Path, ...] = Field(default_factory=tuple)
    assets: tuple[Path, ...] = Field(default_factory=tuple)
    built_site: tuple[Path, ...] = Field(default_factory=tuple)
    tools: dict[str, ToolRequirement] = Field(default_factory=dict)


class DocumentationSiteScheme(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    config_globs: tuple[str, ...] = ("mkdocs.yml", "mkdocs.yaml", "docs/conf.py")
    document_globs: tuple[str, ...] = ("docs/**/*.md", "README.md")
    asset_globs: tuple[str, ...] = ("docs/assets/**/*", "docs/_static/**/*")
    built_site_globs: tuple[str, ...] = ("site/**/*", "public/**/*")
    tools: tuple[ToolRequirement, ...] = Field(default_factory=tuple)

    def bundle(
        self,
        *,
        root: Path,
        name: str,
        version: str = "",
        references: tuple[Reference, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> Manifest:
        project_root = Path(root)
        manifest_metadata = {"profile": "documentation-site", **dict(metadata or {})}
        artifacts = (
            *path_artifacts(project_root, self.config_globs, role="docs-config", kind="metadata", metadata={"scheme": "documentation-site"}),
            *path_artifacts(
                project_root, self.document_globs, role="docs-source", kind="source", language="markdown", metadata={"scheme": "documentation-site"}
            ),
            *path_artifacts(project_root, self.asset_globs, role="docs-asset", kind="asset", metadata={"scheme": "documentation-site"}),
            *path_artifacts(project_root, self.built_site_globs, role="docs-built", kind="site", metadata={"scheme": "documentation-site"}),
            *(tool_artifact(tool) for tool in self.tools),
        )
        return Manifest(name=name, version=version, intent="input", artifacts=artifacts, references=references, metadata=manifest_metadata)

    def install_and_collect(
        self,
        resolution: ResolutionPlan,
        registry: ArtifactRegistry,
        *,
        target_dir: Path,
        path_method: PathMaterializationMethod = "copy",
    ) -> DocumentationSiteCollection:
        materialization = build_materialization_plan(resolution, registry, target_dir=target_dir, path_method=path_method)
        execute_materialization_plan(materialization)
        return self.collect(resolution, registry, materialization_plan=materialization)

    def collect(
        self,
        resolution: ResolutionPlan,
        registry: ArtifactRegistry,
        *,
        materialization_plan: MaterializationPlan | None = None,
    ) -> DocumentationSiteCollection:
        artifacts = tuple(resolved_artifact_locations(resolution, registry, materialization_plan=materialization_plan))
        return DocumentationSiteCollection(
            configs=paths_for_role(artifacts, "docs-config"),
            documents=paths_for_role(artifacts, "docs-source"),
            assets=paths_for_role(artifacts, "docs-asset"),
            built_site=paths_for_role(artifacts, "docs-built"),
            tools=tools_from_artifacts(artifacts),
        )
