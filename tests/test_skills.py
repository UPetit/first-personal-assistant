from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
import respx
import httpx


# ── helpers ──────────────────────────────────────────────────────────────────

def write_skill_md(directory: Path, name: str, body: str = "# Instructions\nDo things.", **fm_extra) -> Path:
    """Write a SKILL.md to directory/<name>/SKILL.md and return the path."""
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    meta = json.dumps({"kore": {"always": fm_extra.pop("always", False), "requires": fm_extra.pop("requires", {})}})
    frontmatter_lines = [
        "---",
        f"name: {fm_extra.pop('skill_name', name)}",
        f"description: {fm_extra.pop('description', 'A test skill')}",
        f"metadata: '{meta}'",
        "---",
    ]
    content = "\n".join(frontmatter_lines) + "\n" + body
    path = skill_dir / "SKILL.md"
    path.write_text(content)
    return path


# ── loader tests ─────────────────────────────────────────────────────────────

def test_parse_skill_md_basic(tmp_path):
    from kore.skills.loader import parse_skill_md

    path = write_skill_md(tmp_path, "web-research", description="Search the web")
    meta = parse_skill_md(path)

    assert meta.name == "web-research"
    assert meta.description == "Search the web"
    assert meta.always_on is False
    assert meta.required_tools == []
    assert meta.body.startswith("# Instructions")


def test_parse_skill_md_always_on(tmp_path):
    from kore.skills.loader import parse_skill_md

    path = write_skill_md(tmp_path, "memory-management", always=True)
    meta = parse_skill_md(path)

    assert meta.always_on is True


def test_parse_skill_md_required_tools(tmp_path):
    from kore.skills.loader import parse_skill_md

    path = write_skill_md(
        tmp_path, "search-skill",
        requires={"tools": ["web_search", "scrape_url"]},
    )
    meta = parse_skill_md(path)

    assert "web_search" in meta.required_tools
    assert "scrape_url" in meta.required_tools


def test_parse_skill_md_required_bins_and_env(tmp_path):
    from kore.skills.loader import parse_skill_md

    path = write_skill_md(
        tmp_path, "git-skill",
        requires={"bins": ["git"], "env": ["GH_TOKEN"]},
    )
    meta = parse_skill_md(path)

    assert "git" in meta.required_bins
    assert "GH_TOKEN" in meta.required_env


def test_parse_skill_md_no_frontmatter(tmp_path):
    from kore.skills.loader import parse_skill_md

    skill_dir = tmp_path / "bare-skill"
    skill_dir.mkdir()
    path = skill_dir / "SKILL.md"
    path.write_text("# Bare Skill\nNo frontmatter here.")

    meta = parse_skill_md(path)

    # name falls back to directory name
    assert meta.name == "bare-skill"
    assert meta.body.startswith("# Bare Skill")


def test_parse_skill_md_path_stored(tmp_path):
    from kore.skills.loader import parse_skill_md

    path = write_skill_md(tmp_path, "path-check")
    meta = parse_skill_md(path)

    assert meta.path == path


def test_parse_skill_md_malformed_metadata(tmp_path):
    from kore.skills.loader import parse_skill_md

    skill_dir = tmp_path / "bad-meta"
    skill_dir.mkdir()
    path = skill_dir / "SKILL.md"
    path.write_text("---\nname: bad-meta\nmetadata: '{not valid json'\n---\n# Body")

    meta = parse_skill_md(path)

    assert meta.name == "bad-meta"
    assert meta.always_on is False
    assert meta.required_tools == []


# ── registry tests ────────────────────────────────────────────────────────────

def test_registry_discovers_builtin_skills(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "web-research", description="Search the web")
    write_skill_md(builtin, "content-writer", description="Write content")

    registry = SkillRegistry(builtin, user)
    names = [s.name for s in registry.all_skills()]

    assert "web-research" in names
    assert "content-writer" in names


def test_registry_user_overrides_builtin(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "web-research", description="Builtin version")
    write_skill_md(user, "web-research", description="User version")

    registry = SkillRegistry(builtin, user)
    skill = next(s for s in registry.all_skills() if s.name == "web-research")

    assert skill.description == "User version"


def test_registry_empty_user_dir(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "nonexistent_user"
    builtin.mkdir()
    # user dir does not exist — should not raise

    write_skill_md(builtin, "web-research")
    registry = SkillRegistry(builtin, user)

    assert len(registry.all_skills()) == 1


def test_registry_dependency_check_passes(tmp_path, monkeypatch):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "search-skill", requires={"tools": ["web_search"]})
    registry = SkillRegistry(builtin, user)
    skill = registry.all_skills()[0]

    assert registry.check_dependencies(skill, available_tools=["web_search"]) is True


def test_registry_dependency_check_fails_missing_tool(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "search-skill", requires={"tools": ["web_search"]})
    registry = SkillRegistry(builtin, user)
    skill = registry.all_skills()[0]

    assert registry.check_dependencies(skill, available_tools=[]) is False


def test_registry_dependency_check_fails_missing_env(tmp_path, monkeypatch):
    from kore.skills.registry import SkillRegistry

    monkeypatch.delenv("GH_TOKEN", raising=False)

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "git-skill", requires={"env": ["GH_TOKEN"]})
    registry = SkillRegistry(builtin, user)
    skill = registry.all_skills()[0]

    assert registry.check_dependencies(skill, available_tools=[]) is False


def test_registry_dependency_check_fails_missing_bin(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "git-skill", requires={"bins": ["__nonexistent_binary_xyz__"]})
    registry = SkillRegistry(builtin, user)
    skill = registry.all_skills()[0]

    assert registry.check_dependencies(skill, available_tools=[]) is False


def test_registry_get_skills_for_executor_explicit(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "web-research", requires={"tools": ["web_search"]})
    write_skill_md(builtin, "content-writer")

    registry = SkillRegistry(builtin, user)
    skills = registry.get_skills_for_executor(
        skill_names=["web-research"],
        available_tools=["web_search"],
    )

    assert len(skills) == 1
    assert skills[0].name == "web-research"


def test_registry_get_skills_for_executor_wildcard(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "web-research", requires={"tools": ["web_search"]})
    write_skill_md(builtin, "content-writer")

    registry = SkillRegistry(builtin, user)
    skills = registry.get_skills_for_executor(
        skill_names=["*"],
        available_tools=["web_search"],
    )

    # content-writer has no tool deps so passes; web-research needs web_search (provided)
    names = [s.name for s in skills]
    assert "web-research" in names
    assert "content-writer" in names


def test_registry_wildcard_excludes_unsatisfied_deps(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "search-skill", requires={"tools": ["web_search"]})
    write_skill_md(builtin, "writer-skill")

    registry = SkillRegistry(builtin, user)
    skills = registry.get_skills_for_executor(["*"], available_tools=[])

    names = [s.name for s in skills]
    assert "search-skill" not in names   # missing web_search
    assert "writer-skill" in names


def test_registry_level1_summary_xml(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "web-research", description="Search the web")

    registry = SkillRegistry(builtin, user)
    summary = registry.build_level1_summary()

    assert "<skills>" in summary
    assert 'name="web-research"' in summary
    assert 'description="Search the web"' in summary
    assert "</skills>" in summary


def test_registry_level2_context_only_always_on(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "memory-management", always=True, body="Always on body.")
    write_skill_md(builtin, "web-research", always=False, body="Not always on.")

    registry = SkillRegistry(builtin, user)
    ctx = registry.build_level2_context()

    assert "Always on body." in ctx
    assert "Not always on." not in ctx


def test_registry_level2_empty_when_no_always_on(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    write_skill_md(builtin, "web-research", always=False)

    registry = SkillRegistry(builtin, user)
    assert registry.build_level2_context() == ""


def test_registry_hot_reload(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    registry = SkillRegistry(builtin, user)
    assert len(registry.all_skills()) == 0

    # Simulate ClawHub install: drop SKILL.md into user dir
    write_skill_md(user, "new-skill", description="Hot-reloaded")

    # Before reload: not visible
    assert len(registry.all_skills()) == 0

    registry.reload()

    # After reload: visible
    assert len(registry.all_skills()) == 1
    assert registry.all_skills()[0].name == "new-skill"


def test_registry_hot_reload_wildcard_executor_sees_new_skill(tmp_path):
    from kore.skills.registry import SkillRegistry

    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir(); user.mkdir()

    registry = SkillRegistry(builtin, user)

    # Install new skill
    write_skill_md(user, "git-manager", description="Git operations")
    registry.reload()

    skills = registry.get_skills_for_executor(["*"], available_tools=[])
    assert any(s.name == "git-manager" for s in skills)


# ── clawhub tests ─────────────────────────────────────────────────────────────

def _make_zip(skill_md_content: str) -> bytes:
    """Create a ZIP archive containing a single SKILL.md."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", skill_md_content)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_clawhub_search_returns_skills():
    from kore.skills.clawhub import ClawHubClient

    base = "https://clawhub.dev/api/v1"
    client = ClawHubClient(base_url=base)

    with respx.mock:
        respx.get(f"{base}/skills/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "git-manager",
                            "description": "Manage git repos",
                            "download_url": f"{base}/skills/git-manager/download",
                        }
                    ]
                },
            )
        )
        results = await client.search("git")

    assert len(results) == 1
    assert results[0].name == "git-manager"
    assert results[0].description == "Manage git repos"


@pytest.mark.asyncio
async def test_clawhub_search_empty_results():
    from kore.skills.clawhub import ClawHubClient

    base = "https://clawhub.dev/api/v1"
    client = ClawHubClient(base_url=base)

    with respx.mock:
        respx.get(f"{base}/skills/search").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        results = await client.search("no-such-skill")

    assert results == []


@pytest.mark.asyncio
async def test_clawhub_install_extracts_skill_md(tmp_path):
    from kore.skills.clawhub import ClawHubClient

    base = "https://clawhub.dev/api/v1"
    client = ClawHubClient(base_url=base)

    skill_md = (
        "---\nname: git-manager\ndescription: Manage git repos\n---\n# Git Manager\nDo git."
    )
    zip_bytes = _make_zip(skill_md)

    with respx.mock:
        respx.get(f"{base}/skills/search").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "git-manager",
                            "description": "Manage git repos",
                            "download_url": f"{base}/skills/git-manager/download",
                        }
                    ]
                },
            )
        )
        respx.get(f"{base}/skills/git-manager/download").mock(
            return_value=httpx.Response(200, content=zip_bytes)
        )
        skill_dir = await client.install("git-manager", tmp_path)

    assert skill_dir.exists()
    assert (skill_dir / "SKILL.md").exists()
    assert "Git Manager" in (skill_dir / "SKILL.md").read_text()


@pytest.mark.asyncio
async def test_clawhub_install_raises_when_not_found(tmp_path):
    from kore.skills.clawhub import ClawHubClient, ClawHubError

    base = "https://clawhub.dev/api/v1"
    client = ClawHubClient(base_url=base)

    with respx.mock:
        respx.get(f"{base}/skills/search").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        with pytest.raises(ClawHubError, match="not found"):
            await client.install("nonexistent-skill", tmp_path)


@pytest.mark.asyncio
async def test_clawhub_install_zipslip_prevented(tmp_path):
    """ZIP with path-traversal member cannot escape the target directory."""
    from kore.skills.clawhub import ClawHubClient

    base = "https://clawhub.dev/api/v1"
    client = ClawHubClient(base_url=base)

    # Build a ZIP with a path-traversal member
    import io as _io, zipfile as _zf
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: safe\n---\n# Safe")
        zf.writestr("../../evil.txt", "malicious content")
    zip_bytes = buf.getvalue()

    with respx.mock:
        respx.get(f"{base}/skills/search").mock(
            return_value=httpx.Response(
                200,
                json={"results": [{"name": "safe-skill", "description": "safe",
                                   "download_url": f"{base}/skills/safe-skill/download"}]},
            )
        )
        respx.get(f"{base}/skills/safe-skill/download").mock(
            return_value=httpx.Response(200, content=zip_bytes)
        )
        skill_dir = await client.install("safe-skill", tmp_path)

    # The evil.txt should NOT have been extracted outside the skill_dir
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path.parent / "evil.txt").exists()
    # The SKILL.md should still be extracted correctly
    assert (skill_dir / "SKILL.md").exists()


# ── skill_tools tests ─────────────────────────────────────────────────────────

def _make_skill_deps(tmp_path, config_override=None):
    """Build a KoreDeps with a real SkillRegistry pointing at tmp_path."""
    from types import SimpleNamespace
    from pydantic import SecretStr
    from kore.agents.deps import KoreDeps
    from kore.config import KoreConfig, LLMConfig, LLMProviderConfig, SkillsConfig
    from kore.skills.registry import SkillRegistry

    cfg = KoreConfig(
        version="1.0.0",
        llm=LLMConfig(providers={"anthropic": LLMProviderConfig(api_key=SecretStr("key"))}),
        skills=SkillsConfig(clawhub_base_url="https://clawhub.dev/api/v1"),
    )
    registry = SkillRegistry(builtin_dir=tmp_path / "builtin", user_dir=tmp_path / "user")
    deps = KoreDeps(config=cfg, skill_registry=registry)
    return SimpleNamespace(deps=deps)


@pytest.mark.asyncio
async def test_skill_search_returns_results(tmp_path):
    """skill_search returns formatted list from ClawHub."""
    from kore.tools.skill_tools import skill_search

    ctx = _make_skill_deps(tmp_path)
    base = ctx.deps.config.skills.clawhub_base_url

    with respx.mock:
        respx.get(f"{base}/skills/search").mock(
            return_value=httpx.Response(
                200,
                json={"results": [
                    {"name": "git-manager", "description": "Manage git repos", "download_url": f"{base}/skills/git-manager/download"},
                ]},
            )
        )
        result = await skill_search(ctx, "git")

    assert "git-manager" in result
    assert "Manage git repos" in result


@pytest.mark.asyncio
async def test_skill_search_empty(tmp_path):
    """skill_search reports no results gracefully."""
    from kore.tools.skill_tools import skill_search

    ctx = _make_skill_deps(tmp_path)
    base = ctx.deps.config.skills.clawhub_base_url

    with respx.mock:
        respx.get(f"{base}/skills/search").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        result = await skill_search(ctx, "nonexistent")

    assert "No skills found" in result


@pytest.mark.asyncio
async def test_skill_install_places_in_user_dir_and_reloads(tmp_path):
    """skill_install downloads to user_dir and hot-reloads the registry."""
    from kore.tools.skill_tools import skill_install

    ctx = _make_skill_deps(tmp_path)
    base = ctx.deps.config.skills.clawhub_base_url
    registry = ctx.deps.skill_registry

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", '---\nname: git-manager\ndescription: Manage git\nmetadata: \'{"kore":{"always":false,"requires":{}}}\'\n---\n# Git')
    zip_bytes = buf.getvalue()

    with respx.mock:
        respx.get(f"{base}/skills/search").mock(
            return_value=httpx.Response(
                200,
                json={"results": [{"name": "git-manager", "description": "Manage git repos",
                                   "download_url": f"{base}/skills/git-manager/download"}]},
            )
        )
        respx.get(f"{base}/skills/git-manager/download").mock(
            return_value=httpx.Response(200, content=zip_bytes)
        )
        result = await skill_install(ctx, "git-manager")

    assert "git-manager" in result
    assert "reloaded" in result
    # Installed into user_dir
    assert (registry.user_dir / "git-manager").exists()
    # Registry picked up the new skill after reload
    assert any(s.name == "git-manager" for s in registry.all_skills())


@pytest.mark.asyncio
async def test_skill_install_not_found(tmp_path):
    """skill_install returns error message when skill not on ClawHub."""
    from kore.tools.skill_tools import skill_install

    ctx = _make_skill_deps(tmp_path)
    base = ctx.deps.config.skills.clawhub_base_url

    with respx.mock:
        respx.get(f"{base}/skills/search").mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        result = await skill_install(ctx, "ghost-skill")

    assert "Install failed" in result


@pytest.mark.asyncio
async def test_skill_install_no_registry(tmp_path):
    """skill_install returns graceful error when registry is not available."""
    from types import SimpleNamespace
    from pydantic import SecretStr
    from kore.agents.deps import KoreDeps
    from kore.config import KoreConfig, LLMConfig, LLMProviderConfig
    from kore.tools.skill_tools import skill_install

    cfg = KoreConfig(
        version="1.0.0",
        llm=LLMConfig(providers={"anthropic": LLMProviderConfig(api_key=SecretStr("key"))}),
    )
    ctx = SimpleNamespace(deps=KoreDeps(config=cfg, skill_registry=None))
    result = await skill_install(ctx, "any-skill")

    assert "not available" in result
