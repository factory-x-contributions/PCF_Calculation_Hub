# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""One-off script to add REUSE SPDX headers across the repository."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COPYRIGHT = "Copyright Siemens 2026"
LICENSE = "Apache-2.0"

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".aws-sam",
    "node_modules",
    ".pytest_cache",
    ".pytest_basetemp",
    "build",
    "dist",
    ".eggs",
    "LICENSES",
}

# Paths without inline comment syntax or third-party license text.
SKIP_REL_PATHS = {
    "coverage.xml",
    "app/data/aas_processed_shells.json",
    "app/data/app_config.json",
    "app/data/data_base_factory.json",
    "app/data/data_base.json",
    "tests/fixtures/aas/AAS_WO_2026_03_04_Template.json",
}

SKIP_EXTENSIONS = {
    ".json",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".pyc",
    ".whl",
    ".egg",
}

SPDX_MARKERS = ("SPDX-FileCopyrightText:", "SPDX-License-Identifier:")

HASH_NAMES = {
    ".coveragerc",
    ".gitignore",
    ".gitattributes",
    ".samignore",
    ".env.example",
    "requirements.txt",
    "LICENSE.txt",
    "COPYRIGHT.md",
}

EXTENSION_STYLE: dict[str, str] = {
    ".py": "hash",
    ".sh": "hash",
    ".yml": "hash",
    ".yaml": "hash",
    ".toml": "hash",
    ".ini": "hash",
    ".cfg": "hash",
    ".md": "html",
    ".html": "html",
    ".css": "block",
    ".js": "block_slash",  # /* */ works in JS at top level
    ".mmd": "mermaid",
    ".svg": "xml",
    ".xml": "xml",
    ".txt": "hash",
}


def has_spdx(content: str) -> bool:
    return all(m in content for m in SPDX_MARKERS)


def build_header(style: str) -> str:
    text_line = f"SPDX-FileCopyrightText: {COPYRIGHT}"
    license_line = f"SPDX-License-Identifier: {LICENSE}"

    if style == "hash":
        return f"# {text_line}\n# {license_line}\n"
    if style == "html":
        return (
            f"<!-- {text_line} -->\n"
            f"<!-- {license_line} -->\n"
        )
    if style == "block":
        return (
            f"/* {text_line} */\n"
            f"/* {license_line} */\n"
        )
    if style == "block_slash":
        return (
            f"/* {text_line} */\n"
            f"/* {license_line} */\n"
        )
    if style == "mermaid":
        return (
            f"%% {text_line}\n"
            f"%% {license_line}\n"
        )
    if style == "xml":
        return (
            f"<!-- {text_line} -->\n"
            f"<!-- {license_line} -->\n"
        )
    raise ValueError(f"unknown style: {style}")


def insert_after_xml_declaration(content: str, header: str) -> str:
    match = re.match(r"<\?xml[^?]*\?>", content, re.IGNORECASE)
    if match:
        decl = match.group(0)
        rest = content[match.end() :].lstrip()
        # Strip a prior inline SPDX block so re-runs can fix formatting.
        rest = re.sub(
            r"<!--\s*SPDX-FileCopyrightText:[^>]*-->\s*"
            r"<!--\s*SPDX-License-Identifier:[^>]*-->\s*",
            "",
            rest,
            count=1,
        )
        return f"{decl}\n{header}{rest}"
    return header + content


def insert_header(content: str, header: str, style: str) -> str:
    if style == "xml":
        return insert_after_xml_declaration(content, header)
    return header + content


def style_for(path: Path) -> str | None:
    if path.name in HASH_NAMES:
        return "hash"
    ext = path.suffix.lower()
    return EXTENSION_STYLE.get(ext)


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in SKIP_REL_PATHS:
            continue
        if path.suffix.lower() in SKIP_EXTENSIONS:
            continue
        if style_for(path) is None:
            continue
        files.append(path)
    return sorted(files)


def process_file(path: Path) -> str:
    """Return 'updated', 'skipped', or 'error'."""
    style = style_for(path)
    if style is None:
        return "skipped"

    try:
        raw = path.read_bytes()
    except OSError:
        return "error"

    if b"\x00" in raw[:8192]:
        return "skipped"

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "skipped"

    if has_spdx(content):
        return "skipped"

    header = build_header(style)
    new_content = insert_header(content, header, style)

    if new_content == content:
        return "skipped"

    newline = "\r\n" if "\r\n" in content and "\n" in content else "\n"
    if content.endswith("\r\n"):
        newline = "\r\n"
    elif content.endswith("\n"):
        newline = "\n"
    path.write_text(new_content, encoding="utf-8", newline=newline)
    return "updated"


def main() -> int:
    stats = {"updated": 0, "skipped": 0, "error": 0}
    for path in iter_files():
        result = process_file(path)
        stats[result] = stats.get(result, 0) + 1
        if result == "updated":
            rel = path.relative_to(ROOT)
            print(f"updated: {rel}")

    print(
        f"\nDone: {stats['updated']} updated, "
        f"{stats['skipped']} skipped, {stats.get('error', 0)} errors"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
