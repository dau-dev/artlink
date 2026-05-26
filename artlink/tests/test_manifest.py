from pathlib import Path

import pytest

from artlink import (
    ARTLINK_MANIFEST_SCHEMA,
    Artifact,
    Capability,
    Digest,
    Manifest,
    ManifestError,
    artifact_inference_issues,
    load_manifest,
    validate_artifact_files,
)


def test_manifest_round_trips_artifacts_to_json_and_yaml(tmp_path: Path) -> None:
    manifest = Manifest(
        name="portable-hdl-inputs",
        intent="input",
        artifacts=(
            Artifact(
                id="filter-rtl",
                path=Path("rtl/filter.sv"),
                kind="source",
                role="hdl-source",
                language="systemverilog",
                provides=("filter",),
                digest=Digest(algorithm="sha256", value="a" * 64),
            ),
            Artifact(
                id="board-constraints",
                path=Path("constraints/board.xdc"),
                kind="metadata",
                role="constraints",
                format="xdc",
                media_type="text/plain",
            ),
        ),
        metadata={"target": "demo-board"},
    )

    manifest_path = tmp_path / "artlink.yaml"
    manifest_path.write_text(manifest.to_yaml_text(), encoding="utf-8")

    loaded = load_manifest(manifest_path)

    assert loaded == manifest
    assert loaded.model_dump(mode="json") == {
        "schema": ARTLINK_MANIFEST_SCHEMA,
        "name": "portable-hdl-inputs",
        "version": "",
        "intent": "input",
        "artifacts": [
            {
                "id": "filter-rtl",
                "name": "",
                "path": "rtl/filter.sv",
                "uri": "",
                "kind": "source",
                "role": "hdl-source",
                "format": "sv",
                "media_type": "",
                "language": "systemverilog",
                "provides": ["filter"],
                "requires": [],
                "digest": {"algorithm": "sha256", "value": "a" * 64},
                "metadata": {},
            },
            {
                "id": "board-constraints",
                "name": "",
                "path": "constraints/board.xdc",
                "uri": "",
                "kind": "metadata",
                "role": "constraints",
                "format": "xdc",
                "media_type": "text/plain",
                "language": "",
                "provides": [],
                "requires": [],
                "digest": None,
                "metadata": {},
            },
        ],
        "references": [],
        "metadata": {"target": "demo-board"},
    }
    assert "schema: artlink.manifest/v0" in manifest.to_yaml_text()


def test_artifact_infers_generic_format_without_overriding_user_values() -> None:
    wheel = Artifact(uri="https://example.invalid/package-1.0.0-py3-none-any.whl", role="driver")
    source = Artifact(path=Path("filter.sv"), role="hdl-source")
    explicit = Artifact(path=Path("payload.custom"), role="payload", format="opaque")

    assert wheel.kind == ""
    assert wheel.format == "wheel"
    assert source.format == "sv"
    assert explicit.format == "opaque"


def test_artifact_reports_explicit_values_that_conflict_with_generic_inference() -> None:
    artifact = Artifact(path=Path("payload.txt"), role="docs", format="markdown", media_type="application/octet-stream")
    inferred = Artifact(path=Path("payload.txt"), role="docs")

    assert artifact.format == "markdown"
    assert artifact.media_type == "application/octet-stream"
    assert [(issue.field, issue.declared_value, issue.inferred_value) for issue in artifact.inference_issues] == [
        ("format", "markdown", "txt"),
        ("media_type", "application/octet-stream", "text/plain"),
    ]
    assert artifact_inference_issues(artifact) == artifact.inference_issues
    assert inferred.inference_issues == ()


def test_artifact_id_is_optional_and_location_identifies_artifacts() -> None:
    manifest = Manifest(
        name="compact-artifacts",
        artifacts=(
            Artifact(path=Path("payload.txt"), role="data"),
            Artifact(uri="https://example.invalid/driver.whl", role="driver"),
        ),
    )

    assert [artifact.id for artifact in manifest.artifacts] == ["", ""]
    assert [artifact.display_id for artifact in manifest.artifacts] == ["payload.txt", "https://example.invalid/driver.whl"]


def test_artifact_capabilities_accept_strings_and_typed_records() -> None:
    artifact = Artifact(
        path=Path("rtl/filter.sv"),
        role="hdl-source",
        provides=("filter", {"kind": "hdl-module", "name": "fir-filter"}),
        requires=(Capability(kind="tool", name="synthesizer"),),
    )

    assert artifact.provides == (Capability(name="filter"), Capability(kind="hdl-module", name="fir-filter"))
    assert artifact.requires == (Capability(kind="tool", name="synthesizer"),)
    assert Manifest(name="capability-package", artifacts=(artifact,)).model_dump(mode="json")["artifacts"][0]["provides"] == [
        "filter",
        {"kind": "hdl-module", "name": "fir-filter"},
    ]


def test_manifest_validates_paths_relative_to_manifest_file(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "filter.sv").write_text("module filter; endmodule\n", encoding="utf-8")
    manifest_path = package_dir / "manifest.yaml"
    manifest_path.write_text(
        """
schema: artlink.manifest/v0
name: local-package
artifacts:
  - path: filter.sv
    role: hdl-source
""".lstrip(),
        encoding="utf-8",
    )

    manifest = load_manifest(manifest_path, validate_paths=True)

    assert manifest.artifacts[0].path == Path("filter.sv")
    assert manifest.artifacts[0].format == "sv"


def test_manifest_rejects_duplicate_artifact_ids_and_locations() -> None:
    with pytest.raises(ManifestError, match="duplicate artifact id"):
        Manifest(
            name="bad-ids",
            artifacts=(
                Artifact(id="same", path=Path("rtl/a.sv"), kind="source", role="hdl-source"),
                Artifact(id="same", path=Path("rtl/b.sv"), kind="source", role="hdl-source"),
            ),
        )

    with pytest.raises(ManifestError, match="duplicate artifact location"):
        Manifest(
            name="bad-paths",
            artifacts=(
                Artifact(path=Path("rtl/a.sv"), kind="source", role="hdl-source"),
                Artifact(path=Path("rtl/a.sv"), kind="source", role="hdl-source"),
            ),
        )


def test_manifest_validates_concrete_artifact_paths(tmp_path: Path) -> None:
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "filter.sv").write_text("module filter; endmodule\n", encoding="utf-8")
    manifest = Manifest(
        name="concrete-inputs",
        artifacts=(
            Artifact(path=Path("rtl/filter.sv"), kind="source", role="hdl-source"),
            Artifact(path=Path("constraints/missing.xdc"), kind="metadata", role="constraints"),
            Artifact(uri="https://example.invalid/driver.whl", kind="binary", role="driver"),
        ),
    )

    with pytest.raises(ManifestError) as exc_info:
        validate_artifact_files(manifest, root=tmp_path)

    message = str(exc_info.value)
    assert "missing artifact path" in message
    assert "constraints/missing.xdc" in message
    assert "driver.whl" not in message
