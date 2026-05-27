from __future__ import annotations

import io
import json
import shutil
import tarfile
from pathlib import Path

from artlink import ArtifactRegistry
from artlink.cli import main
from artlink.packages import discover_packages


def test_artlink_cli_packages_docs_tarball_and_discovers_downloaded_install(tmp_path: Path) -> None:
    project_root = tmp_path / "docs_project"
    _write(project_root / "mkdocs.yml", "site_name: Demo Docs\n")
    _write(project_root / "docs" / "index.md", "# Demo Docs\n")
    _write(project_root / "docs" / "tutorial.md", "# Tutorial\n")
    _write_bytes(project_root / "docs" / "assets" / "logo.png", b"png-demo")
    _write(project_root / "site" / "index.html", "<h1>Demo Docs</h1>\n")

    output_dir = tmp_path / "dist"
    assert (
        main(["package", "--type", "docs", "--root", str(project_root), "--name", "mydocs", "--version", "1.2.3", "--output-dir", str(output_dir)])
        == 0
    )

    archive_path = output_dir / "mydocs-1.2.3.tar.gz"
    assert archive_path.exists()
    with tarfile.open(archive_path) as archive:
        names = set(archive.getnames())
    assert "share/artlink/docs/mydocs/1.2.3/manifest.yaml" in names
    assert "share/artlink/docs/mydocs/1.2.3/docs/index.md" in names
    assert "share/artlink/docs/mydocs/1.2.3/site/index.html" in names

    downloaded_archive = tmp_path / "downloads" / archive_path.name
    downloaded_archive.parent.mkdir(parents=True)
    shutil.copy2(archive_path, downloaded_archive)
    install_root = tmp_path / "install_root"
    assert main(["install", str(downloaded_archive), "--target-dir", str(install_root)]) == 0

    registry = ArtifactRegistry.from_install_path(install_root, allow_manifest_versions=True)
    manifest = registry.get_manifest("mydocs", version="1.2.3")
    assert manifest.metadata["package_type"] == "docs"
    assert (install_root / "share" / "artlink" / "docs" / "mydocs" / "1.2.3" / "docs" / "index.md").exists()

    discovered = discover_packages(install_root, package_type="docs")
    assert [(package.package_type, package.name, package.version) for package in discovered] == [("docs", "mydocs", "1.2.3")]


def test_artlink_registry_cli_lists_and_filters_package_types(tmp_path: Path) -> None:
    docs_root = tmp_path / "docs_project"
    hdl_root = tmp_path / "hdl_project"
    _write(docs_root / "mkdocs.yml", "site_name: Demo Docs\n")
    _write(docs_root / "docs" / "index.md", "# Demo Docs\n")
    _write(hdl_root / "rtl" / "top.sv", "module top; endmodule\n")
    _write(hdl_root / "constraints" / "demo.xdc", "set_property PACKAGE_PIN A1 [get_ports clk]\n")

    dist = tmp_path / "dist"
    install_root = tmp_path / "install_root"
    assert main(["package", "--type", "docs", "--root", str(docs_root), "--name", "mydocs", "--version", "1.0.0", "--output-dir", str(dist)]) == 0
    assert main(["package", "--type", "HDL", "--root", str(hdl_root), "--name", "fpga-core", "--version", "2.0.0", "--output-dir", str(dist)]) == 0
    assert main(["install", str(dist / "mydocs-1.0.0.tar.gz"), "--target-dir", str(install_root)]) == 0
    assert main(["install", str(dist / "fpga-core-2.0.0.tar.gz"), "--target-dir", str(install_root)]) == 0

    all_output = io.StringIO()
    assert main(["registry", "--root", str(install_root), "--format", "json"], output_stream=all_output) == 0
    all_packages = json.loads(all_output.getvalue())
    assert [(package["type"], package["name"], package["version"]) for package in all_packages] == [
        ("docs", "mydocs", "1.0.0"),
        ("hdl", "fpga-core", "2.0.0"),
    ]

    hdl_output = io.StringIO()
    assert main(["registry", "--root", str(install_root), "--type", "HDL", "--format", "json"], output_stream=hdl_output) == 0
    hdl_packages = json.loads(hdl_output.getvalue())
    assert hdl_packages == [
        {
            "name": "fpga-core",
            "version": "2.0.0",
            "type": "hdl",
            "source": str(install_root / "share" / "artlink" / "hdl" / "fpga-core" / "2.0.0" / "manifest.yaml"),
            "artifact_count": 2,
        }
    ]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
