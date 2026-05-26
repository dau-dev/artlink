from pathlib import Path

from artlink import (
    Artifact,
    ArtifactRegistry,
    ArtifactSelector,
    Cardinality,
    Manifest,
    Reference,
    Template,
    TemplateRule,
    load_manifest,
    load_registry,
    load_template,
    resolve_manifest,
    validate_artifact_files,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_hardware_manifest_workflow_end_to_end(tmp_path: Path) -> None:
    (tmp_path / "rtl").mkdir()
    (tmp_path / "constraints").mkdir()
    (tmp_path / "python").mkdir()
    (tmp_path / "build").mkdir()
    (tmp_path / "rtl" / "filter.sv").write_text("module filter; endmodule\n", encoding="utf-8")
    (tmp_path / "constraints" / "demo.xdc").write_text("set_property PACKAGE_PIN A1 [get_ports clk]\n", encoding="utf-8")
    (tmp_path / "python" / "driver.py").write_text("class Driver: pass\n", encoding="utf-8")
    (tmp_path / "build" / "filter.bit").write_bytes(b"ARTLINK")

    source_manifest = Manifest(
        name="source-package",
        artifacts=(
            Artifact(id="filter-rtl", path=Path("rtl/filter.sv"), kind="source", role="hdl-source", language="systemverilog", provides=("filter",)),
        ),
    )
    constraints_manifest = Manifest(
        name="constraints-package",
        artifacts=(Artifact(id="demo-constraints", path=Path("constraints/demo.xdc"), kind="metadata", role="constraints", format="xdc"),),
    )
    driver_manifest = Manifest(
        name="driver-package",
        artifacts=(Artifact(id="python-driver", path=Path("python/driver.py"), kind="source", role="driver", language="python"),),
    )
    for manifest in (source_manifest, constraints_manifest, driver_manifest):
        (tmp_path / f"{manifest.name}.yaml").write_text(manifest.to_yaml_text(), encoding="utf-8")

    project_inputs = Manifest.compose(
        name="project-inputs",
        intent="input",
        manifests=tuple(load_manifest(tmp_path / name) for name in ("source-package.yaml", "constraints-package.yaml", "driver-package.yaml")),
    )
    input_template = Template(
        name="hardware-build-inputs",
        rules=(
            TemplateRule(
                name="requires-filter-module",
                selector=ArtifactSelector(kind="source", role="hdl-source", provides="filter"),
                cardinality=Cardinality(min=1, max=1),
            ),
            TemplateRule(name="requires-constraints", selector=ArtifactSelector(role="constraints"), cardinality=Cardinality(min=1)),
            TemplateRule(name="requires-driver", selector=ArtifactSelector(role="driver"), cardinality=Cardinality(min=1)),
        ),
    )

    validate_artifact_files(project_inputs, root=tmp_path)
    input_result = input_template.validate_manifest(project_inputs)

    assert input_result.is_valid
    assert project_inputs.metadata["composed_from"] == ["source-package", "constraints-package", "driver-package"]

    output_manifest = Manifest(
        name="filter-bitstream-output",
        intent="output",
        artifacts=(Artifact(id="filter-bitstream", path=Path("build/filter.bit"), kind="binary", role="bitstream", format="xilinx-bitstream"),),
        metadata={"inputs": project_inputs.name},
    )
    output_template = Template(
        name="bitstream-output",
        rules=(
            TemplateRule(
                name="requires-one-bitstream", selector=ArtifactSelector(kind="binary", role="bitstream"), cardinality=Cardinality(min=1, max=1)
            ),
        ),
    )

    validate_artifact_files(output_manifest, root=tmp_path)
    output_result = output_template.validate_manifest(output_manifest)

    assert output_result.is_valid
    assert "role: bitstream" in output_manifest.to_yaml_text()


def test_registry_discovers_build_inputs_from_mixed_sources(tmp_path: Path) -> None:
    install_dir = tmp_path / "install" / "share" / "artlink" / "manifests"
    install_dir.mkdir(parents=True)
    source_manifest = Manifest(
        name="installed-source-package",
        artifacts=(
            Artifact(id="filter-rtl", path=Path("rtl/filter.sv"), kind="source", role="hdl-source", language="systemverilog", provides=("filter",)),
        ),
    )
    driver_manifest = Manifest(
        name="entry-point-driver-package",
        artifacts=(Artifact(id="driver", uri="https://example.invalid/driver.whl", kind="binary", role="driver"),),
    )
    constraints_manifest = Manifest(
        name="explicit-constraints-package",
        artifacts=(Artifact(id="constraints", path=Path("constraints/demo.xdc"), kind="metadata", role="constraints", format="xdc"),),
    )
    (install_dir / "source.yaml").write_text(source_manifest.to_yaml_text(), encoding="utf-8")

    registry = ArtifactRegistry.from_install_path(tmp_path / "install")
    registry.discover_entry_points(entry_points=(FakeEntryPoint("driver", lambda: driver_manifest),))
    registry.register_manifest(constraints_manifest, source="explicit")

    project_inputs = Manifest.compose(
        name="registry-project-inputs",
        intent="input",
        manifests=tuple(entry.manifest for entry in registry.manifests()),
    )
    input_template = Template(
        name="hardware-build-inputs",
        rules=(
            TemplateRule(
                name="requires-filter", selector=ArtifactSelector(role="hdl-source", provides="filter"), cardinality=Cardinality(min=1, max=1)
            ),
            TemplateRule(name="requires-constraints", selector=ArtifactSelector(role="constraints"), cardinality=Cardinality(min=1)),
            TemplateRule(name="requires-driver", selector=ArtifactSelector(role="driver"), cardinality=Cardinality(min=1)),
        ),
    )

    result = input_template.validate_manifest(project_inputs)

    assert result.is_valid
    assert sorted(project_inputs.metadata["composed_from"]) == [
        "entry-point-driver-package",
        "explicit-constraints-package",
        "installed-source-package",
    ]


def test_registry_resolves_versioned_hardware_manifest_reference(tmp_path: Path) -> None:
    install_root = tmp_path / "install"
    v1_dir = install_root / "share" / "artlink" / "hdl-filter" / "1.0.0"
    v2_dir = install_root / "share" / "artlink" / "hdl-filter" / "2.0.0"
    v1_dir.mkdir(parents=True)
    v2_dir.mkdir(parents=True)
    (v1_dir / "filter.sv").write_text("module filter_v1; endmodule\n", encoding="utf-8")
    (v2_dir / "filter.sv").write_text("module filter_v2; endmodule\n", encoding="utf-8")
    v1_manifest = Manifest(
        name="hdl-filter",
        version="1.0.0",
        artifacts=(Artifact(id="filter-v1", path=Path("filter.sv"), kind="source", role="hdl-source"),),
    )
    v2_manifest = Manifest(
        name="hdl-filter",
        version="2.0.0",
        artifacts=(Artifact(id="filter-v2", path=Path("filter.sv"), kind="source", role="hdl-source"),),
    )
    (v1_dir / "manifest.yaml").write_text(v1_manifest.to_yaml_text(), encoding="utf-8")
    (v2_dir / "manifest.yaml").write_text(v2_manifest.to_yaml_text(), encoding="utf-8")
    project_manifest = Manifest(
        name="hardware-project",
        artifacts=(Artifact(path=Path("project.yaml"), kind="metadata", role="project"),),
        references=(Reference(kind="manifest", target="hdl-filter", version="2.0.0"),),
    )

    registry = ArtifactRegistry.from_install_path(install_root, allow_manifest_versions=True)
    resolved_entry = registry.resolve_manifest_references(project_manifest)[0]

    assert resolved_entry.manifest == v2_manifest
    assert registry.artifact_file_path(registry.find_artifacts(role="hdl-source")[1]) == v2_dir / "filter.sv"


def test_yaml_round_trip_resolution_workflow_end_to_end(tmp_path: Path) -> None:
    registry = load_registry(FIXTURES / "registry" / "hardware-registry.yaml")
    loaded_project = load_manifest(FIXTURES / "projects" / "hardware-project.yaml")
    loaded_template = load_template(FIXTURES / "templates" / "hardware-build-inputs.yaml")
    plan = resolve_manifest(loaded_project, registry)
    resolved_inputs = Manifest.compose(name="resolved-hardware-inputs", intent="input", manifests=tuple(plan.resolved_manifests))
    resolved_path = tmp_path / "resolved-inputs.yaml"
    resolved_path.write_text(resolved_inputs.to_yaml_text(), encoding="utf-8")

    assert [node.key for node in plan.nodes] == ["hardware-project", "hdl-filter@2.0.0", "demo-board@1.0.0", "python-driver@0.1.0"]
    assert loaded_template.validate_manifest(resolved_inputs).is_valid
    assert all(registry.artifact_file_path(entry).exists() for entry in registry.artifacts() if entry.artifact.path is not None)
    assert load_manifest(resolved_path) == resolved_inputs
    assert "_target_" not in resolved_path.read_text(encoding="utf-8")


class FakeEntryPoint:
    def __init__(self, name: str, value) -> None:
        self.name = name
        self.group = "artlink.manifests"
        self._value = value

    def load(self):
        return self._value
