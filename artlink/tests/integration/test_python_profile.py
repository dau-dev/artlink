from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from artlink import ArtifactRegistry, Manifest, Reference, resolve_manifest
from artlink.examples.domains.python import PythonPackageScheme, ToolRequirement


def test_python_package_scheme_collects_hatch_built_distributions(tmp_path: Path) -> None:
    project_root = tmp_path / "demo_pkg_project"
    _write(
        project_root / "pyproject.toml",
        """
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "demo-pkg"
version = "0.1.0"
readme = "README.md"
requires-python = ">=3.11"

[tool.hatch.build.targets.wheel]
packages = ["src/demo_pkg"]
""".lstrip(),
    )
    _write(project_root / "README.md", "# Demo package\n")
    _write(project_root / "src" / "demo_pkg" / "__init__.py", "from .core import answer\n")
    _write(project_root / "src" / "demo_pkg" / "core.py", "def answer() -> int:\n    return 42\n")
    _write(project_root / "tests" / "test_core.py", "from demo_pkg import answer\n\ndef test_answer():\n    assert answer() == 42\n")

    subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--wheel", "--no-isolation", "--outdir", "dist"],
        cwd=project_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    scheme = PythonPackageScheme(
        package_source_globs=("src/**/*.py",),
        test_source_globs=("tests/test_*.py",),
        distribution_globs=("dist/*",),
        metadata_file_globs=("README.md",),
        tools=(ToolRequirement(name="python", packages=("build", "hatchling", "pytest")),),
    )

    bundle = scheme.bundle(root=project_root, name="demo-python-package")
    registry = ArtifactRegistry.from_manifests((bundle,), root=project_root)
    request = Manifest(name="demo-package-build", references=(Reference(kind="manifest", target="demo-python-package"),))
    resolution = resolve_manifest(request, registry, provider_conflict_policy="prefer-explicit")

    collection = scheme.install_and_collect(resolution, registry, target_dir=tmp_path / "installed")

    assert bundle.metadata["package_name"] == "demo-pkg"
    assert bundle.metadata["version"] == "0.1.0"
    assert collection.package_name == "demo-pkg"
    assert collection.version == "0.1.0"
    assert collection.project_file is not None
    assert collection.project_file.relative_to(tmp_path / "installed").as_posix() == "pyproject.toml"
    assert _relative_paths(collection.package_sources, tmp_path / "installed") == [
        "src/demo_pkg/__init__.py",
        "src/demo_pkg/core.py",
    ]
    assert _relative_paths(collection.test_sources, tmp_path / "installed") == ["tests/test_core.py"]
    assert [path.name for path in collection.wheels] == ["demo_pkg-0.1.0-py3-none-any.whl"]
    assert [path.name for path in collection.source_distributions] == ["demo_pkg-0.1.0.tar.gz"]
    assert collection.tools["python"].packages == ("build", "hatchling", "pytest")
    assert all(path.exists() for path in collection.package_sources + collection.wheels + collection.source_distributions)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _relative_paths(paths: tuple[Path, ...], root: Path) -> list[str]:
    return [path.relative_to(root).as_posix() for path in paths]
