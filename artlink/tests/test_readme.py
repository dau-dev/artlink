"""The README's self-contained code blocks run as written: python blocks that
do not open with a ``# requires:`` line are executed, and yaml blocks that
carry an artlink schema are loaded through the matching constructor."""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import yaml

from artlink import manifest_from_mapping, template_from_mapping

README = Path(__file__).resolve().parents[2] / "README.md"
BLOCK = re.compile(r"```(python|yaml)\n(.*?)```", re.DOTALL)


def _blocks(language: str) -> list[str]:
    return [body for lang, body in BLOCK.findall(README.read_text(encoding="utf-8")) if lang == language]


def test_self_contained_python_blocks_run(tmp_path, monkeypatch) -> None:
    blocks = [block for block in _blocks("python") if not block.startswith("# requires:")]
    assert len(blocks) >= 3
    monkeypatch.chdir(tmp_path)
    for index, block in enumerate(blocks):
        module = types.ModuleType(f"readme_block_{index}")
        monkeypatch.setitem(sys.modules, module.__name__, module)
        try:
            exec(compile(block, f"README.md python block {index + 1}", "exec", dont_inherit=True), module.__dict__)  # noqa: S102
        except Exception as error:
            raise AssertionError(f"README python block {index + 1} does not run as written: {error!r}\n{block}") from error


def test_every_dependent_block_says_what_it_needs() -> None:
    for block in _blocks("python"):
        if block.startswith("# requires:"):
            assert len(block.splitlines()[0]) > len("# requires: ")


def test_manifest_and_template_yaml_blocks_load() -> None:
    loaded = 0
    for block in _blocks("yaml"):
        raw = yaml.safe_load(block)
        if not isinstance(raw, dict):
            continue
        if raw.get("schema") == "artlink.manifest/v0":
            manifest_from_mapping(raw)
            loaded += 1
        elif raw.get("schema") == "artlink.template/v0":
            template_from_mapping(raw)
            loaded += 1
    assert loaded >= 3
