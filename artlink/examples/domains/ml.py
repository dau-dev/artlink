from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from ...artifact import Capability, Reference, _ArtlinkModel
from ...domains.common import ToolRequirement, path_artifacts, paths_for_role, resolved_artifact_locations, tool_artifact, tools_from_artifacts
from ...manifest import Manifest
from ...materialize import MaterializationPlan, PathMaterializationMethod, build_materialization_plan, execute_materialization_plan
from ...registry import ArtifactRegistry
from ...resolver import ResolutionPlan

__all__ = (
    "ModelReleaseCollection",
    "ModelReleaseScheme",
    "ToolRequirement",
)


class ModelReleaseCollection(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    models: tuple[Path, ...] = Field(default_factory=tuple)
    inference_code: tuple[Path, ...] = Field(default_factory=tuple)
    schemas: tuple[Path, ...] = Field(default_factory=tuple)
    metrics: tuple[Path, ...] = Field(default_factory=tuple)
    configs: tuple[Path, ...] = Field(default_factory=tuple)
    environment_files: tuple[Path, ...] = Field(default_factory=tuple)
    tools: dict[str, ToolRequirement] = Field(default_factory=dict)


class ModelReleaseScheme(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    model_globs: tuple[str, ...] = ("models/**/*",)
    inference_code_globs: tuple[str, ...] = ("src/**/*.py", "inference/**/*.py")
    schema_globs: tuple[str, ...] = ("schemas/**/*.json",)
    metric_globs: tuple[str, ...] = ("metrics/**/*.json", "metrics/**/*.csv")
    config_globs: tuple[str, ...] = ("configs/**/*.yaml", "configs/**/*.yml", "configs/**/*.json")
    environment_globs: tuple[str, ...] = ("requirements*.txt", "environment*.yml", "environment*.yaml")
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
        manifest_metadata = {"profile": "model-release", **dict(metadata or {})}
        artifacts = (
            *path_artifacts(
                project_root,
                self.model_globs,
                role="model-file",
                kind="model",
                metadata={"scheme": "model-release"},
                provides=lambda path, _relative_path: (Capability(kind="model", name=path.stem),),
            ),
            *path_artifacts(
                project_root, self.inference_code_globs, role="inference-code", kind="source", language="python", metadata={"scheme": "model-release"}
            ),
            *path_artifacts(project_root, self.schema_globs, role="schema", kind="metadata", metadata={"scheme": "model-release"}),
            *path_artifacts(project_root, self.metric_globs, role="model-metric", kind="metadata", metadata={"scheme": "model-release"}),
            *path_artifacts(project_root, self.config_globs, role="model-config", kind="metadata", metadata={"scheme": "model-release"}),
            *path_artifacts(project_root, self.environment_globs, role="environment", kind="metadata", metadata={"scheme": "model-release"}),
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
    ) -> ModelReleaseCollection:
        materialization = build_materialization_plan(resolution, registry, target_dir=target_dir, path_method=path_method)
        execute_materialization_plan(materialization)
        return self.collect(resolution, registry, materialization_plan=materialization)

    def collect(
        self,
        resolution: ResolutionPlan,
        registry: ArtifactRegistry,
        *,
        materialization_plan: MaterializationPlan | None = None,
    ) -> ModelReleaseCollection:
        artifacts = tuple(resolved_artifact_locations(resolution, registry, materialization_plan=materialization_plan))
        return ModelReleaseCollection(
            models=paths_for_role(artifacts, "model-file"),
            inference_code=paths_for_role(artifacts, "inference-code"),
            schemas=paths_for_role(artifacts, "schema"),
            metrics=paths_for_role(artifacts, "model-metric"),
            configs=paths_for_role(artifacts, "model-config"),
            environment_files=paths_for_role(artifacts, "environment"),
            tools=tools_from_artifacts(artifacts),
        )
