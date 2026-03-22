from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class SkillMeta:
    """Parsed representation of a SKILL.md file."""

    name: str
    description: str
    path: Path
    always_on: bool = False
    required_tools: list[str] = field(default_factory=list)
    required_bins: list[str] = field(default_factory=list)
    required_env: list[str] = field(default_factory=list)
    body: str = ""


def parse_skill_md(path: Path) -> SkillMeta:
    """Parse a SKILL.md file into a SkillMeta dataclass.

    Extracts YAML frontmatter and Markdown body. The `metadata` frontmatter
    field is a JSON string with kore-specific config (always-on flag, deps).
    Falls back gracefully when frontmatter or metadata is absent/malformed.
    """
    text = path.read_text()
    frontmatter, body = _split_frontmatter(text)

    name = frontmatter.get("name") or path.parent.name
    description = frontmatter.get("description", "")

    kore_meta: dict = {}
    raw_meta = frontmatter.get("metadata")
    if raw_meta:
        try:
            if isinstance(raw_meta, dict):
                kore_meta = raw_meta.get("kore", {})
            else:
                parsed = json.loads(str(raw_meta))
                kore_meta = parsed.get("kore", {})
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    always_on = bool(kore_meta.get("always", False))
    requires: dict = kore_meta.get("requires", {})

    return SkillMeta(
        name=name,
        description=description,
        path=path,
        always_on=always_on,
        required_tools=list(requires.get("tools", [])),
        required_bins=list(requires.get("bins", [])),
        required_env=list(requires.get("env", [])),
        body=body.strip(),
    )


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from Markdown body.

    Returns (frontmatter_dict, body_text). If no frontmatter found, returns ({}, text).
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_text = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")

    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        fm = {}

    return fm, body
