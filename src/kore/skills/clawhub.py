from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

CLAWHUB_BASE_URL = "https://clawhub.dev/api/v1"


class ClawHubError(Exception):
    """Raised for ClawHub API errors (skill not found, HTTP failure, etc.)."""


@dataclass
class ClawHubSkill:
    name: str
    description: str
    download_url: str


class ClawHubClient:
    """HTTP client for the ClawHub skill registry."""

    def __init__(self, base_url: str = CLAWHUB_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")

    async def search(self, query: str) -> list[ClawHubSkill]:
        """Search ClawHub for skills matching *query*. Returns a list of matches."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._base_url}/skills/search",
                params={"q": query},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            ClawHubSkill(
                name=item["name"],
                description=item.get("description", ""),
                download_url=item["download_url"],
            )
            for item in data.get("results", [])
        ]

    async def install(self, skill_name: str, target_dir: Path) -> Path:
        """Download and install *skill_name* from ClawHub into *target_dir*.

        Downloads a ZIP archive, extracts it to ``target_dir/<skill_name>/``.
        Returns the path to the installed skill directory.
        Raises :class:`ClawHubError` if the skill is not found.
        """
        results = await self.search(skill_name)
        match = next((r for r in results if r.name == skill_name), None)
        if match is None:
            raise ClawHubError(f"Skill {skill_name!r} not found on ClawHub")

        async with httpx.AsyncClient() as client:
            resp = await client.get(match.download_url, timeout=30.0)
            resp.raise_for_status()
            zip_data = resp.content

        skill_dir = target_dir / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            for member in zf.infolist():
                # Sanitize: resolve the target path and ensure it stays within skill_dir.
                # This prevents ZipSlip attacks (e.g., "../../etc/cron.d/evil").
                member_path = skill_dir / member.filename
                try:
                    member_path.resolve().relative_to(skill_dir.resolve())
                except ValueError:
                    # Path escapes the target directory — skip silently.
                    continue
                zf.extract(member, skill_dir)

        return skill_dir
