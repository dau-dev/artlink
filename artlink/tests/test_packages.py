import io
import tarfile
from pathlib import Path
from zipfile import ZipFile

import pytest

from artlink import Artifact, Manifest, PackageError, build_package_archive, extract_archive, install_package_archive, normalize_package_type


def _tar_with(path: Path, members: dict[str, bytes]) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return path


def test_package_type_is_a_single_safe_path_component() -> None:
    assert normalize_package_type("HDL") == "hdl"
    assert normalize_package_type("hardware_project") == "hdl"
    assert normalize_package_type("my.type") == "my.type"
    for bad in ("../etc", "a/b", "/abs", " ", "name with space", "-leading"):
        with pytest.raises(PackageError):
            normalize_package_type(bad)


def test_archive_members_that_escape_the_destination_are_refused(tmp_path: Path) -> None:
    archive = _tar_with(tmp_path / "evil.tar.gz", {"../escaped.txt": b"x", "ok.txt": b"y"})
    destination = tmp_path / "prefix"
    destination.mkdir()
    with pytest.raises(PackageError, match="escapes the destination"):
        extract_archive(archive, destination)
    assert not (tmp_path / "escaped.txt").exists()
    assert not (destination / "ok.txt").exists()  # nothing was written

    zip_path = tmp_path / "evil.zip"
    with ZipFile(zip_path, "w") as archive:
        archive.writestr("../escaped.txt", "x")
    with pytest.raises(PackageError, match="escapes the destination"):
        extract_archive(zip_path, destination)


def test_symlink_members_pointing_outside_are_refused_by_the_data_filter(tmp_path: Path) -> None:
    archive_path = tmp_path / "link.tar"
    with tarfile.open(archive_path, "w") as archive:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    destination = tmp_path / "prefix"
    destination.mkdir()
    with pytest.raises(PackageError, match="unsafe member"):
        extract_archive(archive_path, destination)


def test_extraction_refuses_to_overwrite_unless_asked(tmp_path: Path) -> None:
    archive = _tar_with(tmp_path / "pkg.tar.gz", {"share/artlink/docs/a/1/manifest.yaml": b"new\n"})
    prefix = tmp_path / "prefix"
    existing = prefix / "share" / "artlink" / "docs" / "a" / "1" / "manifest.yaml"
    existing.parent.mkdir(parents=True)
    existing.write_text("old\n", encoding="utf-8")

    with pytest.raises(PackageError, match="refusing to overwrite"):
        install_package_archive(archive, target_dir=prefix)
    assert existing.read_text(encoding="utf-8") == "old\n"

    install_package_archive(archive, target_dir=prefix, overwrite=True)
    assert existing.read_text(encoding="utf-8") == "new\n"


def test_build_package_archive_places_artifacts_under_the_package_root(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.md").write_text("# hi\n", encoding="utf-8")
    manifest = Manifest(name="mydocs", version="1.0", artifacts=(Artifact(path=Path("docs/index.md"), role="docs"),))
    archive = build_package_archive(manifest, artifact_root=tmp_path, output_dir=tmp_path / "dist", package_type="docs")
    with tarfile.open(archive) as tar:
        names = sorted(tar.getnames())
    assert names == ["share/artlink/docs/mydocs/1.0/docs/index.md", "share/artlink/docs/mydocs/1.0/manifest.yaml"]


def test_not_an_archive_is_refused(tmp_path: Path) -> None:
    plain = tmp_path / "plain.txt"
    plain.write_text("x", encoding="utf-8")
    with pytest.raises(PackageError, match="not a tar or zip archive"):
        extract_archive(plain, tmp_path / "out")
