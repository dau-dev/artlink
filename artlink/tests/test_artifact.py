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


def test_artifact_paths_stay_inside_the_manifest_root() -> None:
    """An installed manifest that could point at ../../etc would make every
    registry a pointer to anywhere on the host."""
    for bad in ("/etc/passwd", "../sibling/payload.txt", "a/../../b"):
        with pytest.raises(ManifestError, match="stay inside its manifest root"):
            Artifact(path=Path(bad), role="data")
    with pytest.raises(ManifestError, match="stay inside its manifest root"):
        Manifest(name="m", artifacts=({"path": "../x", "role": "data"},))
