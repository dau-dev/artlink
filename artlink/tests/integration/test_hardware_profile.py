from pathlib import Path

from artlink import ArtifactRegistry, Manifest, Reference, build_materialization_plan, execute_materialization_plan, resolve_manifest
from artlink.domains.hdl import HardwareProjectScheme, ToolRequirement


def test_hardware_project_scheme_bundles_installs_and_collects_build_inputs(tmp_path: Path) -> None:
    _write(tmp_path / "rtl" / "top.sv", '`include "defs.svh"\nmodule top; endmodule\n')
    _write(tmp_path / "rtl" / "filter.sv", "module filter; endmodule\n")
    _write(tmp_path / "include" / "defs.svh", "`define WIDTH 8\n")
    _write(tmp_path / "tb" / "top_tb.sv", "module top_tb; endmodule\n")
    _write(tmp_path / "tests" / "test_top.py", "def test_top(): pass\n")
    _write(tmp_path / "verilator" / "top_tb.cpp", "int main() { return 0; }\n")
    _write(tmp_path / "constraints" / "demo.xdc", "set_property PACKAGE_PIN A1 [get_ports clk]\n")

    scheme = HardwareProjectScheme(
        design_source_globs=("rtl/*.sv",),
        include_globs=("include/*.svh",),
        systemverilog_testbench_globs=("tb/*.sv",),
        cocotb_test_globs=("tests/test_*.py",),
        verilator_source_globs=("verilator/*.cpp",),
        constraint_globs=("constraints/*.xdc",),
        tools=(
            ToolRequirement(name="vivado"),
            ToolRequirement(name="verilator"),
            ToolRequirement(name="python", packages=("cocotb", "pytest")),
        ),
    )

    bundle = scheme.bundle(root=tmp_path, name="demo-hardware")
    registry = ArtifactRegistry.from_manifests((bundle,), root=tmp_path)
    request = Manifest(name="demo-build", references=(Reference(kind="manifest", target="demo-hardware"),))
    resolution = resolve_manifest(request, registry, provider_conflict_policy="prefer-explicit")
    materialization = build_materialization_plan(resolution, registry, target_dir=tmp_path / "installed")

    execute_materialization_plan(materialization)
    collection = scheme.collect(resolution, registry, materialization_plan=materialization)

    assert [artifact.role for artifact in bundle.artifacts] == [
        "hdl-source",
        "hdl-source",
        "hdl-include",
        "systemverilog-testbench",
        "cocotb-test",
        "verilator-testbench",
        "constraints",
        "tool",
        "tool",
        "tool",
    ]
    assert _relative_paths(collection.design_sources, tmp_path / "installed") == ["rtl/filter.sv", "rtl/top.sv"]
    assert _relative_paths(collection.include_files, tmp_path / "installed") == ["include/defs.svh"]
    assert _relative_paths(collection.include_dirs, tmp_path / "installed") == ["include"]
    assert _relative_paths(collection.systemverilog_testbenches, tmp_path / "installed") == ["tb/top_tb.sv"]
    assert _relative_paths(collection.cocotb_tests, tmp_path / "installed") == ["tests/test_top.py"]
    assert _relative_paths(collection.verilator_sources, tmp_path / "installed") == ["verilator/top_tb.cpp"]
    assert _relative_paths(collection.constraints, tmp_path / "installed") == ["constraints/demo.xdc"]
    assert collection.tools["vivado"].version == "any"
    assert collection.tools["verilator"].version == "any"
    assert collection.tools["python"].packages == ("cocotb", "pytest")
    assert all(path.exists() for path in collection.design_sources + collection.include_files + collection.constraints)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _relative_paths(paths: tuple[Path, ...], root: Path) -> list[str]:
    return [path.relative_to(root).as_posix() for path in paths]
