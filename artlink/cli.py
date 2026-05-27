from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from .examples.domains.docs import DocumentationSiteScheme
from .examples.domains.hdl import HardwareProjectScheme
from .examples.domains.ml import ModelReleaseScheme
from .examples.domains.python import PythonPackageScheme
from .packages import build_package_archive, discover_packages, install_package_archive, normalize_package_type

__all__ = ("main",)


def main(argv: Sequence[str] | None = None, *, output_stream: TextIO | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    stream = output_stream or sys.stdout

    if args.command == "package":
        package_type = normalize_package_type(args.package_type)
        scheme = _scheme_for_type(package_type)
        manifest = scheme.bundle(root=Path(args.root), name=args.name, version=args.version)
        archive_path = build_package_archive(manifest, artifact_root=Path(args.root), output_dir=Path(args.output_dir), package_type=package_type)
        stream.write(f"{archive_path}\n")
        return 0

    if args.command == "install":
        destination = install_package_archive(Path(args.archive), target_dir=Path(args.target_dir))
        stream.write(f"{destination}\n")
        return 0

    if args.command == "registry":
        packages = discover_packages(Path(args.root), package_type=args.package_type)
        if args.format == "json":
            stream.write(json.dumps([package.model_dump(mode="json") for package in packages], indent=2, sort_keys=True) + "\n")
        else:
            for package in packages:
                stream.write(f"{package.package_type}\t{package.name}\t{package.version}\t{package.source}\n")
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Package, install, and discover artlink artifact packages.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    package = subparsers.add_parser("package", help="bundle a project into a discoverable artlink tarball")
    package.add_argument("--type", dest="package_type", required=True, help="package type, such as docs, HDL, ml, or python")
    package.add_argument("--root", required=True, help="project root to scan")
    package.add_argument("--name", required=True, help="package/manifest name")
    package.add_argument("--version", required=True, help="package/manifest version")
    package.add_argument("--output-dir", required=True, help="directory for the generated tarball")

    install = subparsers.add_parser("install", help="extract a discoverable artlink tarball into an install root")
    install.add_argument("archive", help="artlink tarball to install")
    install.add_argument("--target-dir", required=True, help="install prefix to extract into")

    registry = subparsers.add_parser("registry", help="list discoverable artlink packages")
    registry.add_argument("--root", required=True, help="install prefix to search")
    registry.add_argument("--type", dest="package_type", default="", help="optional package type filter, such as HDL")
    registry.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def _scheme_for_type(package_type: str):
    if package_type == "docs":
        return DocumentationSiteScheme()
    if package_type == "hdl":
        return HardwareProjectScheme()
    if package_type == "ml":
        return ModelReleaseScheme()
    if package_type == "python":
        return PythonPackageScheme()
    raise SystemExit(f"unsupported package type: {package_type}")


if __name__ == "__main__":
    raise SystemExit(main())
