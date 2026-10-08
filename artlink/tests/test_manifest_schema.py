"""``artlink.manifest/v0`` has a published JSON Schema, generated from the
``Manifest`` model and held equal to it, and the manifests this package
writes and documents validate against it."""

import json
import re
from pathlib import Path

import jsonschema
import yaml

from artlink import Artifact, Capability, Digest, Manifest, manifest_json_schema
from artlink.manifest import MANIFEST_JSON_SCHEMA_PATH

README = Path(__file__).resolve().parents[2] / "README.md"


def test_the_published_schema_is_the_model():
    published = json.loads(MANIFEST_JSON_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert published == manifest_json_schema(), "regenerate artlink/schemas/artlink.manifest-v0.json from manifest_json_schema()"
    assert published["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    jsonschema.Draft202012Validator.check_schema(published)


def test_a_written_manifest_validates_against_the_schema():
    manifest = Manifest(
        name="golden",
        version="1.2.3",
        intent="input",
        artifacts=(
            Artifact(
                id="rtl",
                path=Path("rtl/filter.sv"),
                kind="source",
                role="hdl-source",
                provides=(Capability(kind="hdl-module", name="filter"), "filter"),
                digest=Digest(algorithm="sha256", value="a" * 64),
            ),
            Artifact(uri="https://example.invalid/doc.pdf", role="docs"),
        ),
    )
    document = yaml.safe_load(manifest.to_yaml_text())
    jsonschema.validate(document, manifest_json_schema())
    assert Manifest(**document) == manifest


def test_the_readme_manifest_examples_validate_against_the_schema():
    text = README.read_text(encoding="utf-8")
    documents = [yaml.safe_load(block) for block in re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)]
    manifests = [doc for doc in documents if isinstance(doc, dict) and doc.get("schema") == "artlink.manifest/v0"]
    assert manifests
    for document in manifests:
        jsonschema.validate(document, manifest_json_schema())


def test_the_schema_refuses_what_the_model_refuses():
    schema = manifest_json_schema()
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors({"schema": "artlink.manifest/v0", "name": "m", "unknown": 1}))  # additionalProperties
    assert list(validator.iter_errors({"schema": "artlink.manifest/v0"}))  # name required
    assert list(validator.iter_errors({"schema": "artlink.manifest/v0", "name": "m", "references": [{"kind": "package", "target": "x"}]}))
