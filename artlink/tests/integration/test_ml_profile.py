from __future__ import annotations

from pathlib import Path

from artlink import ArtifactRegistry, Manifest, Reference, resolve_manifest
from artlink.examples.domains.ml import ModelReleaseScheme, ToolRequirement


def test_model_release_scheme_bundles_installs_and_collects_serving_inputs(tmp_path: Path) -> None:
    _write_bytes(tmp_path / "models" / "classifier.onnx", b"onnx-demo")
    _write(tmp_path / "src" / "serve.py", "def predict(payload):\n    return {'label': 'demo'}\n")
    _write(tmp_path / "schemas" / "input.schema.json", '{"type": "object"}\n')
    _write(tmp_path / "metrics" / "eval.json", '{"accuracy": 0.99}\n')
    _write(tmp_path / "configs" / "model.yaml", "threshold: 0.8\n")
    _write(tmp_path / "requirements.txt", "onnxruntime\nnumpy\n")

    scheme = ModelReleaseScheme(
        model_globs=("models/*.onnx",),
        inference_code_globs=("src/*.py",),
        schema_globs=("schemas/*.json",),
        metric_globs=("metrics/*.json",),
        config_globs=("configs/*.yaml",),
        environment_globs=("requirements.txt",),
        tools=(ToolRequirement(name="python", packages=("onnxruntime", "numpy")),),
    )

    bundle = scheme.bundle(root=tmp_path, name="classifier-release", version="2026.05")
    registry = ArtifactRegistry.from_manifests((bundle,), root=tmp_path)
    request = Manifest(name="deploy-classifier", references=(Reference(kind="manifest", target="classifier-release", version="2026.05"),))
    resolution = resolve_manifest(request, registry, provider_conflict_policy="prefer-explicit")

    collection = scheme.install_and_collect(resolution, registry, target_dir=tmp_path / "installed")

    assert bundle.metadata["profile"] == "model-release"
    assert _relative_paths(collection.models, tmp_path / "installed") == ["models/classifier.onnx"]
    assert _relative_paths(collection.inference_code, tmp_path / "installed") == ["src/serve.py"]
    assert _relative_paths(collection.schemas, tmp_path / "installed") == ["schemas/input.schema.json"]
    assert _relative_paths(collection.metrics, tmp_path / "installed") == ["metrics/eval.json"]
    assert _relative_paths(collection.configs, tmp_path / "installed") == ["configs/model.yaml"]
    assert _relative_paths(collection.environment_files, tmp_path / "installed") == ["requirements.txt"]
    assert collection.tools["python"].packages == ("onnxruntime", "numpy")
    assert collection.models[0].exists()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _relative_paths(paths: tuple[Path, ...], root: Path) -> list[str]:
    return [path.relative_to(root).as_posix() for path in paths]
