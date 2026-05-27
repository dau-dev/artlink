from __future__ import annotations

import json
from pathlib import Path

from artlink import load_manifest
from artlink.cli_tools import SchemeCliCommand, run_packaging_cli
from artlink.examples.domains.python import PythonPackageScheme, ToolRequirement


def test_packaging_cli_tools_bundle_install_and_emit_collection_json(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    manifest_path = tmp_path / "bundle.yaml"
    collection_path = tmp_path / "collection.json"
    installed_root = tmp_path / "installed"
    _write(
        project_root / "pyproject.toml",
        """
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "cli-demo"
version = "1.2.3"
""".lstrip(),
    )
    _write(project_root / "src" / "cli_demo" / "__init__.py", "VALUE = 1\n")
    _write(project_root / "tests" / "test_cli_demo.py", "def test_value():\n    assert True\n")

    command = SchemeCliCommand(
        name="python",
        scheme=PythonPackageScheme(
            package_source_globs=("src/**/*.py",),
            test_source_globs=("tests/test_*.py",),
            tools=(ToolRequirement(name="python", packages=("pytest",)),),
        ),
    )

    assert run_packaging_cli((command,), ["bundle", "python", "--root", str(project_root), "--name", "cli-demo", "--output", str(manifest_path)]) == 0
    manifest = load_manifest(manifest_path)
    assert manifest.name == "cli-demo"
    assert manifest.metadata["package_name"] == "cli-demo"

    assert (
        run_packaging_cli(
            (command,),
            [
                "install",
                "python",
                "--manifest",
                str(manifest_path),
                "--target-dir",
                str(installed_root),
                "--collection-output",
                str(collection_path),
            ],
        )
        == 0
    )
    payload = json.loads(collection_path.read_text(encoding="utf-8"))

    assert payload["package_name"] == "cli-demo"
    assert payload["version"] == "1.2.3"
    assert payload["project_file"] == str(installed_root / "pyproject.toml")
    assert payload["package_sources"] == [str(installed_root / "src" / "cli_demo" / "__init__.py")]
    assert payload["test_sources"] == [str(installed_root / "tests" / "test_cli_demo.py")]
    assert payload["tools"]["python"]["packages"] == ["pytest"]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
