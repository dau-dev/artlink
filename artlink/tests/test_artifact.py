from pathlib import Path
from typing import Any

import pytest

from artlink import Artifact, Digest, Manifest, ManifestError, Reference
from artlink.artifact import DIGEST_HEX_LENGTHS


def test_digest_accepts_a_known_algorithm_with_a_well_formed_value() -> None:
    digest = Digest(algorithm="sha256", value="A" * 64)
    assert digest.value == "a" * 64
    for algorithm, length in DIGEST_HEX_LENGTHS.items():
        assert Digest(algorithm=algorithm, value="0" * length).algorithm == algorithm


def test_digest_refuses_unknown_algorithms_and_malformed_values() -> None:
    with pytest.raises(ManifestError, match="unsupported digest algorithm"):
        Digest(algorithm="crc32", value="deadbeef")
    with pytest.raises(ManifestError, match="64 hex characters"):
        Digest(algorithm="sha256", value="a" * 63)
    with pytest.raises(ManifestError, match="64 hex characters"):
        Digest(algorithm="sha256", value="g" * 64)
    with pytest.raises(ManifestError):
        Digest(algorithm="", value="")


def test_reference_kinds_are_the_ones_resolution_implements() -> None:
    assert Reference(kind="manifest", target="x").kind == "manifest"
    assert Reference(kind="template", target="x").kind == "template"
    unresolvable: tuple[Any, ...] = ("artifact", "package", "registry")
    for kind in unresolvable:
        with pytest.raises(ManifestError):
            Reference(kind=kind, target="x")


def test_artifact_declares_exactly_one_location() -> None:
    with pytest.raises(ManifestError, match="path or uri"):
        Artifact(role="data")
    with pytest.raises(ManifestError, match="exactly one of path or uri"):
        Artifact(path=Path("a.txt"), uri="https://example.invalid/a.txt", role="data")
    assert Artifact(path=Path("a.txt"), role="data").location == "a.txt"
    assert Artifact(uri="https://example.invalid/a.txt", role="data").location == "https://example.invalid/a.txt"


def test_artifact_paths_do_not_climb_out_of_the_manifest_root() -> None:
    """An installed manifest that could point at ../../etc would make every
    registry a pointer to anywhere on the host."""
    for bad in ("../sibling/payload.txt", "a/../../b"):
        with pytest.raises(ManifestError, match="must not climb"):
            Artifact(path=Path(bad), role="data")
    with pytest.raises(ManifestError, match="must not climb"):
        Manifest(name="m", artifacts=({"path": "../x", "role": "data"},))


def test_an_absolute_path_is_carried_but_never_acted_on(tmp_path: Path) -> None:
    """Build tools record where an output landed on this host; the model keeps
    that, and every place artlink would read, copy or pack the file refuses."""
    from artlink import ArtifactRegistry, PackageError, RegistryError, build_materialization_plan, build_package_archive, resolve_manifest
    from artlink.materialize import MaterializationError

    payload = tmp_path / "payload.bit"
    payload.write_bytes(b"x")
    manifest = Manifest(name="built", version="1", artifacts=(Artifact(id="bit", path=payload, role="bitstream"),))
    assert manifest.artifacts[0].path == payload

    registry = ArtifactRegistry.from_manifests((manifest,), root=tmp_path)
    with pytest.raises(RegistryError, match="absolute"):
        registry.artifact_file_path(registry.find_artifacts(role="bitstream")[0])
    with pytest.raises(PackageError, match="absolute"):
        build_package_archive(manifest, artifact_root=tmp_path, output_dir=tmp_path / "dist", package_type="hdl")

    resolution = resolve_manifest(Manifest(name="p", references=(Reference(kind="manifest", target="built"),)), registry)
    with pytest.raises(MaterializationError, match="absolute"):
        build_materialization_plan(resolution, registry, target_dir=tmp_path / "out")
