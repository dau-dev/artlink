from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from ...artifact import Capability, Reference, _ArtlinkModel
from ...domains.common import (
    ToolRequirement,
    path_artifacts,
    paths_for_role,
    resolved_artifact_locations,
    tool_artifact,
    tools_from_artifacts,
    unique_parent_dirs,
)
from ...manifest import Manifest
from ...materialize import MaterializationPlan, PathMaterializationMethod, build_materialization_plan, execute_materialization_plan
from ...registry import ArtifactRegistry
from ...resolver import ResolutionPlan

__all__ = (
    "HardwareDesignCollection",
    "HardwareProjectScheme",
    "ToolRequirement",
)


class HardwareDesignCollection(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    design_sources: tuple[Path, ...] = Field(default_factory=tuple)
    include_files: tuple[Path, ...] = Field(default_factory=tuple)
    include_dirs: tuple[Path, ...] = Field(default_factory=tuple)
    systemverilog_testbenches: tuple[Path, ...] = Field(default_factory=tuple)
    cocotb_tests: tuple[Path, ...] = Field(default_factory=tuple)
    verilator_sources: tuple[Path, ...] = Field(default_factory=tuple)
    constraints: tuple[Path, ...] = Field(default_factory=tuple)
    tools: dict[str, ToolRequirement] = Field(default_factory=dict)

    @property
    def synthesis_sources(self) -> tuple[Path, ...]:
        return self.design_sources


class HardwareProjectScheme(_ArtlinkModel):
    model_config = ConfigDict(frozen=True)

    design_source_globs: tuple[str, ...] = ("rtl/**/*.sv",)
    include_globs: tuple[str, ...] = ("rtl/**/*.svh", "include/**/*.svh")
    systemverilog_testbench_globs: tuple[str, ...] = ("tb/**/*.sv",)
    cocotb_test_globs: tuple[str, ...] = ("tests/test_*.py",)
    verilator_source_globs: tuple[str, ...] = ("verilator/**/*.cpp",)
    constraint_globs: tuple[str, ...] = ("constraints/**/*.xdc",)
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
        artifacts = (
            *path_artifacts(
                project_root,
                self.design_source_globs,
                role="hdl-source",
                kind="source",
                language="systemverilog",
                metadata={"scheme": "hardware-project"},
                provides=lambda path, _relative_path: (Capability(kind="hdl-module", name=path.stem),),
            ),
            *path_artifacts(
                project_root, self.include_globs, role="hdl-include", kind="source", language="systemverilog", metadata={"scheme": "hardware-project"}
            ),
            *path_artifacts(
                project_root,
                self.systemverilog_testbench_globs,
                role="systemverilog-testbench",
                kind="source",
                language="systemverilog",
                metadata={"scheme": "hardware-project"},
            ),
            *path_artifacts(
                project_root, self.cocotb_test_globs, role="cocotb-test", kind="source", language="python", metadata={"scheme": "hardware-project"}
            ),
            *path_artifacts(
                project_root,
                self.verilator_source_globs,
                role="verilator-testbench",
                kind="source",
                language="cpp",
                metadata={"scheme": "hardware-project"},
            ),
            *path_artifacts(project_root, self.constraint_globs, role="constraints", kind="metadata", metadata={"scheme": "hardware-project"}),
            *(tool_artifact(tool) for tool in self.tools),
        )
        return Manifest(name=name, version=version, intent="input", artifacts=artifacts, references=references, metadata=dict(metadata or {}))

    def install_and_collect(
        self,
        resolution: ResolutionPlan,
        registry: ArtifactRegistry,
        *,
        target_dir: Path,
        path_method: PathMaterializationMethod = "copy",
    ) -> HardwareDesignCollection:
        materialization = build_materialization_plan(resolution, registry, target_dir=target_dir, path_method=path_method)
        execute_materialization_plan(materialization)
        return self.collect(resolution, registry, materialization_plan=materialization)

    def collect(
        self,
        resolution: ResolutionPlan,
        registry: ArtifactRegistry,
        *,
        materialization_plan: MaterializationPlan | None = None,
    ) -> HardwareDesignCollection:
        artifacts = tuple(resolved_artifact_locations(resolution, registry, materialization_plan=materialization_plan))
        include_files = paths_for_role(artifacts, "hdl-include")
        return HardwareDesignCollection(
            design_sources=paths_for_role(artifacts, "hdl-source"),
            include_files=include_files,
            include_dirs=unique_parent_dirs(include_files),
            systemverilog_testbenches=paths_for_role(artifacts, "systemverilog-testbench"),
            cocotb_tests=paths_for_role(artifacts, "cocotb-test"),
            verilator_sources=paths_for_role(artifacts, "verilator-testbench"),
            constraints=paths_for_role(artifacts, "constraints"),
            tools=tools_from_artifacts(artifacts),
        )
