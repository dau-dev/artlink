# artlink

A package for packaging, organizing, and combining artifacts

[![Build Status](https://github.com/dau-dev/artlink/actions/workflows/build.yaml/badge.svg?branch=main&event=push)](https://github.com/dau-dev/artlink/actions/workflows/build.yaml)
[![codecov](https://codecov.io/gh/dau-dev/artlink/branch/main/graph/badge.svg)](https://codecov.io/gh/dau-dev/artlink)
[![License](https://img.shields.io/github/license/dau-dev/artlink)](https://github.com/dau-dev/artlink)
[![PyPI](https://img.shields.io/pypi/v/artlink.svg)](https://pypi.python.org/pypi/artlink)

## Overview

`artlink` is a meta package for building package managers. It provides a small, domain-neutral model for describing artifacts, grouping them into manifests, validating those manifests with templates, and composing manifests into build inputs or output receipts.

The current core schemas are:

- `artlink.manifest/v0` for artifact manifests.
- `artlink.template/v0` for declarative manifest validation templates.
- `artlink.registry/v0` for registry configuration.

The older `artlink.poc` package is still present as an experimental reference, but it is not the compatibility target for new work.

The public model objects inherit from `ccflow.BaseModel`, which keeps them compatible with ccflow/Hydra-style `_target_` instantiation while the YAML helpers emit clean artlink schema files without `_target_` metadata.

Reusable functionality lives in the core modules plus `artlink.domains.common`, `artlink.packages`, `artlink.registry`, and `artlink.cli_tools`. The HDL, Python, model-release, and documentation profiles are intentionally packaged as example domain profiles under `artlink.examples.domains`, not as core artlink policy.

## Core Concepts

An `Artifact` is a file, directory, URI, generated output, package resource, or logical content item that another tool can consume. It has a broad `kind`, a domain-facing `role`, optional source metadata, optional capabilities in `provides` and `requires`, and optional digest or metadata fields.

A `Manifest` is a named collection of artifacts. It can describe concrete files that exist now, required inputs that must be resolved later, or produced outputs from a build.

A `Template` is a declarative validator for manifests. It uses selectors and cardinality rules to express requirements such as "at least one HDL source", "exactly one bitstream", or "no disposable build-cache artifacts".

## Python API

```python
from pathlib import Path

from artlink import Artifact, ArtifactSelector, Capability, Cardinality, Manifest, Template, TemplateRule

manifest = Manifest(
    name="project-inputs",
    intent="input",
    artifacts=(
        Artifact(
            id="filter-rtl",
            path=Path("rtl/filter.sv"),
            kind="source",
            role="hdl-source",
            language="systemverilog",
            provides=(Capability(kind="hdl-module", name="filter"),),
        ),
        Artifact(
            id="board-constraints",
            path=Path("constraints/demo.xdc"),
            kind="metadata",
            role="constraints",
            format="xdc",
        ),
    ),
)

template = Template(
    name="hardware-build-inputs",
    rules=(
        TemplateRule(
            name="requires-filter-module",
            selector=ArtifactSelector(kind="source", role="hdl-source", provides=Capability(kind="hdl-module", name="filter")),
            cardinality=Cardinality(min=1, max=1),
        ),
        TemplateRule(
            name="requires-constraints",
            selector=ArtifactSelector(role="constraints"),
            cardinality=Cardinality(min=1),
        ),
    ),
)

result = template.validate_manifest(manifest)
result.raise_for_errors()
```

## Manifest YAML

`Manifest.to_yaml_text()` emits JSON-friendly YAML with stable field names:

```yaml
schema: artlink.manifest/v0
name: project-inputs
version: ''
intent: input
artifacts:
    - id: filter-rtl
      name: ''
      path: rtl/filter.sv
      uri: ''
      kind: source
      role: hdl-source
      format: sv
      media_type: ''
      language: systemverilog
      provides:
                    - kind: hdl-module
                        name: filter
      requires: []
      digest: null
      metadata: {}
references: []
metadata: {}
```

Use `load_manifest(path)` to read a manifest and `validate_artifact_files(manifest, root=...)` when a workflow needs to prove that path-based artifacts exist locally. URI-only artifacts are skipped by local path validation.

Artifact paths in manifest YAML should be absolute or relative to the directory containing the manifest file. `Artifact` uses Pydantic validation to infer generic fields such as `format` and `media_type` from file paths or URI suffixes when those fields are omitted. Explicit values always win. If an explicit value differs from generic inference, `artifact.inference_issues` reports a warning diagnostic without changing the artifact.

Artifact `id` is optional. Use it when a tool or human needs a stable short handle for an artifact; otherwise artlink falls back to `name` and then location for display and diagnostics. A manifest rejects duplicate artifact locations instead of silently deduplicating them, because two entries with the same path or URI but different roles or metadata are usually an authoring mistake.

Capabilities in `provides` and `requires` can be written as simple strings or as typed records. A simple selector such as `provides: filter` matches any capability named `filter`; a typed selector such as `provides: {kind: hdl-module, name: filter}` requires both the kind and name to match.

## Template YAML

Templates are also serializable:

```yaml
schema: artlink.template/v0
name: bitstream-output
version: ''
rules:
  - name: requires-one-bitstream
    selector:
      kind: binary
      role: bitstream
    cardinality:
      min: 1
      max: 1
    severity: error
    message: ''
metadata: {}
```

Selectors currently support `kind`, `role`, `language`, `format`, `media_type`, `path_glob`, `provides`, `requires`, and `metadata_key`. Capability selectors accept either simple string shorthand or typed capability records. Cardinality rules support `min` and optional `max`. Validation returns structured issues so callers can decide whether to raise, warn, or report diagnostics as JSON later.

## Composition Workflow

Multiple manifests can be composed into a new manifest while preserving the source manifest names in metadata:

```python
from pathlib import Path

from artlink import Manifest, load_manifest

project_inputs = Manifest.compose(
    name="project-inputs",
    intent="input",
    manifests=(
        load_manifest(Path("source-package.yaml")),
        load_manifest(Path("constraints-package.yaml")),
        load_manifest(Path("driver-package.yaml")),
    ),
)

assert project_inputs.metadata["composed_from"] == [
    "source-package",
    "constraints-package",
    "driver-package",
]
```

## Registry Discovery

`ArtifactRegistry` tracks the manifests, templates, and artifacts available to a consuming tool. Registry entries preserve their source so later resolver errors can explain where each manifest, template, or artifact came from.

There are four supported population paths:

- Explicit registration with `register_manifest`, `register_artifact`, or `register_manifest_file`.
- Template registration with `register_template` or `register_template_file`.
- Install-path discovery under `share/artlink` from an install root or Python data prefix.
- Python entry-point discovery through the `artlink.manifests` group.

```python
from pathlib import Path

from artlink import ArtifactRegistry, Manifest, Reference, artlink_install_dir, manifest_install_dir

registry = ArtifactRegistry()
registry.register_manifest(Manifest(name="local", artifacts=()), source="explicit")
registry.register_manifest_file(Path("package.artlink.yaml"))

install_dir = manifest_install_dir(Path("/opt/example"))
assert install_dir == Path("/opt/example/share/artlink/manifests")
assert artlink_install_dir(Path("/opt/example")) == Path("/opt/example/share/artlink")

installed_registry = ArtifactRegistry.from_install_path(Path("/opt/example"))
installed_registry.discover_entry_points()

entry = registry.resolve_reference(Reference(kind="manifest", target="local"))
assert entry.manifest.name == "local"
```

Installed manifests should also use artifact paths relative to their own manifest file location, or absolute paths when necessary. For example, a manifest installed at `/opt/example/share/artlink/hdl-filter/2.0.0/manifest.yaml` next to `/opt/example/share/artlink/hdl-filter/2.0.0/filter.sv` can be written as:

```yaml
schema: artlink.manifest/v0
name: hdl-filter
version: 2.0.0
artifacts:
    - path: filter.sv
      role: hdl-source
```

`ArtifactRegistry.from_install_path(prefix)` recursively discovers manifest files under `prefix/share/artlink`. That includes the conventional `share/artlink/manifests` directory and package-owned subdirectories such as `share/artlink/hdl-filter/2.0.0/manifest.yaml`. Registry entries remember the manifest file directory, so `registry.artifact_file_path(entry)` resolves relative artifact paths from the manifest that declared them.

For package builds with Hatch, shared data can install the manifest separately from the payload while keeping both under `share/artlink`:

```toml
[tool.hatch.build.targets.wheel.shared-data]
"artlink-manifests/hdl-filter.yaml" = "share/artlink/manifests/hdl-filter.yaml"
"artlink-data/hdl-filter/2.0.0" = "share/artlink/hdl-filter/2.0.0"
```

An installed package can also advertise manifests by defining entry points in the `artlink.manifests` group:

```toml
[project.entry-points."artlink.manifests"]
hdl-filter = "my_hardware_package.artlink:manifest_paths"
```

```python
from pathlib import Path
from sysconfig import get_path


def manifest_paths():
    prefix = Path(get_path("data"))
    return (prefix / "share" / "artlink" / "manifests" / "hdl-filter.yaml",)
```

Each entry point may load a `Manifest`, a manifest file path, a callable returning either of those, or an iterable containing any of those values. When an entry point returns a manifest file path, relative artifact paths are resolved from that manifest file's directory.

By default, a registry rejects multiple manifests with the same name. This is useful for ecosystems such as Python where one installed distribution should own a package name. Hardware package managers often need multiple versions of a reusable block side by side, so they can opt in with `ArtifactRegistry(allow_manifest_versions=True)` or `ArtifactRegistry.from_install_path(prefix, allow_manifest_versions=True)`. Versioned registries resolve `Reference(kind="manifest", target="hdl-filter", version="2.0.0")`; an unversioned reference is rejected if more than one version is available.

Registry YAML is a tool configuration file, not an artifact manifest. Its job is to tell a consuming process which install roots, manifest files, template files, and direct local artifacts should be visible in an `ArtifactRegistry`. `load_registry(path)` resolves relative `install_roots`, `manifest_files`, `template_files`, and direct artifact roots relative to the registry config file.

The artlink-owned shape uses a registry schema id:

```yaml
schema: artlink.registry/v0
allow_manifest_versions: true
install_roots:
    - /opt/example
manifest_files:
    - local-package.yaml
template_files:
    - local-template.yaml
registered_artifacts:
    - id: local-doc
      path: docs/readme.txt
      kind: metadata
      role: docs
```

`ArtifactRegistry` is also a ccflow model, so config-driven tools may still instantiate it with the `_target_` pattern Hydra/ccflow users expect:

```yaml
_target_: artlink.registry.ArtifactRegistry
allow_manifest_versions: true
install_roots:
    - /opt/example
```

```python
from pathlib import Path

from artlink import ArtifactRegistry, load_registry

registry = ArtifactRegistry.model_validate(
    {"_target_": "artlink.registry.ArtifactRegistry", "allow_manifest_versions": True}
)
configured_registry = load_registry(Path("artlink-registry.yaml"))
```

For distributable packages, prefer manifest YAML files under `share/artlink` over standalone artifact entries. Direct `registered_artifacts` are useful for local tools and tests; package-owned artifacts should normally travel inside a named manifest so provenance, versioning, and reference resolution stay explicit.

## Resolution Graphs

`resolve_manifest(manifest, registry)` resolves manifest references recursively and records template references in the same graph. Templates can reference other templates, so shared validation requirements can be composed without duplicating rules. The returned `ResolutionPlan` records graph nodes, edges, resolved manifests, resolved templates, artifacts contributed by resolved manifests, provider selections, and structured resolution issues. It fails early on missing, ambiguous, or cyclic manifest references.

```python
from pathlib import Path

from artlink import ArtifactRegistry, Manifest, Reference, resolve_manifest

registry = ArtifactRegistry.from_install_path(Path("/opt/example"), allow_manifest_versions=True)
project = Manifest(
    name="hardware-project",
    references=(
        Reference(kind="template", target="hardware-build-inputs"),
        Reference(kind="manifest", target="hdl-filter", version="2.0.0"),
    ),
)

plan = resolve_manifest(project, registry, manifest_version_policy="highest")
resolved_inputs = Manifest.compose(name="resolved-inputs", manifests=tuple(plan.resolved_manifests))
assert [artifact.display_id for artifact in resolved_inputs.artifacts]
assert [template.name for template in plan.resolved_templates]
```

The resolver also detects duplicate capability providers across resolved manifests. By default, duplicate providers are errors. Tools that want to report diagnostics without failing can use `provider_conflict_policy="warning"`; tools that intentionally allow duplicates can use `provider_conflict_policy="ignore"`. A first selection policy, `provider_conflict_policy="prefer-explicit"`, chooses explicitly registered providers and records that selection in the plan.

Resolution is intentionally separate from materialization. `build_materialization_plan(plan, registry, target_dir=...)` produces a `MaterializationPlan` describing local copy, symlink, archive extraction, package resource, and remote reference actions. `execute_materialization_plan(plan)` performs local filesystem actions while leaving remote references as no-ops.

## Package Archives

`artlink.packages` provides domain-neutral helpers for building discoverable `.tar.gz` artifact packages. A package archive places a manifest under `share/artlink/<type>/<name>/<version>/manifest.yaml` and stores path-based artifacts next to it, so extracting the archive into an install prefix makes it discoverable with `ArtifactRegistry.from_install_path(prefix)`.

```python
from pathlib import Path

from artlink import ArtifactRegistry, build_package_archive, discover_packages, install_package_archive
from artlink.examples.domains.docs import DocumentationSiteScheme

scheme = DocumentationSiteScheme(document_globs=("docs/**/*.md",))
manifest = scheme.bundle(root=Path("."), name="mydocs", version="1.2.3")
archive = build_package_archive(manifest, artifact_root=Path("."), output_dir=Path("dist"), package_type="docs")

assert archive == Path("dist/mydocs-1.2.3.tar.gz")

install_package_archive(archive, target_dir=Path("/opt/example"))
registry = ArtifactRegistry.from_install_path(Path("/opt/example"), allow_manifest_versions=True)
assert registry.get_manifest("mydocs", version="1.2.3")
assert [package.name for package in discover_packages(Path("/opt/example"), package_type="docs")] == ["mydocs"]
```

Archive package types are normalized, so `HDL`, `hardware-project`, and `hdl` all map to `hdl`; `documentation-site` maps to `docs`; and `model-release` maps to `ml`. Registry discovery skips non-artlink YAML payload files under `share/artlink`, so docs packages can safely contain files such as `mkdocs.yml`.

## Hardware Profile Example

Domain profiles are intentionally practical: each one bundles common project files according to a scheme, installs the resolved artifacts, and returns a Python object with the paths and tool requirements a downstream tool needs. They sit on top of the same manifest, registry, resolver, and materializer core; they do not make the core domain-specific.

The hardware profile collects HDL build inputs for downstream Vivado, simulator, cocotb, or Verilator tooling.

```python
from pathlib import Path

from artlink import ArtifactRegistry, Manifest, Reference, resolve_manifest
from artlink.examples.domains.hdl import HardwareProjectScheme, ToolRequirement

scheme = HardwareProjectScheme(
    design_source_globs=("rtl/*.sv",),
    include_globs=("include/*.svh",),
    systemverilog_testbench_globs=("tb/*.sv",),
    cocotb_test_globs=("tests/test_*.py",),
    verilator_source_globs=("verilator/*.cpp",),
    constraint_globs=("constraints/*.xdc",),
    tools=(
        ToolRequirement(name="vivado"),
        ToolRequirement(name="verilator"),
        ToolRequirement(name="python", packages=("cocotb", "pytest")),
    ),
)

bundle = scheme.bundle(root=Path("."), name="demo-hardware")
registry = ArtifactRegistry.from_manifests((bundle,), root=Path("."))
request = Manifest(name="demo-build", references=(Reference(kind="manifest", target="demo-hardware"),))
resolution = resolve_manifest(request, registry, provider_conflict_policy="prefer-explicit")
inputs = scheme.install_and_collect(resolution, registry, target_dir=Path("build/artlink-inputs"))

assert inputs.design_sources
assert inputs.include_dirs
assert inputs.constraints
assert inputs.tools["python"].packages == ("cocotb", "pytest")
```

The profile does not generate Tcl, invoke simulators, run pytest, or run Verilator. It gives those tools the resolved design sources, include files/directories, SystemVerilog test benches, cocotb pytest files, Verilator C++ sources, constraints, and tool requirements they need.

## Python Packaging Profile

`PythonPackageScheme` bundles Python project files and built distributions. It reads `[project]` metadata from `pyproject.toml`, keeps wheels and source distributions as distributable package artifacts, and collects the paths a downstream packaging, publishing, or validation tool needs.

```python
from pathlib import Path

from artlink import ArtifactRegistry, Manifest, Reference, resolve_manifest
from artlink.examples.domains.python import PythonPackageScheme, ToolRequirement

scheme = PythonPackageScheme(
    package_source_globs=("src/**/*.py",),
    test_source_globs=("tests/test_*.py",),
    distribution_globs=("dist/*",),
    metadata_file_globs=("README.md", "LICENSE*"),
    tools=(ToolRequirement(name="python", packages=("build", "hatchling", "pytest")),),
)

bundle = scheme.bundle(root=Path("."), name="demo-python-package")
registry = ArtifactRegistry.from_manifests((bundle,), root=Path("."))
request = Manifest(name="package-demo", references=(Reference(kind="manifest", target="demo-python-package"),))
resolution = resolve_manifest(request, registry, provider_conflict_policy="prefer-explicit")
package = scheme.install_and_collect(resolution, registry, target_dir=Path("build/artlink-package"))

assert package.package_name
assert package.project_file
assert package.package_sources
assert package.wheels or package.source_distributions
assert package.tools["python"].packages == ("build", "hatchling", "pytest")
```

The integration test builds a real Hatchling project with `python -m build --sdist --wheel --no-isolation`, then verifies that artlink collects the `pyproject.toml`, package sources, tests, README, wheel, sdist, and packaging tool requirements.

## Model Release Profile

`ModelReleaseScheme` is a concrete example for ML deployment and evaluation workflows. It collects model files, inference code, schemas, metrics, configuration, environment files, and tool requirements into a typed `ModelReleaseCollection`.

```python
from pathlib import Path

from artlink import ArtifactRegistry, Manifest, Reference, resolve_manifest
from artlink.examples.domains.ml import ModelReleaseScheme, ToolRequirement

scheme = ModelReleaseScheme(
    model_globs=("models/*.onnx",),
    inference_code_globs=("src/*.py",),
    schema_globs=("schemas/*.json",),
    metric_globs=("metrics/*.json",),
    config_globs=("configs/*.yaml",),
    environment_globs=("requirements.txt",),
    tools=(ToolRequirement(name="python", packages=("onnxruntime", "numpy")),),
)

bundle = scheme.bundle(root=Path("."), name="classifier-release", version="2026.05")
registry = ArtifactRegistry.from_manifests((bundle,), root=Path("."))
request = Manifest(name="deploy-classifier", references=(Reference(kind="manifest", target="classifier-release", version="2026.05"),))
resolution = resolve_manifest(request, registry, provider_conflict_policy="prefer-explicit")
release = scheme.install_and_collect(resolution, registry, target_dir=Path("build/model-release"))

assert release.models
assert release.inference_code
assert release.schemas
assert release.tools["python"].packages == ("onnxruntime", "numpy")
```

This profile does not evaluate or serve a model. It prepares the resolved artifact paths and requirements for whatever deployment, validation, or packaging command owns those tasks.

## Documentation Site Profile

`DocumentationSiteScheme` collects docs source, static assets, site configuration, built output, and documentation tooling. It is useful for packaging docs as release artifacts or feeding a publish step with normalized paths.

```python
from pathlib import Path

from artlink import ArtifactRegistry, Manifest, Reference, resolve_manifest
from artlink.examples.domains.docs import DocumentationSiteScheme, ToolRequirement

scheme = DocumentationSiteScheme(
    config_globs=("mkdocs.yml",),
    document_globs=("docs/**/*.md",),
    asset_globs=("docs/assets/*",),
    built_site_globs=("site/**/*.html",),
    tools=(ToolRequirement(name="mkdocs"),),
)

bundle = scheme.bundle(root=Path("."), name="demo-docs")
registry = ArtifactRegistry.from_manifests((bundle,), root=Path("."))
request = Manifest(name="publish-docs", references=(Reference(kind="manifest", target="demo-docs"),))
resolution = resolve_manifest(request, registry, provider_conflict_policy="prefer-explicit")
docs = scheme.install_and_collect(resolution, registry, target_dir=Path("build/docs-release"))

assert docs.configs
assert docs.documents
assert docs.assets
assert docs.built_site
```

The profile does not run MkDocs, Sphinx, or a publisher. It gives those tools the config, source, assets, built output, and tool requirements they need.

## CLI Builder Utilities

`artlink.cli_tools` provides utilities for building your own packaging CLI without forcing a universal `artlink` command shape. Register one or more scheme objects with `SchemeCliCommand`, then call `run_packaging_cli()` from your own console entry point.

```python
from artlink.cli_tools import SchemeCliCommand, run_packaging_cli
from artlink.examples.domains.hdl import HardwareProjectScheme
from artlink.examples.domains.python import PythonPackageScheme


def main() -> int:
    return run_packaging_cli(
        (
            SchemeCliCommand(name="python", scheme=PythonPackageScheme()),
            SchemeCliCommand(name="hdl", scheme=HardwareProjectScheme()),
        )
    )
```

That creates two reusable commands for each registered scheme:

```bash
my-packager bundle python --root . --name my-python-package --output build/my-python-package.yaml
my-packager install python --manifest build/my-python-package.yaml --target-dir build/artlink-inputs --collection-output build/collection.json
```

`bundle` scans the requested root and writes manifest YAML. `install` loads a manifest, resolves it through an `ArtifactRegistry`, materializes the files, and optionally emits the typed collection as JSON. CLI-generated manifests record the scanned `artifact_root` in manifest metadata so a local bundle/install command pair can write the manifest outside the scanned tree and still resolve relative artifact paths. For portable installed manifests, keep the manifest next to its payload under `share/artlink` or pass `--root` explicitly during install.

## Top-Level CLI

The package also installs an `artlink` command for end-to-end packaging and registry smoke tests over the bundled example profiles. It is deliberately small: it packages a project into a discoverable tarball, installs a tarball into a prefix, and lists discoverable packages.

```bash
artlink package --type docs --root . --name mydocs --version 1.2.3 --output-dir dist
artlink install dist/mydocs-1.2.3.tar.gz --target-dir /opt/example
artlink registry --root /opt/example --type HDL --format json
```

`artlink package --type docs` uses `DocumentationSiteScheme`; `--type HDL` uses `HardwareProjectScheme`; `--type ml` uses `ModelReleaseScheme`; and `--type python` uses `PythonPackageScheme`. The generated archive name is always `<name>-<version>.tar.gz` after path-safe normalization.

`artlink registry` lists all discovered artlink packages below the install root. The optional `--type` filter uses the same package type normalization as archive creation, so `--type=HDL`, `--type=hardware`, and `--type=hdl` select the same package class.

This is the first step toward the broader artlink flow:

```text
artifacts -> template validation -> manifest -> resolution/materialization -> artifacts
```

and:

```text
input manifests + local artifacts + build metadata -> output manifest
```

## Development

Run the test suite with:

```bash
python -m pytest -q artlink/tests
```

The tests include unit coverage for manifests, templates, registries, resolution, materialization, CLI-building helpers, and integration workflows for HDL projects, Python packages built with Hatchling, model releases, and documentation sites.

> [!NOTE]
> This library was generated using [copier](https://copier.readthedocs.io/en/stable/) from the [Base Python Project Template repository](https://github.com/python-project-templates/base).
