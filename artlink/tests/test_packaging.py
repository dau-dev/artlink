from pathlib import Path

import pytest

from artlink.poc import Artifact, ArtifactManifest, ArtifactManifestError, load_artifact_manifest


def test_artifact_manifest_round_trips_sources_metadata_and_binaries(tmp_path: Path) -> None:
    (tmp_path / "rtl").mkdir()
    (tmp_path / "python").mkdir()
    (tmp_path / "constraints").mkdir()
    (tmp_path / "bitstreams").mkdir()
    (tmp_path / "rtl" / "filter.sv").write_text("module filter; endmodule\n", encoding="utf-8")
    (tmp_path / "python" / "model.py").write_text("class ReferenceModel: pass\n", encoding="utf-8")
    (tmp_path / "constraints" / "board.xdc").write_text("set_property PACKAGE_PIN A1 [get_ports clk]\n", encoding="utf-8")
    (tmp_path / "bitstreams" / "candidate.bit").write_bytes(b"DAU")
    manifest = ArtifactManifest(
        name="portable-bundle",
        artifacts=(
            Artifact(path=Path("rtl/filter.sv"), kind="source", role="hdl-source", language="systemverilog", modules=("filter",)),
            Artifact(path=Path("python/model.py"), kind="source", role="python-source", language="python", modules=("ReferenceModel",)),
            Artifact(path=Path("constraints/board.xdc"), kind="metadata", role="constraints", format="xdc"),
            Artifact(path=Path("bitstreams/candidate.bit"), kind="binary", role="bitstream", format="xilinx-bitstream"),
        ),
    )
    manifest_path = tmp_path / "artifact-manifest.yaml"
    manifest_path.write_text(manifest.to_yaml_text(), encoding="utf-8")

    loaded = load_artifact_manifest(manifest_path, validate_paths=True)

    assert loaded == manifest
    assert "schema: artlink.artifact-manifest/v0" in manifest.to_yaml_text()
    assert "kind: source" in manifest.to_yaml_text()
    assert "role: constraints" in manifest.to_yaml_text()
    assert "role: bitstream" in manifest.to_yaml_text()


def test_artifact_manifest_is_json_ready_for_pydantic_integrations() -> None:
    manifest = ArtifactManifest(
        name="portable-bundle",
        artifacts=(Artifact(path=Path("rtl/filter.sv"), kind="source", role="hdl-source", language="systemverilog", modules=("filter",)),),
    )

    assert manifest.model_dump(mode="json") == {
        "schema": "artlink.artifact-manifest/v0",
        "name": "portable-bundle",
        "artifacts": [
            {
                "path": "rtl/filter.sv",
                "kind": "source",
                "role": "hdl-source",
                "language": "systemverilog",
                "format": "",
                "modules": ["filter"],
                "media_type": "",
                "sha256": "",
            }
        ],
    }


def test_artifact_manifest_rejects_duplicate_artifact_paths() -> None:
    with pytest.raises(ArtifactManifestError) as exc_info:
        ArtifactManifest(
            name="bad-bundle",
            artifacts=(
                Artifact(path=Path("rtl/filter.sv"), kind="source", role="hdl-source", language="systemverilog"),
                Artifact(path=Path("rtl/filter.sv"), kind="source", role="hdl-source", language="systemverilog"),
            ),
        )

    assert "duplicate artifact path" in str(exc_info.value)


def test_load_artifact_manifest_rejects_missing_artifact_files(tmp_path: Path) -> None:
    manifest_path = tmp_path / "artifact-manifest.yaml"
    manifest_path.write_text(
        "\n".join(
            (
                "schema: artlink.artifact-manifest/v0",
                "name: missing-file-bundle",
                "artifacts:",
                "  - path: rtl/missing.sv",
                "    kind: source",
                "    role: hdl-source",
                "    language: systemverilog",
                "",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ArtifactManifestError) as exc_info:
        load_artifact_manifest(manifest_path, validate_paths=True)

    assert "missing artifact file" in str(exc_info.value)


def test_artifact_rejects_unknown_kind() -> None:
    with pytest.raises(ArtifactManifestError) as exc_info:
        Artifact(path=Path("rtl/filter.sv"), kind="hardware", role="hdl-source")

    assert "unsupported artifact kind" in str(exc_info.value)
