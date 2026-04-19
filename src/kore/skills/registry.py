from __future__ import annotations

import os
import shutil
from pathlib import Path
from xml.sax.saxutils import quoteattr

from kore.skills.loader import SkillMeta, parse_skill_md


class SkillRegistry:
    """Discovers, indexes, and serves skills from built-in and user directories.

    Built-in skills live in the project `skills/` directory.
    User skills live in `workspace/skills/` (or a configured path).
    User skills with the same name override built-in ones.
    """

    def __init__(self, builtin_dir: Path, user_dir: Path) -> None:
        self._builtin_dir = builtin_dir
        self._user_dir = user_dir
        self._skills: dict[str, SkillMeta] = {}
        self.load_all()

    def load_all(self) -> None:
        """Discover and parse all skills. User skills override built-ins by name."""
        self._skills = {}
        for skill_md in sorted(self._builtin_dir.glob("*/SKILL.md")):
            meta = parse_skill_md(skill_md)
            self._skills[meta.name] = meta
        if self._user_dir.exists():
            for skill_md in sorted(self._user_dir.glob("*/SKILL.md")):
                meta = parse_skill_md(skill_md)
                self._skills[meta.name] = meta

    @property
    def user_dir(self) -> Path:
        """Directory where user and ClawHub-installed skills live."""
        return self._user_dir

    def reload(self) -> None:
        """Re-scan skill directories. Call after installing a new skill."""
        self.load_all()

    def all_skills(self) -> list[SkillMeta]:
        """Return all loaded skills."""
        return list(self._skills.values())

    def get_skills_for_executor(
        self,
        skill_names: list[str],
        available_tools: list[str],
    ) -> list[SkillMeta]:
        """Return skills for an executor, filtered by satisfied dependencies.

        Pass ``["*"]`` to include all skills with satisfied dependencies.
        """
        if skill_names == ["*"]:
            candidates = list(self._skills.values())
        else:
            candidates = [self._skills[n] for n in skill_names if n in self._skills]
        return [s for s in candidates if self.check_dependencies(s, available_tools)]

    def check_dependencies(self, skill: SkillMeta, available_tools: list[str]) -> bool:
        """Return True if all tool, binary, and env var dependencies are satisfied."""
        for tool in skill.required_tools:
            if tool not in available_tools:
                return False
        for bin_name in skill.required_bins:
            if not shutil.which(bin_name):
                return False
        for env_var in skill.required_env:
            if not os.environ.get(env_var):
                return False
        return True

    def build_level1_summary(self) -> str:
        """Build compact XML listing all skills (Level 1 — always included in prompt).

        ~100 tokens per skill. Lets the agent know what skills exist and
        where to find them (for on-demand Level 3 loading via read_file).
        """
        lines = ["<skills>  <!-- use read_skill(name) to load full instructions -->"]
        for skill in self._skills.values():
            lines.append(
                f"  <skill name={quoteattr(skill.name)}"
                f" description={quoteattr(skill.description)} />"
            )
        lines.append("</skills>")
        return "\n".join(lines)

    def build_level2_context(
        self,
        skills: list[SkillMeta] | None = None,
        always_map: dict[str, bool] | None = None,
    ) -> str:
        """Return full Markdown body of always-on skills (Level 2).

        If *skills* is given, only skills in that list are considered.
        If *skills* is None, all loaded skills are considered.
        *always_map* overrides the skill's own ``always_on`` flag per executor
        assignment (key = skill name, value = True/False). When provided, a
        skill is included iff ``always_map.get(name, skill.always_on)`` is True.
        Returns empty string if no always-on skills match.
        """
        source = skills if skills is not None else list(self._skills.values())
        parts = [
            f"## Skill: {s.name}\n\n{s.body}"
            for s in source
            if (always_map.get(s.name, s.always_on) if always_map is not None else s.always_on)
        ]
        return "\n\n---\n\n".join(parts)
