from __future__ import annotations

from pathlib import Path

from artlink import ArtifactRegistry, Manifest, Reference, resolve_manifest
from artlink.domains.docs import DocumentationSiteScheme, ToolRequirement


def test_documentation_site_scheme_bundles_installs_and_collects_publish_inputs(tmp_path: Path) -> None:
    _write(tmp_path / "mkdocs.yml", "site_name: Demo Docs\n")
    _write(tmp_path / "docs" / "index.md", "# Demo Docs\n")
    _write(tmp_path / "docs" / "tutorial.md", "# Tutorial\n")
    _write_bytes(tmp_path / "docs" / "assets" / "logo.png", b"png-demo")
    _write(tmp_path / "site" / "index.html", "<h1>Demo Docs</h1>\n")

    scheme = DocumentationSiteScheme(
        config_globs=("mkdocs.yml",),
        document_globs=("docs/**/*.md",),
        asset_globs=("docs/assets/*",),
        built_site_globs=("site/**/*.html",),
        tools=(ToolRequirement(name="mkdocs"),),
    )

    bundle = scheme.bundle(root=tmp_path, name="demo-docs")
    registry = ArtifactRegistry.from_manifests((bundle,), root=tmp_path)
    request = Manifest(name="publish-docs", references=(Reference(kind="manifest", target="demo-docs"),))
    resolution = resolve_manifest(request, registry, provider_conflict_policy="prefer-explicit")

    collection = scheme.install_and_collect(resolution, registry, target_dir=tmp_path / "installed")

    assert bundle.metadata["profile"] == "documentation-site"
    assert _relative_paths(collection.configs, tmp_path / "installed") == ["mkdocs.yml"]
    assert _relative_paths(collection.documents, tmp_path / "installed") == ["docs/index.md", "docs/tutorial.md"]
    assert _relative_paths(collection.assets, tmp_path / "installed") == ["docs/assets/logo.png"]
    assert _relative_paths(collection.built_site, tmp_path / "installed") == ["site/index.html"]
    assert collection.tools["mkdocs"].version == "any"
    assert all(path.exists() for path in collection.configs + collection.documents + collection.assets + collection.built_site)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _relative_paths(paths: tuple[Path, ...], root: Path) -> list[str]:
    return [path.relative_to(root).as_posix() for path in paths]
