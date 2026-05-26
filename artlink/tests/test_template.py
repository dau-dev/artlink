from pathlib import Path

from artlink import Artifact, ArtifactSelector, Capability, Cardinality, Manifest, Template, TemplateRule


def test_template_validates_required_and_forbidden_artifacts() -> None:
    template = Template(
        name="hdl-project-inputs",
        rules=(
            TemplateRule(name="requires-hdl", selector=ArtifactSelector(kind="source", role="hdl-source"), cardinality=Cardinality(min=1)),
            TemplateRule(name="one-constraints", selector=ArtifactSelector(role="constraints"), cardinality=Cardinality(min=1, max=1)),
            TemplateRule(name="no-disposable", selector=ArtifactSelector(kind="disposable"), cardinality=Cardinality(max=0)),
        ),
    )
    manifest = Manifest(
        name="bad-inputs",
        artifacts=(
            Artifact(path=Path("rtl/filter.sv"), kind="source", role="hdl-source", provides=("filter",)),
            Artifact(path=Path("build/filter.tmp"), kind="disposable", role="build-cache"),
        ),
    )

    result = template.validate_manifest(manifest)

    assert not result.is_valid
    assert [(issue.rule, issue.severity, issue.count) for issue in result.issues] == [
        ("one-constraints", "error", 0),
        ("no-disposable", "error", 1),
    ]
    assert "expected at least 1 artifact" in result.issues[0].message
    assert "expected at most 0 artifacts" in result.issues[1].message


def test_template_warning_does_not_make_validation_invalid() -> None:
    template = Template(
        name="python-package-advice",
        rules=(
            TemplateRule(
                name="recommend-readme",
                selector=ArtifactSelector(path_glob="README.md"),
                cardinality=Cardinality(min=1),
                severity="warning",
            ),
        ),
    )
    manifest = Manifest(
        name="python-source",
        artifacts=(Artifact(path=Path("pyproject.toml"), kind="metadata", role="python-project"),),
    )

    result = template.validate_manifest(manifest)

    assert result.is_valid
    assert len(result.issues) == 1
    assert result.issues[0].severity == "warning"


def test_selector_matches_capabilities_and_metadata() -> None:
    artifact = Artifact(
        path=Path("rtl/filter.sv"),
        kind="source",
        role="hdl-source",
        language="systemverilog",
        provides=("filter",),
        metadata={"top": "filter"},
    )

    assert ArtifactSelector(language="systemverilog", provides="filter", metadata_key="top").matches(artifact)
    assert not ArtifactSelector(language="verilog", provides="filter", metadata_key="top").matches(artifact)
    assert not ArtifactSelector(language="systemverilog", provides="missing", metadata_key="top").matches(artifact)


def test_selector_matches_typed_capabilities_and_string_shorthand() -> None:
    artifact = Artifact(
        path=Path("rtl/filter.sv"),
        role="hdl-source",
        provides=(Capability(kind="hdl-module", name="filter"),),
        requires=("clock",),
    )

    assert ArtifactSelector(provides="filter").matches(artifact)
    assert ArtifactSelector(provides=Capability(kind="hdl-module", name="filter")).matches(artifact)
    assert ArtifactSelector(requires="clock").matches(artifact)
    assert not ArtifactSelector(provides=Capability(kind="python-import", name="filter")).matches(artifact)


def test_template_round_trips_to_yaml(tmp_path) -> None:
    template = Template(
        name="bitstream-output",
        rules=(
            TemplateRule(
                name="requires-bitstream", selector=ArtifactSelector(kind="binary", role="bitstream"), cardinality=Cardinality(min=1, max=1)
            ),
        ),
    )
    template_path = tmp_path / "template.yaml"
    template_path.write_text(template.to_yaml_text(), encoding="utf-8")

    loaded = Template.load(template_path)

    assert loaded == template
    assert "schema: artlink.template/v0" in loaded.to_yaml_text()
