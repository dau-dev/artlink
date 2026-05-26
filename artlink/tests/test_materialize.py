from pathlib import Path
from zipfile import ZipFile

from artlink import Artifact, ArtifactRegistry, Manifest, Reference, build_materialization_plan, execute_materialization_plan, resolve_manifest


def test_materialization_plan_records_copy_steps_without_touching_files(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    source_path = package_dir / "rtl" / "filter.sv"
    source_path.parent.mkdir()
    source_path.write_text("module filter; endmodule\n", encoding="utf-8")
    source_manifest = Manifest(name="source", artifacts=(Artifact(id="filter", path=Path("rtl/filter.sv"), role="hdl-source"),))
    project = Manifest(name="project", references=(Reference(kind="manifest", target="source"),))
    registry = ArtifactRegistry.from_manifests((source_manifest,), root=package_dir)
    target_dir = tmp_path / "materialized"

    resolution = resolve_manifest(project, registry)
    plan = build_materialization_plan(resolution, registry, target_dir=target_dir)

    assert not target_dir.exists()
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.method == "copy"
    assert action.manifest_key == "source"
    assert action.artifact_id == "filter"
    assert action.source == source_path.as_posix()
    assert action.destination == target_dir / "rtl" / "filter.sv"


def test_materialization_plan_keeps_remote_artifacts_as_references(tmp_path: Path) -> None:
    driver_manifest = Manifest(name="driver", artifacts=(Artifact(uri="https://example.invalid/driver.whl", role="driver"),))
    project = Manifest(name="project", references=(Reference(kind="manifest", target="driver"),))
    registry = ArtifactRegistry.from_manifests((driver_manifest,))

    resolution = resolve_manifest(project, registry)
    plan = build_materialization_plan(resolution, registry, target_dir=tmp_path / "materialized")

    assert [(action.method, action.source, action.destination) for action in plan.actions] == [
        ("reference", "https://example.invalid/driver.whl", None)
    ]

    result = execute_materialization_plan(plan)

    assert result.actions == plan.actions
    assert not (tmp_path / "materialized").exists()


def test_materialization_executor_copies_and_symlinks_files(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    source_path = package_dir / "rtl" / "filter.sv"
    source_path.parent.mkdir(parents=True)
    source_path.write_text("module filter; endmodule\n", encoding="utf-8")
    source_manifest = Manifest(name="source", artifacts=(Artifact(id="filter", path=Path("rtl/filter.sv"), role="hdl-source"),))
    project = Manifest(name="project", references=(Reference(kind="manifest", target="source"),))
    registry = ArtifactRegistry.from_manifests((source_manifest,), root=package_dir)
    resolution = resolve_manifest(project, registry)

    copy_plan = build_materialization_plan(resolution, registry, target_dir=tmp_path / "copied")
    symlink_plan = build_materialization_plan(resolution, registry, target_dir=tmp_path / "linked", path_method="symlink")

    execute_materialization_plan(copy_plan)
    execute_materialization_plan(symlink_plan)

    assert (tmp_path / "copied" / "rtl" / "filter.sv").read_text(encoding="utf-8") == "module filter; endmodule\n"
    assert (tmp_path / "linked" / "rtl" / "filter.sv").is_symlink()


def test_materialization_executor_extracts_archives(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    archive_path = package_dir / "payload.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("payload/data.txt", "payload\n")
    archive_manifest = Manifest(name="archive", artifacts=(Artifact(id="payload", path=Path("payload.zip"), role="data"),))
    project = Manifest(name="project", references=(Reference(kind="manifest", target="archive"),))
    registry = ArtifactRegistry.from_manifests((archive_manifest,), root=package_dir)

    resolution = resolve_manifest(project, registry)
    plan = build_materialization_plan(resolution, registry, target_dir=tmp_path / "extracted")

    assert plan.actions[0].method == "archive-extract"

    execute_materialization_plan(plan)

    assert (tmp_path / "extracted" / "payload" / "payload" / "data.txt").read_text(encoding="utf-8") == "payload\n"


def test_materialization_executor_copies_package_resources(tmp_path: Path, monkeypatch) -> None:
    package_dir = tmp_path / "resource_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "data.txt").write_text("resource\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    resource_manifest = Manifest(name="resources", artifacts=(Artifact(uri="package://resource_pkg/data.txt", role="data"),))
    project = Manifest(name="project", references=(Reference(kind="manifest", target="resources"),))
    registry = ArtifactRegistry.from_manifests((resource_manifest,))

    resolution = resolve_manifest(project, registry)
    plan = build_materialization_plan(resolution, registry, target_dir=tmp_path / "resources")

    assert plan.actions[0].method == "package-resource"

    execute_materialization_plan(plan)

    assert (tmp_path / "resources" / "data.txt").read_text(encoding="utf-8") == "resource\n"
