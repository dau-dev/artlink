from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, TextIO

from pydantic import ConfigDict

from .artifact import Reference, _ArtlinkModel
from .manifest import Manifest, load_manifest
from .registry import ArtifactRegistry
from .resolver import resolve_manifest

__all__ = (
    "BundleScheme",
    "InstallCollectScheme",
    "SchemeCliCommand",
    "build_packaging_parser",
    "run_packaging_cli",
)


class BundleScheme(Protocol):
    def bundle(self, *, root: Path, name: str, version: str = "", metadata: dict[str, Any] | None = None) -> Manifest: ...


class InstallCollectScheme(BundleScheme, Protocol):
    def install_and_collect(self, resolution: Any, registry: ArtifactRegistry, *, target_dir: Path, path_method: str = "copy") -> Any: ...


class SchemeCliCommand(_ArtlinkModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    scheme: Any
    description: str = ""


def build_packaging_parser(commands: Sequence[SchemeCliCommand]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build package-manager CLIs from artlink schemes.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    _add_bundle_parser(subparsers, commands)
    _add_install_parser(subparsers, commands)
    return parser


def run_packaging_cli(
    commands: Sequence[SchemeCliCommand],
    argv: Sequence[str] | None = None,
    *,
    output_stream: TextIO | None = None,
) -> int:
    parser = build_packaging_parser(commands)
    args = parser.parse_args(list(argv) if argv is not None else None)

    command = _command_by_name(commands)[args.scheme]
    if args.action == "bundle":
        root = Path(args.root)
        manifest = command.scheme.bundle(root=root, name=args.name, version=args.version, metadata={"artifact_root": root.as_posix()})
        _write_text(args.output, manifest.to_yaml_text(), output_stream=output_stream)
        return 0
    if args.action == "install":
        manifest_path = Path(args.manifest)
        manifest = load_manifest(manifest_path)
        registry = ArtifactRegistry.from_manifests((manifest,), root=_artifact_root(args.root, manifest, manifest_path))
        request = Manifest(
            name=f"{manifest.name}-request",
            references=(Reference(kind="manifest", target=manifest.name, version=manifest.version),),
        )
        resolution = resolve_manifest(request, registry, provider_conflict_policy=args.provider_conflict_policy)
        collection = command.scheme.install_and_collect(resolution, registry, target_dir=Path(args.target_dir), path_method=args.path_method)
        if args.collection_output:
            _write_text(
                args.collection_output, json.dumps(collection.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", output_stream=output_stream
            )
        return 0
    parser.error(f"unsupported action: {args.action}")
    return 2


def _add_bundle_parser(subparsers: Any, commands: Sequence[SchemeCliCommand]) -> None:
    parser = subparsers.add_parser("bundle", help="bundle artifacts with a registered scheme")
    parser.add_argument("scheme", choices=tuple(command.name for command in commands))
    parser.add_argument("--root", required=True, help="project root to scan")
    parser.add_argument("--name", required=True, help="manifest name")
    parser.add_argument("--version", default="", help="manifest version")
    parser.add_argument("--output", default="-", help="manifest output path, or '-' for stdout")


def _add_install_parser(subparsers: Any, commands: Sequence[SchemeCliCommand]) -> None:
    parser = subparsers.add_parser("install", help="materialize and collect artifacts with a registered scheme")
    parser.add_argument("scheme", choices=tuple(command.name for command in commands))
    parser.add_argument("--manifest", required=True, help="manifest file to install")
    parser.add_argument("--root", default="", help="artifact root; defaults to the manifest directory")
    parser.add_argument("--target-dir", required=True, help="materialization target directory")
    parser.add_argument("--path-method", choices=("copy", "symlink"), default="copy")
    parser.add_argument("--provider-conflict-policy", choices=("error", "warning", "ignore", "prefer-explicit"), default="prefer-explicit")
    parser.add_argument("--collection-output", default="", help="collection JSON output path")


def _command_by_name(commands: Sequence[SchemeCliCommand]) -> dict[str, SchemeCliCommand]:
    return {command.name: command for command in commands}


def _write_text(path: str, text: str, *, output_stream: TextIO | None) -> None:
    if path == "-":
        (output_stream or sys.stdout).write(text)
        return
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


def _artifact_root(root: str, manifest: Manifest, manifest_path: Path) -> Path:
    if root:
        return Path(root)
    artifact_root = manifest.metadata.get("artifact_root")
    if isinstance(artifact_root, str) and artifact_root:
        return Path(artifact_root)
    return manifest_path.parent
