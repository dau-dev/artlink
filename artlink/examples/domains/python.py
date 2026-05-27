from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from ...artifact import Artifact, Capability, Reference, _ArtlinkModel
from ...domains.common import (
    ToolRequirement,
    artifact_id,
    first_path_for_role,
    matching_paths,
    path_artifacts,
    paths_for_role,
    resolved_artifact_locations,
    tool_artifact,
    tools_from_artifacts,
)
from ...manifest import Manifest
from ...materialize import MaterializationPlan, PathMaterializationMethod, build_materialization_plan, execute_materialization_plan
from ...registry import ArtifactRegistry
from ...resolver import ResolutionPlan

__all__ = (
    "ToolRequirement",
    "PythonPackageCollection",
    "PythonPackageScheme",
)


class PythonPackageCollection(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    package_name: str = ""
    version: str = ""
    project_file: Path | None = None
    package_sources: tuple[Path, ...] = Field(default_factory=tuple)
    test_sources: tuple[Path, ...] = Field(default_factory=tuple)
    metadata_files: tuple[Path, ...] = Field(default_factory=tuple)
    wheels: tuple[Path, ...] = Field(default_factory=tuple)
    source_distributions: tuple[Path, ...] = Field(default_factory=tuple)
    tools: dict[str, ToolRequirement] = Field(default_factory=dict)


class PythonPackageScheme(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    project_file_globs: tuple[str, ...] = ("pyproject.toml",)
    package_source_globs: tuple[str, ...] = ("src/**/*.py", "*.py")
    test_source_globs: tuple[str, ...] = ("tests/test_*.py", "tests/**/*_test.py")
    metadata_file_globs: tuple[str, ...] = ("README*", "LICENSE*", "CHANGELOG*", "docs/**/*.md")
    distribution_globs: tuple[str, ...] = ("dist/*.whl", "dist/*.tar.gz", "dist/*.zip")
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
        package_metadata = _project_metadata(project_root)
        manifest_metadata = {"profile": "python-package", **package_metadata, **dict(metadata or {})}
        artifacts = (
            *path_artifacts(
                project_root,
                self.project_file_globs,
                role="python-project",
                kind="metadata",
                metadata={"scheme": "python-package"},
                provides=lambda _path, _relative_path: _project_capabilities(package_metadata),
            ),
            *path_artifacts(
                project_root, self.package_source_globs, role="python-source", kind="source", language="python", metadata={"scheme": "python-package"}
            ),
            *path_artifacts(
                project_root, self.test_source_globs, role="python-test", kind="source", language="python", metadata={"scheme": "python-package"}
            ),
            *path_artifacts(project_root, self.metadata_file_globs, role="python-metadata", kind="metadata", metadata={"scheme": "python-package"}),
            *_distribution_artifacts(project_root, self.distribution_globs, package_metadata=package_metadata),
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
    ) -> PythonPackageCollection:
        materialization = build_materialization_plan(resolution, registry, target_dir=target_dir, path_method=path_method)
        execute_materialization_plan(materialization)
        return self.collect(resolution, registry, materialization_plan=materialization)

    def collect(
        self,
        resolution: ResolutionPlan,
        registry: ArtifactRegistry,
        *,
        materialization_plan: MaterializationPlan | None = None,
    ) -> PythonPackageCollection:
        artifacts = tuple(resolved_artifact_locations(resolution, registry, materialization_plan=materialization_plan))
        metadata = _resolved_metadata(resolution, "python-package")
        distributions = paths_for_role(artifacts, "python-distribution")
        return PythonPackageCollection(
            package_name=str(metadata.get("package_name", "")),
            version=str(metadata.get("version", "")),
            project_file=first_path_for_role(artifacts, "python-project"),
            package_sources=paths_for_role(artifacts, "python-source"),
            test_sources=paths_for_role(artifacts, "python-test"),
            metadata_files=paths_for_role(artifacts, "python-metadata"),
            wheels=tuple(path for path in distributions if path.suffix == ".whl"),
            source_distributions=tuple(path for path in distributions if path.name.endswith((".tar.gz", ".zip"))),
            tools=tools_from_artifacts(artifacts),
        )


def _project_metadata(root: Path) -> dict[str, str]:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return {"package_name": "", "version": ""}
    raw = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = raw.get("project", {})
    return {"package_name": str(project.get("name", "")), "version": str(project.get("version", ""))}


def _project_capabilities(metadata: dict[str, str]) -> tuple[Capability, ...]:
    package_name = metadata.get("package_name", "")
    if not package_name:
        return ()
    return (Capability(kind="python-package", name=package_name),)


def _distribution_capabilities(path: Path, metadata: dict[str, str]) -> tuple[Capability, ...]:
    capabilities: list[Capability] = [Capability(kind="python-distribution", name=path.name)]
    package_name = metadata.get("package_name", "")
    if package_name:
        capabilities.append(Capability(kind="python-package", name=package_name))
    return tuple(capabilities)


def _distribution_artifacts(root: Path, globs: tuple[str, ...], *, package_metadata: dict[str, str]) -> tuple[Artifact, ...]:
    artifacts: list[Artifact] = []
    for path in matching_paths(root, globs):
        relative_path = path.relative_to(root)
        artifacts.append(
            Artifact(
                id=artifact_id("python-distribution", relative_path),
                path=relative_path,
                kind="package",
                role="python-distribution",
                format=_distribution_format(path),
                provides=_distribution_capabilities(path, package_metadata),
                metadata={"scheme": "python-package"},
            )
        )
    return tuple(artifacts)


def _distribution_format(path: Path) -> str:
    if path.suffix == ".whl":
        return "wheel"
    if path.name.endswith((".tar.gz", ".zip")):
        return "sdist"
    return path.suffix.removeprefix(".")


def _resolved_metadata(resolution: ResolutionPlan, profile: str) -> dict[str, Any]:
    for manifest in resolution.resolved_manifests:
        if manifest.metadata.get("profile") == profile:
            return manifest.metadata
    return {}
